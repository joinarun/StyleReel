import { afterEach, describe, expect, it, vi } from 'vitest';
import { CATALOG_PHOTO_TARGET_BYTES, MAX_CATALOG_UPLOAD_BYTES, prepareCatalogPhotos } from './catalogUpload';

const photo=(name:string,bytes:number,type='image/jpeg')=>new File([new Uint8Array(bytes)],name,{type,lastModified:123});
afterEach(()=>vi.unstubAllGlobals());
function decodable({bytes=1024*1024,width=6000,height=4000}:{bytes?:number;width?:number;height?:number}={}){
 const bitmap={width,height,close:vi.fn()};const drawImage=vi.fn();const canvas={width:0,height:0,getContext:()=>({fillStyle:'',fillRect:vi.fn(),drawImage}),toBlob:vi.fn((callback:(blob:Blob)=>void)=>callback(new Blob([new Uint8Array(bytes)],{type:'image/jpeg'})))};
 vi.stubGlobal('createImageBitmap',vi.fn(async()=>bitmap));vi.stubGlobal('document',{createElement:vi.fn(()=>canvas)});
 return {bitmap,canvas,drawImage};
}
function undecodable(){
 vi.stubGlobal('createImageBitmap',vi.fn(async()=>{throw new Error('Unsupported codec')}));
 class UnsupportedImage{onerror:(()=>void)|undefined;set src(_url:string){queueMicrotask(()=>this.onerror?.())}}
 vi.stubGlobal('Image',UnsupportedImage);
}
describe('catalog upload preparation',()=>{
 it('preserves small references exactly, including ordered views and file metadata',async()=>{
  const files=[photo('front.png',100,'image/png'),photo('back.webp',CATALOG_PHOTO_TARGET_BYTES,'image/webp')];
  const result=await prepareCatalogPhotos(files);expect(result.files[0]).toBe(files[0]);expect(result.files[1]).toBe(files[1]);expect(result.totalBytes).toBe(100+CATALOG_PHOTO_TARGET_BYTES);expect(result.compressedPhotos).toBe(0);
 });
 it('resizes a large reference proportionally without cropping and uses the requested JPEG quality',async()=>{
  const {bitmap,canvas,drawImage}=decodable();const original=photo('model-wearing-dress.png',4*1024*1024,'image/png');
  const result=await prepareCatalogPhotos([original]);expect(canvas.width).toBe(2048);expect(canvas.height).toBe(1365);expect(drawImage).toHaveBeenCalledWith(bitmap,0,0,2048,1365);expect(canvas.toBlob).toHaveBeenCalledWith(expect.any(Function),'image/jpeg',0.88);expect(bitmap.close).toHaveBeenCalledOnce();
  expect(result.files[0].name).toBe('model-wearing-dress.jpg');expect(result.files[0].type).toBe('image/jpeg');expect(result.files[0].lastModified).toBe(123);expect(result.files[0].size).toBeLessThanOrEqual(CATALOG_PHOTO_TARGET_BYTES);expect(result.compressedPhotos).toBe(1);
 });
 it('prepares all six photos in their original order to fit the complete request bound',async()=>{
  decodable();const files=Array.from({length:6},(_,index)=>photo(`view-${index}.png`,6*1024*1024,'image/png'));
  const result=await prepareCatalogPhotos(files);expect(result.files.map(file=>file.name)).toEqual(files.map(file=>file.name.replace('.png','.jpg')));expect(result.compressedPhotos).toBe(6);expect(result.totalBytes).toBeLessThan(MAX_CATALOG_UPLOAD_BYTES);
 });
 it('passes HEIC through to server conversion when the browser cannot decode, if the complete request fits',async()=>{
  undecodable();const file=photo('iphone.heic',8*1024*1024,'image/heic');const result=await prepareCatalogPhotos([file]);expect(result.files).toEqual([file]);expect(result.compressedPhotos).toBe(0);
 });
 it('reports an actionable error for a total that cannot be compressed under 28 MB',async()=>{
  undecodable();const files=Array.from({length:6},(_,index)=>photo(`iphone-${index}.heic`,5*1024*1024,'image/heic'));await expect(prepareCatalogPhotos(files)).rejects.toThrow('28 MB');await expect(prepareCatalogPhotos(files)).rejects.toThrow('export large HEIC photos as JPEG');
 });
 it('tries a smaller proportional canvas when the initial JPEG remains above 3 MB',async()=>{
  const {canvas,bitmap}=decodable({bytes:4*1024*1024});canvas.toBlob.mockImplementationOnce(callback=>callback(new Blob([new Uint8Array(4*1024*1024)]))).mockImplementationOnce(callback=>callback(new Blob([new Uint8Array(2*1024*1024)])));
  const result=await prepareCatalogPhotos([photo('front.jpg',6*1024*1024)]);expect(canvas.width).toBe(1536);expect(canvas.height).toBe(1024);expect(result.files[0].size).toBe(2*1024*1024);expect(bitmap.close).toHaveBeenCalledOnce();
 });
});
