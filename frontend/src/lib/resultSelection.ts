import type { GalleryItem, Job } from '../types';

export function selectedLook(items:GalleryItem[],id:string|null){return items.find(item=>item.id===id)??items[0]??null}
export function recentLooks(items:GalleryItem[],current:GalleryItem){return items.some(item=>item.id===current.id)?items:[current,...items]}
export function preserveJobOnHome(job:Job|null,submitting:boolean,saving:boolean,recovering=false){return recovering||submitting||saving||job?.status==='queued'||job?.status==='processing'}
