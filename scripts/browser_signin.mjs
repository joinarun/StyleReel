#!/usr/bin/env node
/** Normal disposable-account email/password sign-in; CAPTCHA remains enforced. */
import { chmod, mkdir, readFile, writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
const root=resolve(dirname(fileURLToPath(import.meta.url)),'..');
const requireFrontend=createRequire(resolve(root,'frontend/package.json'));
const {chromium}=requireFrontend('playwright');
const version=requireFrontend('firebase/package.json').version;
const path=resolve(root,'.deployment/live-session.json');
const session=JSON.parse(await readFile(path,'utf8'));
const adminOnly=process.argv.includes('--admin-only');const refreshAdminBrowser=process.argv.includes('--refresh-admin-browser');const headed=process.argv.includes('--headed');
const reportPath=resolve(root,adminOnly?'verification/catalog-upgrade-auth-admin.json':'verification/catalog-upgrade-auth.json');
const output=resolve(root,'verification/browser/catalog-upgrade');
await mkdir(output,{recursive:true});
const report={checked_at:new Date().toISOString(),service_url:session.url,authentication:'Normal UI email/password with enforced CAPTCHA; at most three attempts, only visible CAPTCHA errors retried',roles:[],passed:false};
const secrets=Object.values(session.accounts).flatMap(account=>[account.email,account.password,account.token]).filter(Boolean);
const redact=value=>secrets.reduce((text,secret)=>text.replaceAll(secret,'[redacted]'),String(value)).replace(/eyJ[\w-]+\.[\w-]+\.[\w-]+/g,'[redacted token]');
const savePrivate=async(file,data)=>{await writeFile(file,JSON.stringify(data,null,2)+'\n',{mode:0o600});await chmod(file,0o600)};
function recentAdminToken(account){
 try{const claims=JSON.parse(Buffer.from(account.token.split('.')[1],'base64url').toString('utf8'));const now=Date.now()/1000;const issued=account.browser_signed_in_at?Date.parse(account.browser_signed_in_at)/1000:claims.iat;return claims.exp>now+600&&issued>now-900}catch{return false}
}
async function authenticate(page,account){
 const initialized=page.waitForResponse(response=>new URL(response.url()).pathname==='/v2/recaptchaConfig'&&response.status()===200,{timeout:60000});
 await page.goto(session.url,{waitUntil:'domcontentloaded'});await initialized;
 await page.getByRole('textbox',{name:'Email address',exact:true}).fill(account.email);
 await page.getByLabel('Password',{exact:true}).fill(account.password);
 await page.getByRole('button',{name:'Enter the studio',exact:true}).click();
 const outcome=await Promise.any([
  page.getByRole('heading',{name:/A new look/}).waitFor({timeout:90000}).then(()=>({ok:true})),
  page.locator('.notice-error:visible').first().waitFor({timeout:90000}).then(async()=>({ok:false,notice:await page.locator('.notice-error:visible').first().innerText()})),
 ]);
 if(!outcome.ok)return outcome;
 const token=await page.evaluate(async version=>{
  const config=await fetch('/api/config').then(response=>response.json());
  const {getApps,initializeApp}=await import(`https://www.gstatic.com/firebasejs/${version}/firebase-app.js`);
  const {getAuth}=await import(`https://www.gstatic.com/firebasejs/${version}/firebase-auth.js`);
  const auth=getAuth(getApps()[0]||initializeApp(config.firebase));await auth.authStateReady();
  if(!auth.currentUser)throw new Error('Normal sign-in persistence was not restored.');return auth.currentUser.getIdToken();
 },version);
 return {ok:true,token};
}
const browser=await chromium.launch({executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless:!headed});
try{
 for(const [role,account] of Object.entries(session.accounts).filter(([role])=>!adminOnly||role==='admin')){
  if(!account.password)throw new Error('Ordinary sign-in requires a disposable account password.');
  if(role==='admin'&&!refreshAdminBrowser&&recentAdminToken(account)){
   report.roles.push({role,passed:true,reused_recent_normal_login:true,issued_at:account.browser_signed_in_at??'JWT issue time within 15 minutes'});console.log('PASS: recent administrator token from ordinary sign-in reused without another CAPTCHA attempt.');continue;
  }
  const result={role,attempts:[],passed:false};report.roles.push(result);
  for(let attempt=1;attempt<=3;attempt++){
   const context=await browser.newContext();const page=await context.newPage();
   try{
    const outcome=await authenticate(page,account);
    if(outcome.ok){
     account.token=outcome.token;account.browser_signed_in_at=new Date().toISOString();await savePrivate(path,session);
     if(role==='admin')await savePrivate(resolve(root,'.deployment/catalog-auth-storage.json'),{email:account.email,saved_at:account.browser_signed_in_at,storage:await context.storageState({indexedDB:true})});
     result.attempts.push({attempt,passed:true,recaptcha_config_http:200,headed});result.passed=true;console.log(`PASS: disposable ${role} account signed in through normal email/password and enforced CAPTCHA.`);break;
    }
    const notice=redact(outcome.notice);const captcha=/security check could not be completed|captcha|recaptcha/i.test(outcome.notice);
    const screenshot=resolve(output,`signin-${role}-attempt-${attempt}.png`);await page.screenshot({path:screenshot,fullPage:true});
    result.attempts.push({attempt,passed:false,captcha_error:captcha,notice,screenshot,recaptcha_config_http:200,headed});console.log(JSON.stringify({role,attempt,notice,screenshot}));
    if(!captcha||attempt===3)throw new Error(`${role}: ordinary UI sign-in rejected${captcha?' after three CAPTCHA attempts':''}.`);
   }finally{await context.close()}
  }
 }
 const config=JSON.parse(await readFile(resolve(root,'.deployment/config.json'),'utf8'));
 await savePrivate(resolve(root,'.deployment/browser-session.json'),{url:session.url,...session.accounts.admin,firebase:config.firebase,authentication:session.authentication});report.passed=report.roles.every(role=>role.passed);
}catch(error){report.error=redact(error.message);console.error(JSON.stringify({passed:false,error:report.error}));process.exitCode=1}
finally{await browser.close();report.completed_at=new Date().toISOString();await writeFile(reportPath,JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify({passed:report.passed,roles:report.roles.length,report:reportPath}))}
