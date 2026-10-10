#!/usr/bin/env node
/** Normal email/password sign-in to disposable fixtures, with enforced CAPTCHA. */
import { readFile, writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const requireFrontend = createRequire(resolve(root, 'frontend/package.json'));
const { chromium } = requireFrontend('playwright');
const version = requireFrontend('firebase/package.json').version;
const path = resolve(root, '.deployment/live-session.json');
const session = JSON.parse(await readFile(path, 'utf8'));
const browser = await chromium.launch({ executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', headless: true });
try {
 for (const [role, account] of Object.entries(session.accounts)) {
  if (!account.password) throw new Error('Ordinary sign-in requires a disposable account password.');
  const context = await browser.newContext();
  const page = await context.newPage();
  await page.goto(session.url, { waitUntil: 'domcontentloaded' });
  await page.getByRole('textbox', { name: 'Email address', exact: true }).fill(account.email);
  await page.getByLabel('Password', { exact: true }).fill(account.password);
  await page.getByRole('button', { name: 'Enter the studio', exact: true }).click();
  await page.getByRole('heading', { name: /A new look/ }).waitFor({ timeout: 90000 });
  account.token = await page.evaluate(async version => {
   const config = await fetch('/api/config').then(r => r.json());
   const { getApps, initializeApp } = await import(`https://www.gstatic.com/firebasejs/${version}/firebase-app.js`);
   const { getAuth } = await import(`https://www.gstatic.com/firebasejs/${version}/firebase-auth.js`);
   const auth = getAuth(getApps()[0] || initializeApp(config.firebase));
   await auth.authStateReady();
   if (!auth.currentUser) throw new Error('Normal sign-in persistence was not restored.');
   return auth.currentUser.getIdToken();
  }, version);
  await writeFile(path, JSON.stringify(session, null, 2), { mode: 0o600 });
  await context.close();
  console.log(`PASS: disposable ${role} account signed in through normal email/password and CAPTCHA.`);
 }
 const config = JSON.parse(await readFile(resolve(root, '.deployment/config.json'), 'utf8'));
 await writeFile(resolve(root, '.deployment/browser-session.json'), JSON.stringify({ url: session.url, ...session.accounts.admin, firebase: config.firebase, authentication: session.authentication }, null, 2), { mode: 0o600 });
} finally {
 await browser.close();
}
