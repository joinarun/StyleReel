import { describe, expect, it } from 'vitest';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import Studio from '../components/Studio';
import GarmentPhotos from '../components/GarmentPhotos';
import PhotoPicker from '../components/PhotoPicker';
import type { CatalogLabels, Category, Garment, Settings } from '../types';

const settings:Settings={ai:{provider:'google',model:'pro',resolution:'2K',system_prompt:'',catalog_prompt:'',holding_prompt:'',timeout_seconds:120},rate_limits:{max_calls:2,window_seconds:60,daily_user_calls:20,daily_global_calls:100,monthly_budget_usd:25},gallery:{max_images:20},providers:[{id:'google',label:'Google',configured:true,status:'ready',models:['pro'],supports_holding:true,supports_multi:true,prompt_supported:true}]};
const labels:CatalogLabels={stores:[{id:'new-store',name:'Admin-added store'}],brands:[{id:'new-brand',name:'Admin-added brand'}]};
const categories:Category[]=[{id:'dresses',name:'Dresses',slot:'full'},{id:'pants',name:'Pants',slot:'lower'}];
const garment:Garment={id:'blue',name:'Blue dress',category_id:'dresses',store_id:'new-store',brand_id:'new-brand',active:true,image_url:'/front.jpg',image_urls:['/front.jpg','/back-on-model.jpg']};

describe('try-on options and collection markup',()=>{
 it('shows both requested option names, small supporting text, and the three distinct filter rows',()=>{
  const markup=renderToStaticMarkup(createElement(Studio,{settings,labels,categories,garments:[garment],gallery:[],onSaved:()=>{},onGallery:async()=>{},homeRevision:0,visible:true}));
  expect(markup).toContain('Pick a real Dress to Try');expect(markup).toContain('<small>Click a photo of you holding the dress</small>');expect(markup).toContain('Pick a virtual Dress to Try');expect(markup).toContain('<small>Click a photo of yours and select a dress from the virtual gallery</small>');
  expect(markup).toContain('Filter by dress type');expect(markup).toContain('Filter by Store Name');expect(markup).toContain('Filter by Brand Name');expect(markup).toContain('Dresses');expect(markup).toContain('Pants');expect(markup).toContain('Admin-added store');expect(markup).toContain('Admin-added brand');expect(markup).toContain('View all 2 photos');
 });
 it('provides accessible arrows and thumbnails for every available dress reference',()=>{
  const markup=renderToStaticMarkup(createElement(GarmentPhotos,{garment}));expect(markup).toContain('Previous dress photo');expect(markup).toContain('Next dress photo');expect(markup).toContain('View dress photo 1');expect(markup).toContain('View dress photo 2');expect(markup).toContain('aria-pressed="true"');expect(markup).toContain('Photo 1 of 2');
 });
 it('keeps holding-photo guidance short with no age gate or repeated recapture instructions',()=>{
  const markup=renderToStaticMarkup(createElement(PhotoPicker,{file:null,onChange:()=>{},holding:true,disabled:false}));expect(markup).toContain('Take or upload a photo of you holding the dress.');expect(markup).not.toContain('adult');expect(markup).not.toContain('Stand straight');expect(markup).not.toContain('full body');expect(markup).not.toContain('better result');
 });
});
