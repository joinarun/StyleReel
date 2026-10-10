#!/usr/bin/env node
/** Deployed UX revision checks: normal sign-in, one paid saree job, encrypted recent looks. */
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const requireFrontend = createRequire(resolve(root, 'frontend/package.json'));
const { chromium, devices } = requireFrontend('playwright');
const session = JSON.parse(await readFile(resolve(root, '.deployment/browser-session.json'), 'utf8'));
const output = resolve(root, 'verification/browser/revision');
await mkdir(output, { recursive: true });
const olderAfter = 'data:image/jpeg;base64,' + (await readFile(resolve(root, 'verification/results/pro-saree.jpg'))).toString('base64');
const report = { service_url: session.url, checked_at: new Date().toISOString(), browser: 'Installed Google Chrome', physical_device_testing: false, checks: [], errors: [], external_events: [], fixture_note: 'Synthetic fictional adult and licensed saree. Recent-strip overflow uses encrypted copies of real synthetic Google benchmark results; these copies are not additional AI generations.' };
const record = (name, passed = true, details = {}) => { report.checks.push({ name, passed, ...details }); if (!passed) throw new Error(name); };
const browser = await chromium.launch({ executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', headless: true, args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'] });
const headers = { Authorization: `Bearer ${session.token}` };
const watch = page => {
 page.on('pageerror', error => report.errors.push({ type: 'pageerror', message: error.message.replace(/eyJ[\w-]+\.[\w-]+\.[\w-]+/g, '[redacted]') }));
 page.on('console', message => {
  if (message.type() !== 'error') return;
  const text = message.text();
  const url = message.location().url;
  if (url.startsWith('https://www.google.com/recaptcha/enterprise/anchor') && text === 'requestStorageAccess: Permission denied.') report.external_events.push({ type: 'google_recaptcha_frame_storage_access_denied', location: new URL(url).origin + new URL(url).pathname, message: text, observation: 'The console message originates from Google’s CAPTCHA iframe. Ordinary email/password sign-in and application checks still succeed; the denial is retained rather than hidden.' });
  else if (/\/recaptcha\/(enterprise|api2)\/pat/.test(url) || text.includes('report-only Content Security Policy') || url.startsWith('https://csp.withgoogle.com/')) report.external_events.push({ origin: new URL(url || 'https://www.google.com').origin, message: text.slice(0, 350) });
  else report.errors.push({ type: 'console', location: url ? new URL(url).origin + new URL(url).pathname : '', message: text.slice(0, 350) });
 });
};
async function signIn(page) {
 await page.goto(session.url, { waitUntil: 'domcontentloaded' });
 await page.getByRole('textbox', { name: 'Email address', exact: true }).fill(session.email);
 await page.getByLabel('Password', { exact: true }).fill(session.password);
 await page.getByRole('button', { name: 'Enter the studio', exact: true }).click();
 await page.getByRole('heading', { name: /A new look/ }).waitFor({ timeout: 90000 });
}
async function nav(page, name) {
 const menu = page.getByRole('button', { name: 'Open navigation', exact: true });
 if (await menu.isVisible()) await menu.click();
 await page.getByRole('button', { name, exact: true }).click();
}
async function home(page) {
 await page.locator('.app-header .brand-link').click();
 await page.getByRole('button', { name: 'Take a photo', exact: true }).waitFor();
 record('StyleReel logo returns to a fresh studio', !(await page.locator('.generated-image:visible').count()) && (await page.locator('.selection-count:visible').innerText()) === '0/2');
}
async function layout(page, name) {
 const size = await page.evaluate(() => ({ viewport: innerWidth, width: document.documentElement.scrollWidth }));
 record(`${name} layout has no horizontal page overflow`, size.width <= size.viewport + 1, size);
 await page.screenshot({ path: resolve(output, `${name}.png`), fullPage: true });
}
async function fixture(page, job) {
 return page.evaluate(async ({ headers, job }) => {
  const get = async path => { const response = await fetch(path, { headers }); if (!response.ok) throw new Error(`Fixture read: HTTP ${response.status}`); return response; };
  const [me, secret] = await Promise.all([get('/api/me').then(r => r.json()), get('/api/me/gallery-key').then(r => r.json())]);
  const blob = await get(job.result_url).then(r => r.blob());
  const after = await new Promise(resolve => { const reader = new FileReader(); reader.onload = () => resolve(reader.result); reader.readAsDataURL(blob); });
  return { uid: me.id, key: secret.key, item: { id: job.id, created_at: job.created_at, garment_names: job.garment_names, workflow: 'catalog', experimental: true, before: '', after, provider: 'Google', model: 'gemini-3-pro-image', estimated_cost_usd: job.estimated_cost_usd } };
 }, { headers, job });
}
async function seed(page, fixture, count = 9) {
 await page.evaluate(async ({ fixture, count, olderAfter }) => {
  const key = await crypto.subtle.importKey('raw', Uint8Array.from(atob(fixture.key), c => c.charCodeAt(0)), 'AES-GCM', false, ['encrypt']);
  const db = await new Promise((resolve, reject) => { const request = indexedDB.open('stylereel-private-gallery', 2); request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error); });
  for (let index = 0; index < count; index++) {
   const item = index ? { ...fixture.item, id: `${fixture.item.id}-local-fixture-${index}`, created_at: new Date(Date.parse(fixture.item.created_at) - index * 3600000).toISOString(), garment_names: [`Earlier saree look ${index}`], after: index % 2 ? olderAfter : fixture.item.after } : fixture.item;
   const iv = crypto.getRandomValues(new Uint8Array(12));
   const ciphertext = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, key, new TextEncoder().encode(JSON.stringify(item)));
   await new Promise((resolve, reject) => { const transaction = db.transaction('images', 'readwrite'); transaction.objectStore('images').put({ id: `${fixture.uid}:${item.id}`, uid: fixture.uid, iv, ciphertext }); transaction.oncomplete = resolve; transaction.onerror = () => reject(transaction.error); });
  }
  db.close();
 }, { fixture, count, olderAfter });
 await page.reload({ waitUntil: 'domcontentloaded' });
 await page.getByRole('heading', { name: /A new look/ }).waitFor({ timeout: 60000 });
}
async function rememberExisting(page, job) {
 const data = await fixture(page, job);
 await page.evaluate(async ({ data, job }) => {
  const key = await crypto.subtle.importKey('raw', Uint8Array.from(atob(data.key), c => c.charCodeAt(0)), 'AES-GCM', false, ['encrypt']);
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const ciphertext = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, key, new TextEncoder().encode(JSON.stringify({ job, before: '', provider: 'Google', model: 'gemini-3-pro-image' })));
  const db = await new Promise((resolve, reject) => { const r = indexedDB.open('stylereel-private-gallery', 2); r.onsuccess = () => resolve(r.result); r.onerror = () => reject(r.error); });
  await new Promise((resolve, reject) => { const tx = db.transaction('pending', 'readwrite'); tx.objectStore('pending').put({ id: data.uid, iv, ciphertext }); tx.oncomplete = resolve; tx.onerror = () => reject(tx.error); });
  db.close();
 }, { data, job });
}
async function recoverExisting(page, job) {
 await rememberExisting(page, job);
 await page.reload({ waitUntil: 'domcontentloaded' });
 await page.getByRole('heading', { name: /Looks like your/ }).waitFor({ timeout: 60000 });
 record('Existing real saree job recovers from encrypted pending state without another paid submission');
}
async function verifyDelayedRecoveryHome(page, job) {
 await home(page);
 await rememberExisting(page, job);
 let release; let seen;
 const released = new Promise(resolve => { release = resolve; });
 const intercepted = new Promise(resolve => { seen = resolve; });
 const pattern = `${session.url}/api/tryon/jobs/${job.id}`;
 const handler = async route => { seen(); await released; await route.continue(); };
 await page.route(pattern, handler);
 await page.reload({ waitUntil: 'domcontentloaded' });
 await intercepted;
 record('Pending recovery blocks a new camera/Generate flow until its job is checked', await page.getByRole('button', { name: 'Take a photo', exact: true }).isDisabled() && await page.locator('.generate-button:visible').isDisabled());
 await page.locator('.app-header .brand-link').click();
 const retrieved = page.waitForResponse(r => new URL(r.url()).pathname === job.result_url && r.request().method() === 'GET');
 release(); await retrieved;
 await page.waitForFunction(() => document.querySelector('.generate-button')?.textContent.includes('Generate my look'));
 await page.waitForTimeout(300);
 record('Home during delayed pending recovery stays fresh after the old result is saved', await page.locator('.generated-image:visible').count() === 0 && await page.locator('.selection-count:visible').innerText() === '0/2');
 await page.unroute(pattern, handler);
}
async function verifyLateShare(page, context, inGallery = false) {
 let release; let seen; let shareId;
 const released = new Promise(resolve => { release = resolve; });
 const intercepted = new Promise(resolve => { seen = resolve; });
 const pattern = `${session.url}/api/shares`;
 const handler = async route => {
  if (route.request().method() !== 'POST') return route.continue();
  const response = await route.fetch();
  const share = await response.json(); shareId = share.id;
  seen(); await released; await route.fulfill({ response });
 };
 await page.route(pattern, handler);
 await page.getByRole('button', { name: inGallery ? 'Share look with QR' : 'Share with QR', exact: true }).click();
 await page.getByRole('button', { name: 'Create 15-minute link', exact: true }).click();
 await intercepted;
 await page.getByRole('button', { name: 'Close dialog', exact: true }).click();
 if (!inGallery) await home(page);
 const delivered = page.waitForResponse(r => r.url() === pattern && r.request().method() === 'POST');
 release(); await delivered; await page.waitForTimeout(500);
 record(inGallery ? 'Closing a pending QR dialog in Gallery prevents a late response from reopening it' : 'Home after closing a pending QR dialog cannot restore the previous result', await page.getByRole('dialog').count() === 0 && (inGallery || await page.locator('.generated-image:visible').count() === 0));
 await page.unroute(pattern, handler);
 if (shareId) { const revoked = await context.request.delete(session.url + '/api/shares/' + shareId, { headers }); if (!revoked.ok()) throw new Error('Late test share cleanup failed.'); }
}
async function verifyRecent(page, name) {
 await nav(page, 'My gallery');
 await page.getByRole('heading', { name: 'Your looks, your story.', exact: true }).waitFor();
 record(`${name} gallery shows a single generated photo`, await page.locator('.generated-image:visible img').count() === 1 && await page.getByRole('slider', { name: /Compare/ }).count() === 0 && await page.getByRole('img', { name: 'Original photo', exact: true }).count() === 0);
 const recent = page.locator('.recent-strip:visible');
 await page.getByRole('button', { name: 'Scroll to next looks', exact: true }).click();
 await page.waitForFunction(() => document.querySelector('.gallery-result .recent-strip')?.scrollLeft > 0);
 record(`${name} earlier results scroll within their bottom strip`, await recent.evaluate(e => e.scrollWidth > e.clientWidth));
 const originalImage = await page.locator('.generated-image:visible img').getAttribute('src');
 const older = page.locator('.recent-image:visible').nth(1);
 await older.scrollIntoViewIfNeeded(); await older.click();
 await page.getByRole('heading', { name: 'Earlier saree look 1', exact: true }).waitFor();
 const selectedImage = await page.locator('.generated-image:visible img').getAttribute('src');
 record(`${name} clicking a previous look selects its image and metadata`, await older.getAttribute('aria-pressed') === 'true' && selectedImage !== originalImage && selectedImage === await older.locator('img').getAttribute('src') && (await page.locator('.generated-image:visible').boundingBox()).y < (await recent.boundingBox()).y);
 const download = page.waitForEvent('download');
 await page.getByRole('button', { name: 'Download look', exact: true }).click();
 record(`${name} download follows selected older look`, (await download).suggestedFilename().endsWith('-local-fixture-1.jpg'));
 await layout(page, name);
 await home(page);
}
try {
 const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, permissions: ['camera'] });
 await context.addInitScript(() => {
  window.__revisionStreams = [];
  const media = navigator.mediaDevices;
  if (media?.getUserMedia) { const original = media.getUserMedia.bind(media); media.getUserMedia = async constraints => { const stream = await original(constraints); window.__revisionStreams.push(stream); return stream; }; }
 });
 const page = await context.newPage(); watch(page);
 await signIn(page);
 record('Normal CAPTCHA-protected email/password login succeeds');
 const uploads = []; page.on('request', request => { if (request.method() === 'POST' && new URL(request.url()).pathname === '/api/uploads') uploads.push(request); });
 record('Consent checkbox is removed from the studio', await page.getByRole('checkbox').count() === 0);
 const disclosure = await page.locator('.processing-disclosure').evaluate(e => ({ text: e.textContent, font: parseFloat(getComputedStyle(e).fontSize), top: e.getBoundingClientRect().top, barBottom: document.querySelector('.generation-bar').getBoundingClientRect().bottom }));
 record('Small bottom disclosure identifies Google and overseas processing', disclosure.top >= disclosure.barBottom && disclosure.font >= 10 && disclosure.font <= 13 && disclosure.text.includes('Google') && disclosure.text.includes('outside India'));
 await page.getByRole('button', { name: 'Take a photo', exact: true }).click();
 await page.getByRole('dialog', { name: 'Take a photo', exact: true }).waitFor();
 await page.getByRole('button', { name: 'Capture photo', exact: true }).waitFor({ state: 'visible' });
 await page.waitForFunction(() => document.querySelector('.desktop-camera-preview video')?.videoWidth > 0 && !Array.from(document.querySelectorAll('button')).find(e => e.textContent.includes('Capture photo'))?.disabled);
 await page.getByRole('button', { name: 'Capture photo', exact: true }).click();
 await page.getByRole('img', { name: 'Your selected photo', exact: true }).waitFor();
 record('Deployed desktop webcam capture produces a local photo and stops the camera', await page.evaluate(() => window.__revisionStreams.length > 0 && window.__revisionStreams.every(s => s.getTracks().every(t => t.readyState === 'ended'))) && uploads.length === 0);
 await page.locator('input[type="file"]').first().setInputFiles(resolve(root, 'verification/fixtures/saree-person-dress.jpg'));
 const select = page.locator('.garment-select').filter({ has: page.locator('.garment-category', { hasText: /^Sarees$/i }) });
 await select.click();
 await page.getByRole('button', { name: 'Generate my look', exact: true }).waitFor();
 record('Photo and saree enable generation without a consent checkbox or early upload', await page.getByRole('button', { name: 'Generate my look', exact: true }).isEnabled() && uploads.length === 0);
 await layout(page, 'desktop-home');
 const markerPath = resolve(root, '.deployment/revision-browser-generation.json');
 let job; let replay = false;
 try { job = JSON.parse(await readFile(markerPath, 'utf8')); if (!job.id) throw new Error('A prior paid submission may exist without a known ID; it will not be repeated.'); replay = true; }
 catch (error) {
  if (error.code !== 'ENOENT') throw error;
  await writeFile(markerPath, JSON.stringify({ requested_at: new Date().toISOString(), status: 'requested' }), { mode: 0o600, flag: 'wx' });
  const accepted = page.waitForResponse(r => new URL(r.url()).pathname === '/api/tryon/catalog' && r.request().method() === 'POST');
  await page.getByRole('button', { name: 'Generate my look', exact: true }).click();
  const response = await accepted;
  if (response.status() !== 202) throw new Error(`Saree browser submission HTTP ${response.status()}; do not automatically resubmit.`);
  job = await response.json();
  await writeFile(markerPath, JSON.stringify(job, null, 2), { mode: 0o600 });
  console.log('Browser accepted one real Google Pro saree job; waiting for the result.');
  // The same Studio component must preserve its job while another page is visible.
  await nav(page, 'Administration');
  await page.getByRole('heading', { name: 'The studio, thoughtfully managed.', exact: true }).waitFor();
  await nav(page, 'Try-on studio');
  await page.getByRole('heading', { name: /Looks like your/ }).waitFor({ timeout: 360000 });
  record('In-flight generation survives administration navigation without a second submission', uploads.length === 1);
 }
 const response = await context.request.get(session.url + `/api/tryon/jobs/${job.id}`, { headers });
 if (!response.ok()) throw new Error(`Completed saree job HTTP ${response.status()}`);
 job = await response.json();
 record('Real Google Pro saree job succeeds and remains experimental', job.status === 'succeeded' && job.experimental === true);
 if (replay) await recoverExisting(page, job);
 await writeFile(markerPath, JSON.stringify(job, null, 2), { mode: 0o600 });
 const image = await context.request.get(session.url + job.result_url, { headers });
 await writeFile(resolve(root, 'verification/results/saree-revision-dress.jpg'), await image.body());
 report.generation = { job_id: job.id, workflow: job.workflow, fixture: 'Previously Google-generated synthetic full dress', model: 'gemini-3-pro-image', status: job.status, experimental: job.experimental, estimated_reserved_usd: job.estimated_cost_usd, output_file: 'verification/results/saree-revision-dress.jpg' };
 const saved = await page.evaluate(async id => { const db = await new Promise((resolve, reject) => { const r = indexedDB.open('stylereel-private-gallery', 2); r.onsuccess = () => resolve(r.result); r.onerror = () => reject(r.error); }); const records = await new Promise(resolve => { const r = db.transaction('images').objectStore('images').getAll(); r.onsuccess = () => resolve(r.result); }); db.close(); return records.some(r => r.id.endsWith(':' + id) && r.ciphertext && !r.after); }, job.id);
 record('Browser generated result is encrypted in the local gallery', saved);
 record('Studio result shows only the new image with recent looks below it', await page.locator('.generated-image:visible img').count() === 1 && await page.getByRole('slider', { name: /Compare/ }).count() === 0 && await page.locator('.recent-strip:visible').count() === 1);
 await page.getByRole('button', { name: 'Share with QR', exact: true }).click();
 await page.getByRole('button', { name: 'Create 15-minute link', exact: true }).click();
 const link = await page.getByRole('textbox', { name: 'Temporary share link', exact: true }).inputValue();
 const sharedPage = await context.newPage(); watch(sharedPage); await sharedPage.goto(link);
 await sharedPage.getByRole('img', { name: 'Privately shared AI garment preview', exact: true }).waitFor();
 await sharedPage.locator('header .brand-link').click();
 await sharedPage.getByRole('heading', { name: /A new look/ }).waitFor({ timeout: 60000 });
 record('Shared-image StyleReel logo navigates home');
 await sharedPage.close();
 const revocation = page.waitForResponse(r => r.request().method() === 'DELETE' && new URL(r.url()).pathname.startsWith('/api/shares/'));
 await page.getByRole('button', { name: 'Revoke link now', exact: true }).click();
 if ((await revocation).status() !== 200) throw new Error('QR revocation was rejected.');
 await page.getByRole('button', { name: 'Create 15-minute link', exact: true }).waitFor();
 const revoked = await context.request.post(session.url + '/api/shares/download', { data: { token: new URL(link).hash.slice(1) } });
 record('QR link can still be revoked with the single-image result view', revoked.status() === 410);
 await page.getByRole('button', { name: 'Close dialog', exact: true }).click();
 await layout(page, 'desktop-generated-saree');
 await verifyLateShare(page, context);
 await nav(page, 'Administration'); await page.getByRole('heading', { name: 'The studio, thoughtfully managed.', exact: true }).waitFor(); await home(page);
 await verifyDelayedRecoveryHome(page, job);
 const galleryFixture = await fixture(page, job);
 await seed(page, galleryFixture); await verifyRecent(page, 'desktop-recent-looks');
 await nav(page, 'My gallery');
 await verifyLateShare(page, context, true);
 await home(page);
 for (const [name, device] of [['android', devices['Pixel 7']], ['iphone', devices['iPhone 13']], ['ipad', devices['iPad (gen 7)']]]) {
  const mobile = await browser.newContext(device);
  const mobilePage = await mobile.newPage(); watch(mobilePage);
  await signIn(mobilePage);
  record(`${name} retains native camera capture`, await mobilePage.locator('input[capture="user"]').count() === 1);
  await layout(mobilePage, `${name}-home`);
  await seed(mobilePage, galleryFixture); await verifyRecent(mobilePage, `${name}-recent-looks`);
  await mobile.close();
 }
 await recoverExisting(page, job);
 await nav(page, 'My gallery');
 const deletion = page.waitForResponse(r => r.request().method() === 'DELETE' && new URL(r.url()).pathname === `/api/tryon/results/${job.id}`);
 await page.getByRole('button', { name: 'Delete look', exact: true }).click();
 await page.getByRole('dialog').getByRole('button', { name: 'Delete', exact: true }).click();
 record('Gallery deletion removes the selected test result on the server', (await deletion).status() === 200);
 await page.getByRole('dialog').waitFor({ state: 'hidden' });
 await nav(page, 'Try-on studio');
 await page.getByRole('button', { name: 'Take a photo', exact: true }).waitFor();
 record('Returning to Studio cannot resurrect a result deleted in Gallery', await page.locator('.generated-image:visible').count() === 0);
 await context.close();
 record('No application page or console errors', report.errors.length === 0);
 report.completed_at = new Date().toISOString();
 console.log(`PASS: ${report.checks.length} deployed revision browser checks.`);
} catch (error) {
 report.failure = String(error.message).replace(/eyJ[\w-]+\.[\w-]+\.[\w-]+/g, '[redacted]');
 process.exitCode = 1;
 console.error(report.failure);
} finally {
 await browser.close();
 await writeFile(resolve(output, 'report.json'), JSON.stringify(report, null, 2));
}
