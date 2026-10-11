import { describe, expect, it } from 'vitest';
import { filterGarments, garmentPhotos, validateGarmentPhotos } from './catalog';
import type { CatalogLabels, Garment } from '../types';

const labels:CatalogLabels={stores:[{id:'a',name:'Arun Store'},{id:'b',name:'New Store'}],brands:[{id:'silk',name:'Silk Brand'},{id:'cotton',name:'Cotton Brand'}]};
const make=(id:string,fields:Partial<Garment>):Garment=>({id,name:id,category_id:'sarees',active:true,image_url:`/${id}-front.jpg`,...fields});
const garments=[make('rose',{store_id:'a',brand_id:'silk'}),make('blue',{store_id:'b',brand_id:'cotton'}),make('pants',{category_id:'pants',store_id:'a',brand_id:'cotton'}),make('hidden',{store_id:'a',active:false}),make('legacy',{})];
const all={category:'all',store:'all',brand:'all',search:''};

describe('collection label filters',()=>{
 it('combines type, store and brand and excludes inactive pieces',()=>{
  expect(filterGarments(garments,{...all,category:'sarees',store:'a',brand:'silk'},labels).map(piece=>piece.id)).toEqual(['rose']);
  expect(filterGarments(garments,{...all,store:'a',brand:'cotton'},labels).map(piece=>piece.id)).toEqual(['pants']);
 });
 it('finds newly added labels and supports searching a store or brand name',()=>{
  expect(filterGarments(garments,{...all,search:'new store'},labels).map(piece=>piece.id)).toEqual(['blue']);
  expect(filterGarments(garments,{...all,search:'COTTON BRAND'},labels).map(piece=>piece.id)).toEqual(['blue','pants']);
 });
 it('keeps older unlabelled garments visible with All filters and can filter to no matches',()=>{
  expect(filterGarments(garments,all,labels).map(piece=>piece.id)).toContain('legacy');
  expect(filterGarments(garments,{...all,category:'pants',brand:'silk'},labels)).toEqual([]);
 });
});
describe('garment reference photos',()=>{
 it('uses all ordered references and removes duplicated URLs without adding the legacy primary twice',()=>expect(garmentPhotos(make('model-dress',{image_urls:['/front.jpg','/back.jpg','/front.jpg']}))).toEqual(['/front.jpg','/back.jpg']));
 it('opens legacy single-photo garments with no migration required',()=>{expect(garmentPhotos(make('legacy',{}))).toEqual(['/legacy-front.jpg']);expect(garmentPhotos(make('empty',{image_urls:[]}))).toEqual(['/empty-front.jpg'])});
 it('requires 1–6 supported, size-limited photos while accepting HEIC filenames',()=>{
  const photo=new File(['photo'],'model-wearing-dress.jpg',{type:'image/jpeg'});
  expect(validateGarmentPhotos([])).toContain('at least one');expect(validateGarmentPhotos([photo])).toBeUndefined();expect(validateGarmentPhotos(Array(6).fill(photo))).toBeUndefined();expect(validateGarmentPhotos(Array(7).fill(photo))).toContain('up to 6');
  expect(validateGarmentPhotos([new File(['iphone'],'dress.heic')])).toBeUndefined();expect(validateGarmentPhotos([new File(['not image'],'document.pdf',{type:'application/pdf'})])).toContain('JPEG');
  const oversized=new File([new Uint8Array(12*1024*1024+1)],'large.jpg',{type:'image/jpeg'});expect(validateGarmentPhotos([oversized])).toContain('12 MB');
 });
});
