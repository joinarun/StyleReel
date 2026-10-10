import type { UsageEvent } from '../types';
export function usageTokens(event:UsageEvent){
 const reported=event.reported_usage??{};
 const count=(value:unknown):number|undefined=>typeof value==='number'&&Number.isFinite(value)&&value>=0?value:undefined;
 return {input:count(reported.promptTokenCount)??count(event.input_tokens),output:count(reported.candidatesTokenCount)??count(event.output_tokens),thinking:count(reported.thoughtsTokenCount)};
}
export function usageCsv(events:UsageEvent[]){
 const fields=['created_at','user_id','provider','model','workflow','status','estimated_cost_usd','duration_seconds','input_tokens','output_tokens','thinking_tokens'];
 return [fields.join(','),...events.map(event=>{const tokens=usageTokens(event);const row:Record<string,unknown>={...event,input_tokens:tokens.input,output_tokens:tokens.output,thinking_tokens:tokens.thinking};return fields.map(field=>`"${String(row[field]??'').replaceAll('"','""')}"`).join(',')})].join('\r\n');
}
