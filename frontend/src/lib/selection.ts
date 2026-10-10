import type { Category, Garment, Provider } from '../types';
export function selectGarment(selected:string[],next:Garment,garments:Garment[],categories:Category[]):string[]{
 if(selected.includes(next.id))return selected.filter(id=>id!==next.id);
 const slot=categories.find(c=>c.id===next.category_id)?.slot;
 if(!slot)return selected;
 if(slot==='full')return[next.id];
 const keep=selected.filter(id=>{const garment=garments.find(g=>g.id===id);const other=categories.find(c=>c.id===garment?.category_id)?.slot;return other && other!=='full'&&other!==slot});
 return [...keep,next.id];
}
export function estimatedCalls(workflow:'catalog'|'holding',count:number,provider:Provider|undefined){return workflow==='holding'?2:provider?.supports_multi?1:Math.max(1,count)}
export function estimateCost(calls:number,provider:Provider|undefined,model:string){const cost=provider?.model_costs?.[model]??provider?.estimated_cost_per_call_usd;return cost===undefined?null:cost*calls}
export function isExperimental(selected:string[],garments:Garment[],categories:Category[]){return selected.some(id=>categories.find(c=>c.id===garments.find(g=>g.id===id)?.category_id)?.experimental)}
