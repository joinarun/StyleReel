import type { User } from 'firebase/auth';
export class ApiError extends Error { constructor(public status:number,message:string,public retryAfter?:number){super(message);this.name='ApiError'} }
let currentUser:User|null=null;
export function setApiUser(user:User|null){currentUser=user}
export async function api<T>(path:string,init:RequestInit={}):Promise<T>{
 const headers=new Headers(init.headers);
 if(currentUser)headers.set('Authorization',`Bearer ${await currentUser.getIdToken()}`);
 if(init.body && !(init.body instanceof FormData)&&!headers.has('Content-Type'))headers.set('Content-Type','application/json');
 const response=await fetch(path,{...init,headers,credentials:'same-origin'});
 if(!response.ok){let detail='Something went wrong. Please try again.';try{const data=await response.json();detail=typeof data.detail==='string'?data.detail:(data.detail?.message || data.error?.message || data.message || detail)}catch{/* No response detail. */}throw new ApiError(response.status,detail,Number(response.headers.get('Retry-After'))||undefined)}
 if(response.status===204)return undefined as T;
 return response.json() as Promise<T>;
}
export const post=<T>(path:string,body:unknown)=>api<T>(path,{method:'POST',body:JSON.stringify(body)});
export const patch=<T>(path:string,body:unknown)=>api<T>(path,{method:'PATCH',body:JSON.stringify(body)});
export async function fetchImage(path:string,init:RequestInit={}):Promise<Blob>{
 const headers=new Headers(init.headers);
 const sameOrigin=!/^(https?:)?\/\//i.test(path)||(typeof location!=='undefined'&&new URL(path,location.origin).origin===location.origin);
 if(currentUser&&sameOrigin)headers.set('Authorization',`Bearer ${await currentUser.getIdToken()}`);
 const response=await fetch(path,{...init,headers,credentials:'same-origin'});
 if(!response.ok)throw new ApiError(response.status,'This image is no longer available.');
 return response.blob();
}
export function errorMessage(error:unknown){return error instanceof Error?error.message:'Something went wrong. Please try again.'}
