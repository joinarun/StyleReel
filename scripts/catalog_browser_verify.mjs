#!/usr/bin/env node
/** Deployed collection upgrade QA: normal CAPTCHA login and no AI submissions. */
import { chmod, mkdir, readFile, writeFile } from 'node:fs/promises';
import { randomUUID } from 'node:crypto';
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root=resolve(dirname(fileURLToPath(import.meta.url)),'..');
const requireFrontend=createRequire(resolve(root,'frontend/package.json'));
const {chromium,devices}=requireFrontend('playwright');
const session=JSON.parse(await readFile(resolve(root,'.deployment/live-session.json'),'utf8'));
const account=session.accounts?.admin;
const restoreVerifiedSession=process.argv.includes('--restore-verified-session');
if(!account?.email||!account.password)throw new Error('A disposable administrator email/password fixture is required.');
let authStorage;
try{const saved=JSON.parse(await readFile(resolve(root,'.deployment/catalog-auth-storage.json'),'utf8'));if(saved.email===account.email&&Date.parse(saved.saved_at)>Date.now()-15*60000)authStorage=saved.storage}catch(error){if(error.code!=='ENOENT')throw error}
const output=resolve(root,'verification/browser/catalog-upgrade');
const reportPath=resolve(root,'verification/catalog-upgrade-browser.json');
const statePath=resolve(root,'.deployment/catalog-browser-state.json');
await mkdir(output,{recursive:true});
let state;
try{state=JSON.parse(await readFile(statePath,'utf8'))}catch(error){if(error.code!=='ENOENT')throw error;state={run_id:randomUUID().replaceAll('-','').slice(0,10),created_at:new Date().toISOString()}}
const saveState=async()=>{await writeFile(statePath,JSON.stringify(state,null,2)+'\n',{mode:0o600});await chmod(statePath,0o600)};
await saveState();
const names={category:`Browser dresses ${state.run_id}`,store:`Browser Store ${state.run_id}`,brand:`Browser Brand ${state.run_id}`,garment:`Browser multi-photo dress ${state.run_id}`};
const report={service_url:session.url,checked_at:new Date().toISOString(),browser:'Installed Google Chrome',authentication:restoreVerifiedSession?'Existing administrator ID token obtained through an earlier successful ordinary CAPTCHA login, server-validated and restored into Firebase IndexedDB persistence for UI checks':'Ordinary Firebase email/password through the deployed login and enforced CAPTCHA, with normal IndexedDB persistence reused for device layouts',limitations:restoreVerifiedSession?['Three fresh headless and three fresh headed admin password attempts were rejected by enforced CAPTCHA despite successful reCAPTCHA configuration initialization. These UI checks restore an existing verified ordinary-login ID token and do not claim a new password/CAPTCHA success.']:[],physical_device_testing:false,checks:[],scenarios:[],errors:[],external_events:[],paid_submissions:0,fixture_note:'UI upload/viewer fixture: the same licensed CC0 cream dress reference is uploaded under two file names. Distinct stored URLs exercise multiple reference controls; garment-quality evaluation uses separate synthetic/mannequin references in the API report.',resource_ids:{}};
const sensitive=[account.email,account.password,...Object.values(session.accounts??{}).flatMap(value=>[value.password,value.token,value.customToken,value.custom_token]).filter(Boolean)];
const redact=value=>sensitive.reduce((text,secret)=>text.replaceAll(secret,'[redacted]'),String(value)).replace(/eyJ[\w-]+\.[\w-]+\.[\w-]+/g,'[redacted token]');
const record=(name,passed=true,details={})=>{report.checks.push({name,passed,...details});if(!passed)throw new Error(name)};
const browser=await chromium.launch({executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless:true});
let activePage;
let activeScenario='desktop';

