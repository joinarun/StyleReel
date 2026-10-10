import type { GalleryItem, Job } from '../types';
interface RecordData {id:string;uid:string;iv:Uint8Array;ciphertext:ArrayBuffer}
let key:CryptoKey|null=null;let owner:string|null=null;
const dbPromise=()=>new Promise<IDBDatabase>((resolve,reject)=>{const request=indexedDB.open('stylereel-private-gallery',2);request.onupgradeneeded=()=>{if(!request.result.objectStoreNames.contains('images')){const store=request.result.createObjectStore('images',{keyPath:'id'});store.createIndex('uid','uid')}if(!request.result.objectStoreNames.contains('pending'))request.result.createObjectStore('pending',{keyPath:'id'})};request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error)});
export async function unlockGallery(uid:string,encoded:string){const raw=Uint8Array.from(atob(encoded),c=>c.charCodeAt(0));key=await crypto.subtle.importKey('raw',raw,{name:'AES-GCM'},false,['encrypt','decrypt']);owner=uid}
export function lockGallery(){key=null;owner=null}
function credentials(){if(!key||!owner)throw new Error('Your private gallery is locked. Please sign in again.');return {key,owner}}
export function captureGallerySession(){const auth=credentials();return ()=>owner===auth.owner&&key===auth.key}
function assertCurrentSession(auth:{key:CryptoKey;owner:string}){if(owner!==auth.owner||key!==auth.key)throw new Error('Your private gallery is locked. Please sign in again.')}
export async function listGallery():Promise<GalleryItem[]>{const auth=credentials();const db=await dbPromise();try{const records=await new Promise<RecordData[]>((resolve,reject)=>{const request=db.transaction('images').objectStore('images').index('uid').getAll(auth.owner);request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error)});const items=await Promise.all(records.map(async record=>{try{const decrypted=await crypto.subtle.decrypt({name:'AES-GCM',iv:record.iv as Uint8Array<ArrayBuffer>},auth.key,record.ciphertext);return JSON.parse(new TextDecoder().decode(decrypted)) as GalleryItem}catch{return null}}));if(owner!==auth.owner||key!==auth.key)throw new Error('Your private gallery is locked. Please sign in again.');return items.filter((item):item is GalleryItem=>item!==null).sort((a,b)=>b.created_at.localeCompare(a.created_at))}finally{db.close()}}
export async function saveGallery(item:GalleryItem){const auth=credentials();const iv=crypto.getRandomValues(new Uint8Array(12));const ciphertext=await crypto.subtle.encrypt({name:'AES-GCM',iv},auth.key,new TextEncoder().encode(JSON.stringify(item)));const db=await dbPromise();try{assertCurrentSession(auth);await new Promise<void>((resolve,reject)=>{const tx=db.transaction('images','readwrite');tx.objectStore('images').put({id:`${auth.owner}:${item.id}`,uid:auth.owner,iv,ciphertext});tx.oncomplete=()=>resolve();tx.onerror=()=>reject(tx.error)})}finally{db.close()}}
export async function removeGallery(ids:string[]){const auth=credentials();const db=await dbPromise();try{assertCurrentSession(auth);await new Promise<void>((resolve,reject)=>{const tx=db.transaction('images','readwrite');for(const id of ids)tx.objectStore('images').delete(`${auth.owner}:${id}`);tx.oncomplete=()=>resolve();tx.onerror=()=>reject(tx.error)})}finally{db.close()}}

export interface PendingLook {job:Job;before:string;provider:string;model:string}
export async function savePendingLook(value:PendingLook){
 const auth=credentials();const iv=crypto.getRandomValues(new Uint8Array(12));const ciphertext=await crypto.subtle.encrypt({name:'AES-GCM',iv},auth.key,new TextEncoder().encode(JSON.stringify(value)));const db=await dbPromise();
 try{assertCurrentSession(auth);await new Promise<void>((resolve,reject)=>{const tx=db.transaction('pending','readwrite');tx.objectStore('pending').put({id:auth.owner,iv,ciphertext});tx.oncomplete=()=>resolve();tx.onerror=()=>reject(tx.error)})}finally{db.close()}
}
export async function getPendingLook():Promise<PendingLook|null>{
 const auth=credentials();const db=await dbPromise();
 try{const record=await new Promise<RecordData|undefined>((resolve,reject)=>{const request=db.transaction('pending').objectStore('pending').get(auth.owner);request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error)});if(!record)return null;const decrypted=await crypto.subtle.decrypt({name:'AES-GCM',iv:record.iv as Uint8Array<ArrayBuffer>},auth.key,record.ciphertext);if(owner!==auth.owner||key!==auth.key)return null;return JSON.parse(new TextDecoder().decode(decrypted)) as PendingLook}finally{db.close()}
}
export async function clearPendingLook(){
 const auth=credentials();const db=await dbPromise();
 try{assertCurrentSession(auth);await new Promise<void>((resolve,reject)=>{const tx=db.transaction('pending','readwrite');tx.objectStore('pending').delete(auth.owner);tx.oncomplete=()=>resolve();tx.onerror=()=>reject(tx.error)})}finally{db.close()}
}
