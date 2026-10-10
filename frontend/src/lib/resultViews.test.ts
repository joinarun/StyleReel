import { describe, expect, it } from 'vitest';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import Gallery from '../components/Gallery';
import Studio from '../components/Studio';
import type { GalleryItem, Settings } from '../types';

const item:GalleryItem={id:'result-a',created_at:'2026-10-09',garment_names:['Test garment'],workflow:'catalog',before:'PRIVATE_SOURCE_PHOTOGRAPH',after:'data:image/jpeg;base64,GENERATED_RESULT',provider:'Google',model:'pro',estimated_cost_usd:.25};
const settings:Settings={ai:{provider:'google',model:'pro',resolution:'2K',system_prompt:'',catalog_prompt:'',holding_prompt:'',timeout_seconds:120},rate_limits:{max_calls:2,window_seconds:60,daily_user_calls:20,daily_global_calls:100,monthly_budget_usd:25},gallery:{max_images:20},providers:[{id:'google',label:'Google',configured:true,status:'ready',models:['pro'],supports_holding:true,supports_multi:true,prompt_supported:true,estimated_cost_per_call_usd:.25}]};

describe('generated-image result markup',()=>{
 it('renders generated images and selectable recent looks without exposing stored source photos or comparison controls',()=>{const markup=renderToStaticMarkup(createElement(Gallery,{items:[item],max:20,onRefresh:async()=>{},onCreate:()=>{}}));expect(markup).toContain('GENERATED_RESULT');expect(markup).not.toContain('PRIVATE_SOURCE_PHOTOGRAPH');expect(markup).not.toContain('type="range"');expect(markup).toContain('aria-label="Recent saved looks"');expect(markup).toContain('aria-pressed="true"');expect(markup).toContain('aria-label="Download look"');expect(markup).toContain('aria-label="Share look with QR"')});
 it('replaces the consent checkbox with legible Generate authorization and provider-retention disclosure',()=>{const markup=renderToStaticMarkup(createElement(Studio,{settings,garments:[],categories:[],gallery:[],onSaved:()=>{},onGallery:async()=>{},homeRevision:0,visible:true}));expect(markup).not.toContain('type="checkbox"');expect(markup).toContain('By pressing Generate');expect(markup).toContain('Processing may occur outside India');expect(markup).toContain('Provider retention terms apply');expect(markup).toContain('processing-disclosure')});
});
