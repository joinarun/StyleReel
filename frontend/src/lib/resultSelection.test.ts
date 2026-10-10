import { describe, expect, it } from 'vitest';
import type { GalleryItem, Job } from '../types';
import { selectedLook, recentLooks, preserveJobOnHome } from './resultSelection';

const look=(id:string):GalleryItem=>({id,created_at:'2026-10-09',garment_names:[id],workflow:'catalog',before:'private source',after:`generated-${id}`,provider:'Google',model:'pro',estimated_cost_usd:.25});
const job=(status:Job['status']):Job=>({id:'immutable-job',status,expected_calls:1,estimated_cost_usd:.25});

describe('generated-result selection and home recovery',()=>{
 it('keeps the selected older result when a newly finished look joins the gallery',()=>{const older=look('older');expect(selectedLook([look('new'),older],'older')).toBe(older)});
 it('selects the newest available result after the selected look is deleted',()=>{const newest=look('newest');expect(selectedLook([newest,look('older')],'deleted')).toBe(newest)});
 it('shows no result after the gallery becomes empty',()=>{expect(selectedLook([],'deleted')).toBeNull()});
 it('shows a just-finished result while encrypted gallery refresh is still pending',()=>{const fresh=look('fresh');expect(recentLooks([look('older')],fresh).map(item=>item.id)).toEqual(['fresh','older'])});
 it('does not duplicate a completed result after gallery refresh',()=>{const fresh=look('fresh');expect(recentLooks([fresh,look('older')],fresh).map(item=>item.id)).toEqual(['fresh','older'])});
 it('preserves queued jobs, processing jobs, submissions in flight, and result persistence on home',()=>{expect(preserveJobOnHome(job('queued'),false,false)).toBe(true);expect(preserveJobOnHome(job('processing'),false,false)).toBe(true);expect(preserveJobOnHome(null,true,false)).toBe(true);expect(preserveJobOnHome(job('succeeded'),false,true)).toBe(true)});
 it('permits fresh-home clearing only after processing and persistence have settled',()=>{for(const status of ['succeeded','failed','unknown'] as const)expect(preserveJobOnHome(job(status),false,false)).toBe(false);expect(preserveJobOnHome(null,false,false)).toBe(false)});
});
