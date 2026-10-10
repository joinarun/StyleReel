import type { GalleryItem, Job } from '../types';
import type { PendingLook } from './gallery';

export interface ShareViewToken {revision:number;itemId:string}
export class AsyncViewGate {
 private revision=0;
 private itemId:string|null=null;
 open(itemId:string):ShareViewToken{this.itemId=itemId;return {revision:++this.revision,itemId}}
 close(){this.revision++;this.itemId=null}
 accepts(token:ShareViewToken){return this.itemId===token.itemId&&this.revision===token.revision}
}

export class ObservedResults {
 private observed=new Set<string>();
 status(itemId:string,items:GalleryItem[]):'waiting'|'available'|'removed'{if(items.some(item=>item.id===itemId)){this.observed.add(itemId);return 'available'}return this.observed.has(itemId)?'removed':'waiting'}
}

export function canApplyRecoveredWorkflow(startHomeRevision:number,currentHomeRevision:number){return startHomeRevision===currentHomeRevision}
export function pendingLookSnapshot(job:Job,before:string,providerLabel:string,model:string):PendingLook{const copy=structuredClone(job);if(copy.garment_names)Object.freeze(copy.garment_names);if(copy.error&&typeof copy.error==='object')Object.freeze(copy.error);return Object.freeze({job:Object.freeze(copy),before,provider:job.provider_label??providerLabel,model:job.model??model})}
