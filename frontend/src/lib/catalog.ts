import type { CatalogLabels, Garment } from '../types';

export interface CatalogFilters { category:string; store:string; brand:string; search:string }

export function filterGarments(garments:Garment[], filters:CatalogFilters, labels:CatalogLabels):Garment[]{
 const query=filters.search.trim().toLocaleLowerCase();
 return garments.filter(garment=>garment.active
  &&(filters.category==='all'||garment.category_id===filters.category)
  &&(filters.store==='all'||garment.store_id===filters.store)
  &&(filters.brand==='all'||garment.brand_id===filters.brand)
  &&[garment.name,garment.description,labels.stores.find(label=>label.id===garment.store_id)?.name,labels.brands.find(label=>label.id===garment.brand_id)?.name].filter(Boolean).join(' ').toLocaleLowerCase().includes(query));
}

export function garmentPhotos(garment:Garment):string[]{
 const photos=garment.image_urls?.filter(Boolean)??[];
 return Array.from(new Set(photos.length?photos:[garment.image_url].filter(Boolean)));
}

export const MAX_GARMENT_PHOTOS=6;
export function validateGarmentPhotos(files:File[]):string|undefined{
 if(!files.length)return 'Add at least one photo of the dress.';
 if(files.length>MAX_GARMENT_PHOTOS)return `Add up to ${MAX_GARMENT_PHOTOS} photos per dress.`;
 if(files.some(file=>file.size>12*1024*1024))return 'Each dress photo must be 12 MB or smaller.';
 if(files.some(file=>!/^image\/(jpeg|png|webp|heic|heif)$/i.test(file.type)&&!(/\.(jpe?g|png|webp|heic|heif)$/i.test(file.name))))return 'Use JPEG, PNG, WebP, or iPhone HEIC photos.';
 return undefined;
}