async function prepare(context){
 const page=await context.newPage();activePage=page;
 await page.route('**/api/tryon/**',route=>{
  const request=route.request();const pathname=new URL(request.url()).pathname;
  if(request.method()==='POST'&&['/api/tryon/catalog','/api/tryon/holding-garment'].includes(pathname)){report.paid_submissions++;return route.abort('blockedbyclient')}
  return route.continue();
 });
 page.on('pageerror',error=>report.errors.push({type:'pageerror',scenario:activeScenario,message:redact(error.message)}));
 page.on('console',message=>{
  if(message.type()!=='error')return;const origin=message.location().url;const text=redact(message.text()).slice(0,400);
  if(origin.startsWith('https://identitytoolkit.googleapis.com/')&&text.includes('400'))report.external_events.push({scenario:activeScenario,type:'Firebase sign-in rejection response',message:text});
  else if(origin.includes('/recaptcha/')||origin.startsWith('https://csp.withgoogle.com/')||text.includes('report-only Content Security Policy'))report.external_events.push({scenario:activeScenario,type:'Google CAPTCHA/browser event',message:text});
  else report.errors.push({type:'console',scenario:activeScenario,message:text});
 });
 for(let attempt=1;attempt<=3;attempt++){
  await page.goto(session.url,{waitUntil:'domcontentloaded'});
  if(authStorage){await page.getByRole('heading',{name:/A new look/}).waitFor({timeout:60000});record(`${activeScenario}: studio restores the authenticated Firebase session from device persistence`);return page}
  if(restoreVerifiedSession){
   await page.getByRole('heading',{name:'Let’s find your look.',exact:true}).waitFor({timeout:60000});
   await page.evaluate(async({token,uid,email})=>{
    const config=await fetch('/api/config').then(response=>response.json());const verified=await fetch('/api/me',{headers:{Authorization:`Bearer ${token}`}});
    if(!verified.ok)throw new Error(`Existing authenticated fixture was rejected by the backend: HTTP ${verified.status}.`);
    const account=await verified.json();if(account.id!==uid||account.email!==email||account.role!=='admin'||!account.active||account.must_change_password)throw new Error('Existing fixture is not a ready administrator.');
    const claims=JSON.parse(atob(token.split('.')[1].replaceAll('-','+').replaceAll('_','/')));if(claims.sub!==uid||claims.exp*1000<Date.now()+5*60000)throw new Error('Existing ordinary-login token does not cover the verification window.');
    const user={uid,email,emailVerified:!!claims.email_verified,isAnonymous:false,displayName:null,photoURL:null,providerData:[{providerId:'password',uid:email,displayName:null,email,phoneNumber:null,photoURL:null}],stsTokenManager:{refreshToken:null,accessToken:token,expirationTime:claims.exp*1000},createdAt:String(claims.auth_time*1000),lastLoginAt:String(claims.auth_time*1000),apiKey:config.firebase.apiKey,appName:'[DEFAULT]'};
    const db=await new Promise((resolve,reject)=>{const request=indexedDB.open('firebaseLocalStorageDb',1);request.onupgradeneeded=()=>{if(!request.result.objectStoreNames.contains('firebaseLocalStorage'))request.result.createObjectStore('firebaseLocalStorage',{keyPath:'fbase_key'})};request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(new Error('Firebase persistence could not be opened.'))});
    await new Promise((resolve,reject)=>{const transaction=db.transaction('firebaseLocalStorage','readwrite');transaction.objectStore('firebaseLocalStorage').put({fbase_key:`firebase:authUser:${config.firebase.apiKey}:[DEFAULT]`,value:user});transaction.oncomplete=resolve;transaction.onerror=()=>reject(new Error('Firebase persistence could not be saved.'))});db.close();
   },{token:account.token,uid:account.uid,email:account.email});
   await page.reload({waitUntil:'domcontentloaded'});await page.getByRole('heading',{name:/A new look/}).waitFor({timeout:60000});
   authStorage=await context.storageState({indexedDB:true});record(`${activeScenario}: server-verified existing ordinary-login ID token restores administrator UI through Firebase persistence`);break;
  }
  await page.getByRole('textbox',{name:'Email address',exact:true}).fill(account.email);
  await page.getByLabel('Password',{exact:true}).fill(account.password);
  await page.getByRole('button',{name:'Enter the studio',exact:true}).click();
  const outcome=await Promise.any([
   page.getByRole('heading',{name:/A new look/}).waitFor({timeout:90000}).then(()=>({ok:true})),
   page.locator('.notice-error:visible').first().waitFor({timeout:90000}).then(async()=>({ok:false,notice:await page.locator('.notice-error:visible').first().innerText()})),
  ]);
  if(outcome.ok){
   authStorage=await context.storageState({indexedDB:true});await writeFile(resolve(root,'.deployment/catalog-auth-storage.json'),JSON.stringify({email:account.email,saved_at:new Date().toISOString(),storage:authStorage},null,2)+'\n',{mode:0o600});await chmod(resolve(root,'.deployment/catalog-auth-storage.json'),0o600);
   record(`${activeScenario}: ordinary email/password login succeeds with CAPTCHA enforced`);break;
  }
  const captcha=/security check could not be completed|captcha|recaptcha/i.test(outcome.notice);report.external_events.push({scenario:activeScenario,type:'Visible login rejection',attempt,captcha_error:captcha,notice:redact(outcome.notice)});
  if(!captcha||attempt===3)throw new Error('Ordinary UI sign-in was rejected; check the recorded visible notice.');
 }
 return page;
}
async function nav(page,name){
 const menu=page.getByRole('button',{name:'Open navigation',exact:true});if(await menu.isVisible())await menu.click();
 await page.getByRole('button',{name,exact:true}).click();
}
async function home(page){await page.locator('.app-header .brand-link').click();await page.getByRole('tab',{name:/Pick a virtual Dress to Try/}).waitFor();await page.locator('.generate-button:visible').waitFor();}
async function capture(page,name){
 if(await page.locator('.garment-grid:visible').count())await page.waitForFunction(()=>{const grid=document.querySelector('.garment-grid');const cards=Array.from(grid?.querySelectorAll('.garment-card')??[]);return !cards.length||cards.every(card=>{const image=card.querySelector('.garment-image img');return image?.complete&&image.naturalWidth>0})},{},{timeout:30000});
 const dimensions=await page.evaluate(()=>({viewport:innerWidth,page_width:document.documentElement.scrollWidth}));
 record(`${name}: no horizontal page overflow`,dimensions.page_width<=dimensions.viewport+1,dimensions);
 await page.screenshot({path:resolve(output,`${name}.png`),fullPage:true});
}
async function saveLabel(page,kind){
 const dialog=page.getByRole('dialog',{name:'Add a new piece',exact:true});
 const title={category:'Type',store:'Store Name',brand:'Brand Name'}[kind];
 if(state[kind]){await dialog.getByLabel(new RegExp(`^${title}`)).selectOption(state[kind].id);return}
 await dialog.getByRole('button',{name:`Add new ${title}`,exact:true}).click();
 await dialog.getByLabel(`New ${title}`,{exact:true}).fill(names[kind]);
 if(kind==='category')await dialog.getByLabel(/^Body coverage/).selectOption('full');
 const pathname=kind==='category'?'/api/admin/categories':'/api/admin/catalog/labels';
 const accepted=page.waitForResponse(response=>new URL(response.url()).pathname===pathname&&response.request().method()==='POST');
 await dialog.getByRole('button',{name:'Save label',exact:true}).click();
 const response=await accepted;
 const body=await response.json();
 if(response.status()!==201)throw new Error(`UI ${title} creation failed with HTTP ${response.status()}.`);
 state[kind]=body;await saveState();
 await page.waitForFunction(({title,id})=>Array.from(document.querySelectorAll('.catalog-label-field')).some(field=>field.querySelector('label')?.textContent.startsWith(title)&&field.querySelector('select')?.value===id),{title,id:body.id});
 record(`${title}: inline UI creation saves and immediately selects its persistent label`,body.name===names[kind],{id:body.id});
}
async function createResources(page){
 if(state.garment)return;
 await nav(page,'Administration');await page.getByRole('tab',{name:'Collection',exact:true}).click();
 await page.getByRole('button',{name:'Garment',exact:true}).click();
 const dialog=page.getByRole('dialog',{name:'Add a new piece',exact:true});await dialog.waitFor();
 const bytes=await readFile(resolve(root,'sample_assets/cream-dress.jpg'));
 await dialog.getByLabel(/^Dress photos/).setInputFiles([{name:'licensed-dress-front.jpg',mimeType:'image/jpeg',buffer:bytes},{name:'licensed-dress-reference.jpg',mimeType:'image/jpeg',buffer:bytes}]);
 await page.waitForFunction(()=>{const images=Array.from(document.querySelectorAll('.dress-photo-draft img'));return images.length===2&&images.every(image=>image.complete&&image.naturalWidth>0)});
 record('Admin multiple-photo chooser displays two local reference previews and removal controls',(await dialog.locator('.dress-photo-draft').count())===2&&(await dialog.getByRole('button',{name:/Remove dress photo/}).count())===2);
 await dialog.getByLabel('Name',{exact:true}).fill(names.garment);
 await dialog.getByLabel('Description',{exact:true}).fill('Temporary browser QA fixture; not a retail catalog item.');
 for(const kind of ['category','store','brand'])await saveLabel(page,kind);
 await dialog.locator('summary').filter({hasText:'Photo attribution and source'}).click();
 await dialog.getByLabel('Licence',{exact:true}).fill('CC0 1.0');await dialog.getByLabel('Attribution',{exact:true}).fill('Paul Poiret / The Metropolitan Museum of Art; duplicate reference for UI testing');await dialog.getByLabel('Source URL',{exact:true}).fill('https://commons.wikimedia.org/wiki/File:Dress_MET_DP143261.jpg');
 await capture(page,'desktop-admin-add-piece');
 const accepted=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/admin/garments'&&response.request().method()==='POST');
 await dialog.getByRole('button',{name:'Save piece',exact:true}).click();
 const response=await accepted;const garment=await response.json();
 if(response.status()!==201)throw new Error(`UI dress creation failed with HTTP ${response.status()}.`);
 state.garment=garment;await saveState();
 report.resource_ids={category:state.category.id,store:state.store.id,brand:state.brand.id,garment:garment.id};
 record('UI dress save persists Type, Store Name, Brand Name and two ordered garment photo URLs',garment.category_id===state.category.id&&garment.store_id===state.store.id&&garment.brand_id===state.brand.id&&garment.image_urls?.length===2&&new Set(garment.image_urls).size===2,{garment_id:garment.id,photo_count:garment.image_urls?.length});
 await dialog.waitFor({state:'hidden'});
 await home(page);
 record('New Type, Store Name and Brand Name appear immediately in the studio after saving the piece',await page.getByRole('group',{name:'Filter by dress type',exact:true}).getByRole('button',{name:state.category.name,exact:true}).isVisible()&&await page.getByRole('group',{name:'Filter by Store Name',exact:true}).getByRole('button',{name:state.store.name,exact:true}).isVisible()&&await page.getByRole('group',{name:'Filter by Brand Name',exact:true}).getByRole('button',{name:state.brand.name,exact:true}).isVisible());
}
async function filtersAndPhotos(page,name){
 for(const [group,kind] of [['Filter by dress type','category'],['Filter by Store Name','store'],['Filter by Brand Name','brand']])await page.getByRole('group',{name:group,exact:true}).getByRole('button',{name:state[kind].name,exact:true}).click();
 const card=page.locator('.garment-card:visible');
 record(`${name}: combined type, store and brand filters show only the saved dress`,await card.count()===1&&(await card.innerText()).includes(names.garment));
 await card.getByRole('button',{name:`Select ${names.garment}`,exact:true}).click();
 record(`${name}: the multi-reference dress can be selected`,await card.getByRole('button',{name:`Remove ${names.garment}`,exact:true}).getAttribute('aria-pressed')==='true');
 await card.getByRole('button',{name:`View all 2 photos of ${names.garment}`,exact:true}).click();
 const dialog=page.getByRole('dialog',{name:names.garment,exact:true});await dialog.waitFor();
 await page.waitForFunction(()=>{const image=document.querySelector('[role="dialog"] .garment-detail-image');return image?.tagName==='IMG'&&image.complete&&image.naturalWidth>0});
 const initial=await dialog.locator('.garment-detail-image').getAttribute('src');
 await dialog.getByRole('button',{name:'Next dress photo',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('.garment-photo-navigation')?.textContent.includes('Photo 2 of 2'));
 await page.waitForFunction(initial=>{const image=document.querySelector('[role="dialog"] .garment-detail-image');return image?.tagName==='IMG'&&image.complete&&image.naturalWidth>0&&image.getAttribute('src')!==initial},initial);
 record(`${name}: next arrow displays the second ordered reference`,await dialog.locator('.garment-detail-image').getAttribute('src')!==initial&&await dialog.getByRole('button',{name:'View dress photo 2',exact:true}).getAttribute('aria-pressed')==='true');
 await dialog.getByRole('button',{name:'View dress photo 1',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('.garment-photo-navigation')?.textContent.includes('Photo 1 of 2'));
 record(`${name}: photo thumbnail restores the first reference`,await dialog.getByRole('button',{name:'View dress photo 1',exact:true}).getAttribute('aria-pressed')==='true');
 await capture(page,`${name}-photos`);await dialog.getByRole('button',{name:'Close dialog',exact:true}).click();
 await home(page);
}
async function optionsAndLayout(page,name){
 const virtual=page.getByRole('tab',{name:/Pick a virtual Dress to Try/});const real=page.getByRole('tab',{name:/Pick a real Dress to Try/});
 record(`${name}: both renamed try-on options and requested support text are visible`,await virtual.isVisible()&&await real.isVisible()&&(await virtual.innerText()).includes('Click a photo of yours and select a dress from the virtual gallery')&&(await real.innerText()).includes('Click a photo of you holding the dress'));
 const fonts=await page.locator('.workflow-label').evaluateAll(elements=>elements.map(element=>({title:parseFloat(getComputedStyle(element).fontSize),support:parseFloat(getComputedStyle(element.querySelector('small')).fontSize)})));
 record(`${name}: option support text uses a smaller font`,fonts.every(font=>font.support<font.title),{fonts});
 record(`${name}: original dress types remain alongside store and brand filters`,await page.getByRole('group',{name:'Filter by dress type',exact:true}).getByRole('button',{name:'Dresses',exact:true}).isVisible()&&await page.getByRole('group',{name:'Filter by dress type',exact:true}).getByRole('button',{name:'Pants',exact:true}).isVisible());
 await real.click();
 const guidance=await page.locator('.holding-intro:visible').innerText();
 record(`${name}: real-garment guidance allows children and avoids repeated recapture instructions`,guidance.includes('For children and adults')&&!/new photo|better photo|clearer photo|adult.only|full body|one person and one garment/i.test(guidance)&&(await page.locator('.photo-guidance:visible p').count())===1);
 await capture(page,`${name}-real-dress`);
 await virtual.click();await capture(page,name);
}

try{
 const desktop=await browser.newContext({viewport:{width:1440,height:1000},...(authStorage?{storageState:authStorage}:{})});activeScenario='desktop';const page=await prepare(desktop);
 await createResources(page);
 report.resource_ids={category:state.category?.id,store:state.store?.id,brand:state.brand?.id,garment:state.garment?.id};
 await filtersAndPhotos(page,'desktop');await optionsAndLayout(page,'desktop');
 const persisted=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/garments'&&response.request().method()==='GET');
 await page.reload({waitUntil:'domcontentloaded'});await page.getByRole('heading',{name:/A new look/}).waitFor({timeout:60000});
 const listing=await(await persisted).json();const saved=listing.find(garment=>garment.id===state.garment.id);
 record('Reload restores the garment labels and both server photo references',saved?.category_id===state.category.id&&saved?.store_id===state.store.id&&saved?.brand_id===state.brand.id&&saved?.image_urls?.length===2);
 await filtersAndPhotos(page,'desktop-reload');await optionsAndLayout(page,'desktop-reload');
 report.scenarios.push({name:'desktop',passed:true,viewport:{width:1440,height:1000},engine:'Installed Chrome'});await desktop.close();activePage=undefined;
 for(const [name,profile] of [['android',devices['Pixel 7']],['iphone',devices['iPhone 13']],['ipad',devices['iPad (gen 7)']]]){
  activeScenario=name;const {defaultBrowserType:_unused,...device}=profile;const context=await browser.newContext({...device,...(authStorage?{storageState:authStorage}:{})});const mobile=await prepare(context);
  await filtersAndPhotos(mobile,name);await optionsAndLayout(mobile,name);
  report.scenarios.push({name,passed:true,viewport:device.viewport,engine:'Chrome device emulation'});await context.close();activePage=undefined;
 }
 record('Browser verification made no paid generation submissions',report.paid_submissions===0,{provider_calls:0});
 report.passed=report.errors.length===0&&report.scenarios.length===4;state.browser_verified=report.passed;await saveState();
}catch(error){
 const notices=activePage?await activePage.locator('.notice-error:visible').allTextContents().catch(()=>[]):[];
 const screenshot=resolve(output,`${activeScenario}-failure.png`);if(activePage)await activePage.screenshot({path:screenshot,fullPage:true}).catch(()=>{});
 report.errors.push({type:'verification',scenario:activeScenario,message:redact(error.message).slice(0,1800),notice_errors:notices.map(redact),screenshot});report.passed=false;
 // Only visible, redacted application notices and the failure screenshot path are emitted.
 console.error(JSON.stringify({notice_errors:notices.map(redact),failure_screenshot:screenshot}));
}finally{
 await browser.close();report.completed_at=new Date().toISOString();
 try{const initial=JSON.parse(await readFile(resolve(root,'verification/catalog-upgrade-browser-initial.json'),'utf8'));if(initial.passed&&initial.resource_ids?.garment===state.garment?.id)report.initial_ui_creation_evidence={report:'verification/catalog-upgrade-browser-initial.json',passed:true,checks:initial.checks.length,resource_ids:initial.resource_ids}}catch(error){if(error.code!=='ENOENT')throw error}
 await writeFile(reportPath,JSON.stringify(report,null,2)+'\n');
 console.log(JSON.stringify({passed:report.passed,scenarios:report.scenarios.length,checks:report.checks.length,errors:report.errors.length,paid_submissions:report.paid_submissions,report:reportPath,cleanup_state:statePath}));
}
if(!report.passed)process.exitCode=1;
