#!/usr/bin/env node
/**
 * Live Chrome verification. Secrets come only from the ignored session file.
 * Usage: node scripts/browser_verify.mjs .deployment/browser-session.json
 * Session: {url, custom_token, job_id?, before_path?, output_dir?, delete_result?}
 * Never prints credentials, bearer links, or image bytes.
 */
import { readFile, mkdir, writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const requireFrontend = createRequire(resolve(root, 'frontend/package.json'));
const { chromium, devices } = requireFrontend('playwright');
const firebaseVersion = requireFrontend('firebase/package.json').version;
const sessionPath = resolve(process.argv[2] || resolve(root, '.deployment/browser-session.json'));
const session = JSON.parse(await readFile(sessionPath, 'utf8'));
const baseUrl = String(session.url || session.base_url || session.service_url || '').replace(/\/$/, '');
const customToken = session.custom_token || session.customToken;
session.job_id = session.job_id || session.jobId;
if (!baseUrl.startsWith('https://') && !baseUrl.startsWith('http://localhost') && !baseUrl.startsWith('http://127.0.0.1')) throw new Error('Supply an HTTPS service URL or local test URL.');
if (!customToken) throw new Error('The ignored browser session file needs custom_token.');
const output = resolve(root, session.output_dir || 'verification/browser');
await mkdir(output, { recursive: true });
const sensitive = [customToken];
const redact = value => {
 let text = String(value);
 for (const secret of sensitive) if (secret) text = text.split(secret).join('[redacted]');
 return text.replace(/eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+/g, '[redacted-token]').replace(/\/share#[A-Za-z0-9_-]+/g, '/share#[redacted]');
};
const report = { service_url: baseUrl, checked_at: new Date().toISOString(), browser: 'Installed Google Chrome', physical_device_testing: false, checks: [], scenarios: [], errors: [], external_protocol_events: [], external_telemetry_observations: [], limitations: [] };
let galleryFixture = null;
const observedErrors = [];
const record = (name, details = {}) => report.checks.push({ name, passed: true, ...details });
const assert = (condition, message) => { if (!condition) throw new Error(message); };
const browser = await chromium.launch({ executablePath: session.chrome_path || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', headless: true });
function watch(page, scenario) {
 const errors = [];
 observedErrors.push(errors);
 page.__styleReelHttp = [];
 page.on('response', response => { const url = new URL(response.url()); if (url.pathname.startsWith('/api/') && response.status() >= 400) { const request = response.request(); page.__styleReelHttp.push({ at: new Date().toISOString(), path: url.pathname, status: response.status(), method: request.method(), had_authorization: Boolean(request.headers().authorization) }); } });
 page.on('pageerror', error => errors.push({ type: 'pageerror', message: redact(error.message), scenario }));
 page.on('console', message => {
  if (message.type() !== 'error') return;
  const url = message.location().url;
  if (/^https:\/\/(www\.google\.com|www\.recaptcha\.net)\/recaptcha\/(enterprise|api2)\/pat(?:\?|$)/.test(url) && message.text().includes('401')) {
   report.external_protocol_events.push({ type: 'recaptcha_private_access_token_negotiation', status: 401, url: new URL(url).origin + new URL(url).pathname, scenario, explanation: 'Google documents this 401 as expected PAT protocol negotiation; CAPTCHA remains operational.', source: 'https://docs.cloud.google.com/recaptcha/docs/private-access-tokens' }); return;
  }
  if (message.text().startsWith("Framing 'https://www.google.com/' violates the following report-only Content Security Policy directive:") && message.text().includes("frame-ancestors 'self'") && message.text().includes('no further action has been taken')) {
   report.external_telemetry_observations.push({ type: 'google_report_only_policy', message: redact(message.text()), scenario, explanation: 'Chrome identifies the framed Google origin and a report-only policy. The application serves an enforced frame-ancestors none policy, with no report-only header. This observation is retained separately from application violations.' }); return;
  }
  errors.push({ type: 'console', message: redact(message.text()), url: redact(url), at: new Date().toISOString(), scenario });
 });
 page.on('requestfailed', request => {
  const requestUrl = new URL(request.url());
  if (requestUrl.hostname === 'csp.withgoogle.com' && requestUrl.pathname.startsWith('/csp/frame-ancestors/') && request.failure()?.errorText === 'net::ERR_BLOCKED_BY_ORB') {
   report.external_telemetry_observations.push({ type: 'google_report_transport', message: `${redact(request.url())}: ${request.failure().errorText}`, scenario, explanation: 'Chrome blocked the Google telemetry-report response. No application-origin request failed.' }); return;
  }
  if (request.failure()?.errorText !== 'net::ERR_ABORTED') errors.push({ type: 'requestfailed', message: `${redact(request.url())}: ${request.failure()?.errorText}`, scenario });
 });
 return errors;
}
async function installViolationRecorder(page) {
 await page.addInitScript(() => {
  window.__styleReelCsp = [];
  document.addEventListener('securitypolicyviolation', event => window.__styleReelCsp.push({ directive: event.violatedDirective, blocked: event.blockedURI }));
 });
}
async function signIn(page, sessionToken = customToken) {
 // Official SDK instance writes the normal Firebase IndexedDB persistence entry.
 // Reload lets the application's bundled SDK restore it; no production debug API.
 await page.evaluate(async ({ token, version }) => {
  const configResponse = await fetch('/api/config');
  if (!configResponse.ok) throw new Error('Public Firebase configuration could not be read.');
  const config = await configResponse.json();
  const { initializeApp } = await import(`https://www.gstatic.com/firebasejs/${version}/firebase-app.js`);
  const { getAuth, setPersistence, indexedDBLocalPersistence, signInWithCustomToken, connectAuthEmulator } = await import(`https://www.gstatic.com/firebasejs/${version}/firebase-auth.js`);
  const app = initializeApp(config.firebase);
  const auth = getAuth(app);
  if (config.auth_emulator_url) connectAuthEmulator(auth, config.auth_emulator_url, { disableWarnings: true });
  await setPersistence(auth, indexedDBLocalPersistence);
  await signInWithCustomToken(auth, token);
 }, { token: sessionToken, version: firebaseVersion });
 await page.reload({ waitUntil: 'domcontentloaded' });
 await page.getByRole('heading', { name: /A new look/ }).waitFor({ timeout: 60000 });
}
async function nav(page, label, heading) {
 const menu = page.getByRole('button', { name: 'Open navigation', exact: true });
 if (await menu.isVisible()) await menu.click();
 await page.getByRole('button', { name: new RegExp(`^${label}`) }).click();
 await page.getByRole('heading', { name: heading }).waitFor();
}
async function layout(page, name) {
 await page.waitForTimeout(300);
 const dimensions = await page.evaluate(() => ({ viewport: innerWidth, document: document.documentElement.scrollWidth, body: document.body.scrollWidth }));
 assert(dimensions.document <= dimensions.viewport + 1 && dimensions.body <= dimensions.viewport + 1, `${name} has horizontal page overflow (${dimensions.document}/${dimensions.viewport}).`);
 await page.screenshot({ path: resolve(output, `${name}.png`), fullPage: true });
 const violations = await page.evaluate(() => { const recorded = window.__styleReelCsp || []; window.__styleReelCsp = []; return recorded; });
 for (const violation of violations) report.errors.push({ type: 'csp', ...violation, scenario: name });
 record(`Responsive ${name}`, { width: dimensions.viewport, horizontal_overflow: false });
}
async function prepareFixture(page, jobIdOverride) {
 const latest = JSON.parse(await readFile(sessionPath, 'utf8'));
 Object.assign(session, latest);
 session.job_id = session.job_id || latest.jobId;
 if (!session.job_id && !jobIdOverride) return null;
 const fixture = await page.evaluate(async ({ jobId, version }) => {
  const { getApps, initializeApp } = await import(`https://www.gstatic.com/firebasejs/${version}/firebase-app.js`);
  const { getAuth } = await import(`https://www.gstatic.com/firebasejs/${version}/firebase-auth.js`);
  const config = await fetch('/api/config').then(response => response.json());
  const auth = getAuth(getApps()[0] || initializeApp(config.firebase));
  await auth.authStateReady();
  if (!auth.currentUser) throw new Error('The official Firebase SDK could not restore the test session.');
  const token = await auth.currentUser.getIdToken();
  const headers = { Authorization: `Bearer ${token}` };
  const get = async path => { const response = await fetch(path, { headers }); if (!response.ok) throw new Error(`Authenticated fixture endpoint failed with HTTP ${response.status}.`); return response; };
  const [me, secret, job, settings] = await Promise.all([get('/api/me').then(r => r.json()), get('/api/me/gallery-key').then(r => r.json()), get(`/api/tryon/jobs/${jobId}`).then(r => r.json()), get('/api/settings').then(r => r.json())]);
  if (job.status !== 'succeeded' || !job.result_url) throw new Error(`The supplied live job is ${job.status}; a succeeded job is required.`);
  const blob = await get(job.result_url).then(r => r.blob());
  const after = await new Promise(resolve => { const reader = new FileReader(); reader.onload = () => resolve(reader.result); reader.readAsDataURL(blob); });
  return { uid: me.id, key: secret.key, item: { id: job.id, created_at: job.created_at, garment_names: job.garment_names, workflow: job.workflow, before: '', after, provider: settings.providers.find(p => p.id === settings.ai.provider)?.label || settings.ai.provider, model: settings.ai.model, estimated_cost_usd: job.estimated_cost_usd } };
 }, { jobId: jobIdOverride || session.job_id, version: firebaseVersion });
 const beforePath = resolve(root, session.before_path || 'verification/fixtures/person.png');
 const before = await readFile(beforePath);
 fixture.item.before = `data:image/${beforePath.endsWith('.png') ? 'png' : 'jpeg'};base64,${before.toString('base64')}`;
 return fixture;
}
async function seedEncryptedFixture(page, fixture) {
 if (!fixture) return;
 await page.evaluate(async ({ uid, key: encoded, item }) => {
  const raw = Uint8Array.from(atob(encoded), char => char.charCodeAt(0));
  const key = await crypto.subtle.importKey('raw', raw, 'AES-GCM', false, ['encrypt']);
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const ciphertext = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, key, new TextEncoder().encode(JSON.stringify(item)));
  const db = await new Promise((resolve, reject) => { const request = indexedDB.open('stylereel-private-gallery', 2); request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error); });
  await new Promise((resolve, reject) => { const transaction = db.transaction('images', 'readwrite'); transaction.objectStore('images').put({ id: `${uid}:${item.id}`, uid, iv, ciphertext }); transaction.oncomplete = resolve; transaction.onerror = () => reject(transaction.error); });
  db.close();
 }, fixture);
 await page.reload({ waitUntil: 'domcontentloaded' });
 await page.getByRole('heading', { name: /A new look/ }).waitFor({ timeout: 60000 });
}
async function verifyLocalPhotoAndSelection(page) {
 const uploads = [];
 const listener = request => { if (request.method() === 'POST' && new URL(request.url()).pathname === '/api/uploads') uploads.push(request); };
 page.on('request', listener);
 const full = await page.locator('.garment-select').evaluateAll(buttons => buttons.map(button => ({ name: button.getAttribute('aria-label'), category: button.querySelector('.garment-category')?.textContent })));
 const skirt = full.find(item => item.category?.toLowerCase() === 'skirts');
 const top = full.find(item => item.category?.toLowerCase() === 't-shirts');
 const dress = full.find(item => item.category?.toLowerCase() === 'dresses');
 if (skirt && top && dress) {
  await page.getByRole('button', { name: skirt.name, exact: true }).click();
  await page.getByRole('button', { name: top.name, exact: true }).click();
  assert(await page.locator('.selection-count').innerText() === '2/2', 'Upper/lower combination was not selected.');
  await page.getByRole('button', { name: dress.name, exact: true }).click();
  assert(await page.locator('.selection-count').innerText() === '1/2', 'Complete outfit did not replace separate pieces.');
  record('Live catalog upper/lower combination and full-body replacement');
 } else await page.locator('.garment-select').first().click();
 await page.locator('input[type="file"]').first().setInputFiles(resolve(root, session.before_path || 'verification/fixtures/person.png'));
 await page.getByRole('img', { name: 'Your selected photo', exact: true }).waitFor();
 await page.getByRole('button', { name: 'Crop', exact: true }).click();
 await page.getByRole('dialog', { name: 'Frame your photo', exact: true }).waitFor();
 const zoom = page.getByRole('slider', { name: 'Zoom', exact: true });
 await zoom.focus(); await zoom.press('ArrowRight');
 const applyCrop = page.getByRole('button', { name: 'Apply crop', exact: true });
 await page.waitForFunction(() => Array.from(document.querySelectorAll('[role="dialog"] .crop-container img')).every(image => image.complete && image.naturalWidth > 0));
 await applyCrop.click({ timeout: 30000 });
 await page.getByRole('dialog', { name: 'Frame your photo', exact: true }).waitFor({ state: 'hidden' });
 assert(uploads.length === 0, 'A photograph was uploaded before consent and submission.');
 const consent = page.getByRole('checkbox', { name: /^I consent to sending my photo/ });
 await consent.check();
 assert(await page.getByRole('button', { name: 'Generate my look', exact: true }).isEnabled(), 'Valid photo, garment and consent did not enable generation.');
 await consent.uncheck();
 assert(await page.getByRole('button', { name: 'Generate my look', exact: true }).isDisabled(), 'Generation can start without consent.');
 page.off('request', listener);
 record('Local photo selection, canvas crop, consent gate, and no pre-consent upload');
 await verifyPaidCatalogGeneration(page, consent);
}
async function verifyPaidCatalogGeneration(page, consent) {
 const markerPath = resolve(root, '.deployment/browser-generation.json');
 try {
  const prior = JSON.parse(await readFile(markerPath, 'utf8'));
  report.limitations.push(`Paid browser generation already submitted at ${prior.created_at}; it is not repeated.`);
  record('Browser generation replay protection', { prior_job: prior.job_id, extra_calls: 0 });
  return;
 } catch (error) { if (error.code !== 'ENOENT') throw new Error('The browser generation marker exists but is unreadable; no paid call will be repeated.'); }
 const metadata = await page.locator('.generation-summary').innerText();
 assert(metadata.includes('gemini-3-pro-image') && metadata.includes('Google'), 'The paid browser acceptance run must use Google Pro.');
 assert(await page.locator('.generation-estimate').innerText().then(text => text.includes('1 AI call')), 'The paid check must submit exactly one catalog image-generation call.');
 await writeFile(markerPath, JSON.stringify({ created_at: new Date().toISOString(), provider: 'google', model: 'gemini-3-pro-image', status: 'requested' }, null, 2) + '\n', { mode: 0o600, flag: 'wx' });
 await consent.check();
 const responsePromise = page.waitForResponse(response => new URL(response.url()).pathname === '/api/tryon/catalog' && response.request().method() === 'POST');
 await page.getByRole('button', { name: 'Generate my look', exact: true }).click();
 const response = await responsePromise;
 if (response.status() !== 202) throw new Error(`Browser generation submission was rejected with HTTP ${response.status()}.`);
 const job = await response.json();
 await writeFile(markerPath, JSON.stringify({ job_id: job.id, created_at: new Date().toISOString(), provider: 'google', model: 'gemini-3-pro-image', status: 'submitted' }, null, 2) + '\n', { mode: 0o600 });
 console.log('Browser catalog job accepted; waiting for its real Google result.');
 await page.getByRole('heading', { name: /Looks like your/ }).waitFor({ timeout: 360000 });
 await page.waitForFunction(() => Array.from(document.querySelectorAll('.result-photo img')).every(image => image.complete && image.naturalWidth > 0));
 await layout(page, 'desktop-browser-generated-result');
 const completed = await page.evaluate(async ({ jobId, version }) => {
  const { getApps, initializeApp } = await import(`https://www.gstatic.com/firebasejs/${version}/firebase-app.js`);
  const { getAuth } = await import(`https://www.gstatic.com/firebasejs/${version}/firebase-auth.js`);
  const config = await fetch('/api/config').then(response => response.json());
  const auth = getAuth(getApps()[0] || initializeApp(config.firebase));
  await auth.authStateReady();
  const token = await auth.currentUser.getIdToken();
  const response = await fetch(`/api/tryon/jobs/${jobId}`, { headers: { Authorization: `Bearer ${token}` } });
  if (!response.ok) throw new Error(`Completed browser job could not be read: HTTP ${response.status}.`);
  const completedJob = await response.json();
  const db = await new Promise((resolve, reject) => { const request = indexedDB.open('stylereel-private-gallery', 2); request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error); });
  const saved = await new Promise((resolve, reject) => { const request = db.transaction('images').objectStore('images').get(`${auth.currentUser.uid}:${jobId}`); request.onsuccess = () => resolve(Boolean(request.result?.ciphertext)); request.onerror = () => reject(request.error); });
  db.close();
  return { status: completedJob.status, reserved_estimate_usd: completedJob.estimated_cost_usd, encrypted_save: saved };
 }, { jobId: job.id, version: firebaseVersion });
 assert(completed.status === 'succeeded' && completed.encrypted_save, 'The live generated job was not automatically encrypted in the local gallery.');
 await writeFile(markerPath, JSON.stringify({ job_id: job.id, created_at: new Date().toISOString(), provider: 'google', model: 'gemini-3-pro-image', status: 'succeeded', reserved_estimate_usd: completed.reserved_estimate_usd }, null, 2) + '\n', { mode: 0o600 });
 await page.reload({ waitUntil: 'domcontentloaded' });
 await page.getByRole('heading', { name: /A new look/ }).waitFor({ timeout: 60000 });
 record('One real browser-driven Google Pro catalog generation, polling, render, and encrypted save', { job_id: job.id, authorized_extra_calls: 1, reserved_estimate_usd: completed.reserved_estimate_usd });
}
async function verifyPasswordSignIn() {
 let credentials;
 try { credentials = JSON.parse(await readFile(resolve(root, '.deployment/login-test.json'), 'utf8')); }
 catch { report.limitations.push('Enterprise email/password flow skipped: the private login-test file is not available.'); return; }
 sensitive.push(credentials.email, credentials.password);
 const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
 const page = await context.newPage();
 const errors = watch(page, 'enterprise-password-login');
 await installViolationRecorder(page);
 await page.goto(credentials.url || baseUrl, { waitUntil: 'domcontentloaded' });
 await page.getByRole('heading', { name: 'Let’s find your look.', exact: true }).waitFor({ timeout: 60000 });
 await page.getByRole('textbox', { name: 'Email address', exact: true }).fill(credentials.email);
 await page.getByLabel('Password', { exact: true }).fill(credentials.password);
 await page.getByRole('button', { name: 'Enter the studio', exact: true }).click();
 const outcome = await Promise.race([
  page.getByRole('heading', { name: 'Make this account yours.', exact: true }).waitFor({ timeout: 60000 }).then(() => 'password-change'),
  page.getByRole('alert').waitFor({ timeout: 60000 }).then(() => 'error'),
 ]);
 if (outcome === 'error') {
  const message = await page.getByRole('alert').innerText();
  await page.screenshot({ path: resolve(output, 'enterprise-login-blocked.png'), fullPage: true });
  report.errors.push({ type: 'enterprise-password-login', message: redact(message), enforcement_disabled: false });
  await context.close(); return;
 }
 await layout(page, 'enterprise-password-change');
 record('Normal email/password Enterprise sign-in reaches first-password gate');
 const { randomBytes } = await import('node:crypto');
 const newPassword = randomBytes(24).toString('base64url') + '!aA7';
 sensitive.push(newPassword);
 await page.getByLabel(/^New password/).fill(newPassword);
 await page.getByLabel('Confirm new password', { exact: true }).fill(newPassword);
 await page.getByRole('button', { name: 'Save new password', exact: true }).click();
 await page.getByRole('heading', { name: 'Let’s find your look.', exact: true }).waitFor({ timeout: 60000 });
 await page.getByRole('textbox', { name: 'Email address', exact: true }).fill(credentials.email);
 await page.getByLabel('Password', { exact: true }).fill(newPassword);
 await page.getByRole('button', { name: 'Enter the studio', exact: true }).click();
 await page.getByRole('heading', { name: /A new look/ }).waitFor({ timeout: 60000 });
 await layout(page, 'enterprise-login-studio');
 record('First password update, session revocation, and normal sign-in with new password');
 await page.getByRole('button', { name: 'Change password', exact: true }).click();
 await page.getByRole('dialog', { name: 'Change your password', exact: true }).waitFor();
 await page.getByLabel('Current password', { exact: true }).fill(newPassword);
 const voluntaryPassword = randomBytes(24).toString('base64url') + '!aA7';
 sensitive.push(voluntaryPassword);
 await page.getByLabel(/^New password/).fill(voluntaryPassword);
 await page.getByLabel('Confirm new password', { exact: true }).fill(voluntaryPassword);
 await page.getByRole('button', { name: 'Update password', exact: true }).click();
 await page.getByRole('heading', { name: 'Let’s find your look.', exact: true }).waitFor({ timeout: 60000 });
 await page.getByRole('textbox', { name: 'Email address', exact: true }).fill(credentials.email);
 await page.getByLabel('Password', { exact: true }).fill(voluntaryPassword);
 await page.getByRole('button', { name: 'Enter the studio', exact: true }).click();
 await page.getByRole('heading', { name: /A new look/ }).waitFor({ timeout: 60000 });
 record('Voluntary password change reauthenticates with current password, logs out, and accepts the new password');
 await context.close();
}
async function authToken(page) {
 return page.evaluate(async version => {
  const { getApps, initializeApp } = await import(`https://www.gstatic.com/firebasejs/${version}/firebase-app.js`);
  const { getAuth } = await import(`https://www.gstatic.com/firebasejs/${version}/firebase-auth.js`);
  const config = await fetch('/api/config').then(response => response.json());
  const auth = getAuth(getApps()[0] || initializeApp(config.firebase));
  await auth.authStateReady();
  if (!auth.currentUser) throw new Error('The test session is not authenticated.');
  return auth.currentUser.getIdToken();
 }, firebaseVersion);
}
async function authRequest(page, path, method = 'GET', data) {
 const token = await authToken(page);
 return page.context().request.fetch(`${baseUrl}${path}`, { method, headers: { Authorization: `Bearer ${token}` }, ...(data === undefined ? {} : { data }) });
}
async function encryptedRecordIds(page, uid) {
 return page.evaluate(async uid => {
  const db = await new Promise((resolve, reject) => { const request = indexedDB.open('stylereel-private-gallery', 2); request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error); });
  const records = await new Promise((resolve, reject) => { const request = db.transaction('images').objectStore('images').index('uid').getAll(uid); request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error); });
  db.close(); return records.map(record => record.id.slice(uid.length + 1));
 }, uid);
}
function blockPaidSubmissions(page, attempts) {
 return page.route('**/api/tryon/**', route => {
  const request = route.request();
  const path = new URL(request.url()).pathname;
  if (request.method() === 'POST' && ['/api/tryon/catalog', '/api/tryon/holding-garment'].includes(path)) { attempts.push(path); return route.abort('blockedbyclient'); }
  return route.continue();
 });
}
async function verifyGalleryManagement() {
 const forbiddenSubmissions = [];
 const adminContext = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
 const page = await adminContext.newPage();
 watch(page, 'gallery-management-admin'); await installViolationRecorder(page); await blockPaidSubmissions(page, forbiddenSubmissions);
 let settings;
 try {
  await page.goto(baseUrl, { waitUntil: 'domcontentloaded' });
  await page.getByRole('heading', { name: 'Let’s find your look.', exact: true }).waitFor({ timeout: 60000 });
  await signIn(page);
  const settingsResponse = await authRequest(page, '/api/admin/settings');
  assert(settingsResponse.ok(), 'Admin gallery configuration could not be read.'); settings = await settingsResponse.json();
  const original = await prepareFixture(page);
  const marker = JSON.parse(await readFile(resolve(root, '.deployment/browser-generation.json'), 'utf8'));
  assert(marker.status === 'succeeded' && marker.job_id, 'The guarded browser generation is not available for recovery.');
  const generated = await prepareFixture(page, marker.job_id);
  const imageData = generated.item.after.match(/^data:image\/([^;]+);base64,(.+)$/s);
  assert(imageData, 'Generated output could not be preserved locally.');
  await writeFile(resolve(output, `browser-generated-original.${imageData[1] === 'jpeg' ? 'jpg' : imageData[1]}`), Buffer.from(imageData[2], 'base64'));
  await seedEncryptedFixture(page, original);
  const configured = await authRequest(page, '/api/admin/settings', 'PUT', { ai: settings.ai, rate_limits: settings.rate_limits, gallery: { max_images: 1 } });
  assert(configured.ok(), 'Temporary gallery capacity could not be set.');
  await page.reload({ waitUntil: 'domcontentloaded' }); await page.getByRole('heading', { name: /A new look/ }).waitFor();
  await page.locator('.garment-select').first().click();
  await page.locator('input[type="file"]').first().setInputFiles(resolve(root, session.before_path || 'verification/fixtures/person.png'));
  await page.getByRole('checkbox', { name: /^I consent to sending my photo/ }).check();
  await page.getByRole('button', { name: 'Generate my look', exact: true }).click();
  const warning = page.getByRole('dialog', { name: 'Make room for a new look', exact: true }); await warning.waitFor();
  assert((await warning.innerText()).includes('oldest saved look'), 'Gallery replacement warning omits eviction guidance.');
  await layout(page, 'gallery-capacity-warning');
  await warning.getByRole('button', { name: 'Keep my gallery', exact: true }).click(); await warning.waitFor({ state: 'hidden' });
  assert((await encryptedRecordIds(page, original.uid)).join() === original.item.id, 'Cancelling capacity warning changed the saved look.');
  record('Capacity warning and cancellation preserve the existing encrypted look', { capacity: 1, billable_submissions: 0 });
  const jobResponse = await authRequest(page, `/api/tryon/jobs/${marker.job_id}`); assert(jobResponse.ok(), 'Existing recovery job could not be read.');
  const job = await jobResponse.json();
  await page.evaluate(async ({ uid, encoded, pending }) => {
   const raw = Uint8Array.from(atob(encoded), char => char.charCodeAt(0)); const key = await crypto.subtle.importKey('raw', raw, 'AES-GCM', false, ['encrypt']);
   const iv = crypto.getRandomValues(new Uint8Array(12)); const ciphertext = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, key, new TextEncoder().encode(JSON.stringify(pending)));
   const db = await new Promise((resolve, reject) => { const request = indexedDB.open('stylereel-private-gallery', 2); request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error); });
   await new Promise((resolve, reject) => { const tx = db.transaction('pending', 'readwrite'); tx.objectStore('pending').put({ id: uid, iv, ciphertext }); tx.oncomplete = resolve; tx.onerror = () => reject(tx.error); }); db.close();
  }, { uid: generated.uid, encoded: generated.key, pending: { job: { ...job, status: 'processing' }, before: generated.item.before, provider: generated.item.provider, model: generated.item.model } });
  await page.reload({ waitUntil: 'domcontentloaded' }); await page.getByRole('heading', { name: /Looks like your/ }).waitFor({ timeout: 60000 });
  assert((await encryptedRecordIds(page, generated.uid)).join() === marker.job_id, 'Recovered result did not replace the oldest local record at capacity.');
  record('Encrypted pending-job recovery saves the existing live result and evicts the oldest record', { new_provider_calls: 0, recovered_job_id: marker.job_id });
  await nav(page, 'My gallery', /Your looks, your story/); await page.locator('.gallery-card').waitFor();
  await page.getByRole('button', { name: 'Delete look', exact: true }).click();
  const single = page.getByRole('dialog', { name: 'Delete this look?', exact: true }); await single.waitFor();
  await single.getByRole('button', { name: 'Delete', exact: true }).click(); await single.waitFor({ state: 'hidden' });
  assert((await encryptedRecordIds(page, generated.uid)).length === 0, 'Single deletion left a local encrypted record.');
  const denied = await authRequest(page, job.result_url); assert([404, 410].includes(denied.status()), 'Single UI deletion left the server result readable.');
  await layout(page, 'gallery-single-deleted'); record('Real single-result UI deletion removes local ciphertext and denies server retrieval', { result_status: denied.status() });
 } finally {
  if (settings) {
   const restored = await authRequest(page, '/api/admin/settings', 'PUT', { ai: settings.ai, rate_limits: settings.rate_limits, gallery: settings.gallery });
   assert(restored.ok(), 'Gallery capacity restoration failed.'); record('Administrator gallery capacity restored', { max_images: settings.gallery.max_images });
  }
  await adminContext.close();
 }
 const live = JSON.parse(await readFile(resolve(root, '.deployment/live-session.json'), 'utf8'));
 const userToken = live.accounts?.user?.customToken || live.accounts?.user?.custom_token;
 assert(userToken, 'The private standard-user session is missing.'); sensitive.push(userToken);
 const userContext = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
 const userPage = await userContext.newPage(); watch(userPage, 'gallery-management-user'); await installViolationRecorder(userPage); await blockPaidSubmissions(userPage, forbiddenSubmissions);
 try {
  await userPage.goto(baseUrl, { waitUntil: 'domcontentloaded' }); await userPage.getByRole('heading', { name: 'Let’s find your look.', exact: true }).waitFor(); await signIn(userPage, userToken);
  assert(await userPage.getByRole('button', { name: 'Administration', exact: true }).count() === 0, 'Standard user has an administration control.');
  const ids = ['6f54fb580aeb4988a5bcaa36b0db2b80', 'a5740bd677d04431b53c8d7c2c591d71'];
  const fixtures = [];
  for (const id of ids) { const fixture = await prepareFixture(userPage, id); fixtures.push(fixture); await seedEncryptedFixture(userPage, fixture); }
  await nav(userPage, 'My gallery', /Your looks, your story/); assert(await userPage.locator('.gallery-card').count() === 2, 'The two real user looks did not restore.'); await layout(userPage, 'gallery-standard-user');
  await userPage.getByRole('button', { name: 'Select all', exact: true }).click(); assert(await userPage.getByRole('button', { name: 'Download (2)', exact: true }).isVisible(), 'Bulk selection did not select both looks.');
  await userPage.getByRole('button', { name: 'Delete', exact: true }).click();
  const bulk = userPage.getByRole('dialog', { name: 'Delete 2 looks?', exact: true }); await bulk.waitFor(); await bulk.getByRole('button', { name: 'Delete', exact: true }).click(); await bulk.waitFor({ state: 'hidden' });
  assert((await encryptedRecordIds(userPage, fixtures[0].uid)).length === 0, 'Bulk deletion left encrypted records.');
  const statuses = [];
  for (const id of ids) { const image = await authRequest(userPage, `/api/tryon/results/${id}`); statuses.push(image.status()); assert([404, 410].includes(image.status()), 'Bulk UI deletion left a result readable.'); }
  await userPage.getByRole('heading', { name: 'Your first look is waiting', exact: true }).waitFor(); await layout(userPage, 'gallery-bulk-deleted');
  record('Standard-user bulk UI deletion removes both encrypted records and denies both server results', { result_statuses: statuses });
  assert(forbiddenSubmissions.length === 0, 'A gallery-only check attempted a paid submission.'); record('Gallery acceptance made zero provider submissions', { billable_submissions: 0 });
 } finally { await userContext.close(); }
}
const passwordOnly = process.argv.includes('--password-only');
const galleryOnly = process.argv.includes('--gallery-only');
const scenarios = [
 ['desktop', { viewport: { width: 1440, height: 1000 } }],
 ['android', devices['Pixel 7']],
 ['iphone', devices['iPhone 13']],
 ['ipad', devices['iPad (gen 7)']],
];
const scenarioFilter = process.argv.find(argument => argument.startsWith('--scenario='))?.split('=')[1];
const selectedScenarios = scenarioFilter ? scenarios.filter(([name]) => name === scenarioFilter) : scenarios;
try {
 for (const [name, device] of passwordOnly || galleryOnly ? [] : selectedScenarios) {
  const { defaultBrowserType: _unused, ...contextOptions } = device;
  const context = await browser.newContext({ ...contextOptions, acceptDownloads: true });
  const page = await context.newPage();
  const errors = watch(page, name);
  await installViolationRecorder(page);
  await page.goto(baseUrl, { waitUntil: 'domcontentloaded' });
  await page.getByRole('heading', { name: 'Let’s find your look.', exact: true }).waitFor({ timeout: 60000 });
  await layout(page, `${name}-login`);
  await signIn(page);
  if (name === 'desktop') galleryFixture = await prepareFixture(page);
  await seedEncryptedFixture(page, galleryFixture);
  await page.locator('.garment-grid img').first().waitFor({ timeout: 30000 });
  await layout(page, `${name}-studio`);
  if (name === 'desktop') await verifyLocalPhotoAndSelection(page);
  await nav(page, 'My gallery', /Your looks, your story/);
  if (galleryFixture) {
   await page.locator('.gallery-card').first().waitFor();
   await page.waitForFunction(() => { const image = document.querySelector('.gallery-card img'); return image?.complete && image.naturalWidth > 0; });
   assert(await page.locator('.gallery-card img').first().evaluate(image => image.complete && image.naturalWidth > 0), 'Saved result did not render.');
   record(`${name} encrypted gallery restoration`, { live_job: true });
  }
  await layout(page, `${name}-gallery`);
  if (name === 'desktop' && galleryFixture) {
   const ownDownload = page.waitForEvent('download');
   await page.getByRole('button', { name: 'Download look', exact: true }).first().click();
   assert((await ownDownload).suggestedFilename().includes('stylereel'), 'Authenticated gallery download did not start.');
   record('Authenticated local gallery download');
   await page.getByRole('button', { name: 'Share look with QR', exact: true }).first().click();
   await page.getByRole('button', { name: 'Create 15-minute link', exact: true }).click();
   await page.locator('.qr-frame svg').waitFor();
   const url = await page.getByRole('textbox', { name: 'Temporary share link', exact: true }).inputValue();
   sensitive.push(url, new URL(url).hash.slice(1));
   const anonymous = await browser.newContext({ viewport: { width: 390, height: 844 } });
   const anonymousPage = await anonymous.newPage();
   await anonymousPage.goto(url, { waitUntil: 'domcontentloaded' });
   await anonymousPage.locator('.shared-image img').waitFor();
   await anonymousPage.waitForFunction(() => { const image = document.querySelector('.shared-image img'); return image?.complete && image.naturalWidth > 0; });
   assert(await anonymousPage.locator('.shared-image img').evaluate(image => image.complete && image.naturalWidth > 0), 'Anonymous share image did not render.');
   const download = anonymousPage.waitForEvent('download');
   await anonymousPage.getByRole('button', { name: 'Download this look', exact: true }).click();
   assert((await download).suggestedFilename().includes('stylereel'), 'Shared download did not start.');
   await anonymousPage.screenshot({ path: resolve(output, 'anonymous-share.png'), fullPage: true });
   await page.getByRole('button', { name: 'Revoke link now', exact: true }).click();
   await page.getByRole('button', { name: 'Create 15-minute link', exact: true }).waitFor();
   await anonymousPage.reload({ waitUntil: 'domcontentloaded' });
   await anonymousPage.getByRole('alert').filter({ hasText: /expired or been revoked/ }).waitFor();
   record('Live QR share, anonymous download, and owner revocation');
   await anonymous.close();
   await page.getByRole('button', { name: 'Close dialog', exact: true }).click();
   await page.getByRole('button', { name: /View / }).first().click();
   const comparator = page.getByRole('slider', { name: 'Compare original and styled images' });
   await comparator.focus();
   await comparator.press('End');
   await comparator.press('ArrowLeft');
   assert(await comparator.inputValue() === '99', 'Comparison slider did not move.');
   await page.getByRole('button', { name: 'Close dialog', exact: true }).click();
   record('Before/after gallery comparison');
  }
  const menu = page.getByRole('button', { name: 'Open navigation', exact: true });
  if (await menu.isVisible()) await menu.click();
  const admin = page.getByRole('button', { name: /^Administration/ });
  if (await admin.isVisible()) {
   await admin.click();
   await page.getByRole('heading', { name: /thoughtfully managed/ }).waitFor();
   await page.locator('.stat-card').first().waitFor({ timeout: 30000 });
   await layout(page, `${name}-admin`);
   await page.getByRole('tab', { name: 'People', exact: true }).click();
   await page.getByRole('button', { name: 'Add person', exact: true }).click();
   const email = page.getByRole('textbox', { name: 'Email', exact: true });
   await email.pressSequentially('focus-check@example.com');
   assert(await email.inputValue() === 'focus-check@example.com', 'Dialog form lost focus while typing.');
   await page.getByRole('button', { name: 'Close dialog', exact: true }).click();
   record(`${name} admin modal keyboard entry`, { mutation: false });
   await page.getByRole('tab', { name: 'Settings', exact: true }).click();
   await page.getByRole('button', { name: 'Save studio settings', exact: true }).waitFor();
   assert(await page.getByText('Keys are write-only and stored in Secret Manager. Google uses the service account.').isVisible(), 'Provider credential disclosure missing.');
  } else {
   report.limitations.push(`${name}: administrator screens were not checked because this fixture account is a user.`);
   if (await page.getByRole('button', { name: 'Close navigation', exact: true }).isVisible()) await page.getByRole('button', { name: 'Close navigation', exact: true }).click();
  }
  const signout = page.getByRole('button', { name: 'Sign out', exact: true });
  if (await page.getByRole('button', { name: 'Open navigation', exact: true }).isVisible()) await page.getByRole('button', { name: 'Open navigation', exact: true }).click();
  page.__styleReelLogoutAt = new Date().toISOString();
  await signout.filter({ visible: true }).first().click();
  await page.getByRole('heading', { name: 'Let’s find your look.', exact: true }).waitFor();
  assert(await page.locator('.gallery-card img').count() === 0, 'Private gallery images remain visible after logout.');
  record(`${name} logout locks gallery`);
  report.scenarios.push({ name, passed: true, viewport: contextOptions.viewport, engine: 'Chrome emulation', failed_http: page.__styleReelHttp, logout_at: page.__styleReelLogoutAt });
  await context.close();
 }
 if (passwordOnly || session.verify_password_login || process.argv.includes('--with-password')) await verifyPasswordSignIn();
 if (galleryOnly) await verifyGalleryManagement();
 if (!galleryFixture && !passwordOnly && !galleryOnly) report.limitations.push('Gallery result, comparison, and share checks skipped because no succeeded live job ID was supplied.');
 report.limitations.push('Physical-device camera and HEIC capture are not verified by Chrome viewport emulation.');
 if (!galleryOnly) report.limitations.push('The supplied real result is preserved; destructive result deletion is checked separately by backend tests.');
 report.passed = (passwordOnly || galleryOnly || report.scenarios.length === selectedScenarios.length) && report.errors.length === 0;
} catch (error) {
 report.errors.push({ type: 'verification', message: redact(error.message) });
 report.passed = false;
} finally {
 report.errors.push(...observedErrors.flat());
 if (report.errors.length) report.passed = false;
 await browser.close();
 // Report deliberately omits account tokens, gallery keys, image bytes and share links.
 const reportPath = resolve(output, passwordOnly ? 'password-report.json' : galleryOnly ? 'gallery-report.json' : 'report.json');
 await writeFile(reportPath, JSON.stringify(report, null, 2) + '\n');
 console.log(JSON.stringify({ passed: report.passed, scenarios: report.scenarios.length, checks: report.checks.length, errors: report.errors.length, report: reportPath }));
}
if (!report.passed) process.exitCode = 1;
