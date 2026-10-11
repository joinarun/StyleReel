/** Keep all reference views while fitting Cloud Run's complete HTTP request limit. */
export const MAX_CATALOG_UPLOAD_BYTES=28*1024*1024;
export const CATALOG_PHOTO_TARGET_BYTES=3*1024*1024;
const MAX_EDGE=2048;
const JPEG_QUALITY=0.88;

type DecodedPhoto={image:CanvasImageSource;width:number;height:number;dispose:()=>void};
async function decodePhoto(file:File):Promise<DecodedPhoto>{
 if(typeof createImageBitmap==='function'){
  try{const bitmap=await createImageBitmap(file,{imageOrientation:'from-image'});return {image:bitmap,width:bitmap.width,height:bitmap.height,dispose:()=>bitmap.close()}}
  catch{/* Safari and HEIC support vary; try the browser's normal image decoder. */}
 }
 const url=URL.createObjectURL(file);const image=new Image();
 try{
  await new Promise<void>((resolve,reject)=>{image.onload=()=>resolve();image.onerror=()=>reject(new Error('Browser image decoder unavailable.'));image.src=url});
  if(!image.naturalWidth||!image.naturalHeight)throw new Error('Browser image decoder unavailable.');
  return {image,width:image.naturalWidth,height:image.naturalHeight,dispose:()=>URL.revokeObjectURL(url)};
 }catch(error){URL.revokeObjectURL(url);throw error}
}

async function compressPhoto(file:File):Promise<File>{
 if(file.size<=CATALOG_PHOTO_TARGET_BYTES)return file;
 let decoded:DecodedPhoto;
 try{decoded=await decodePhoto(file)}catch{return file} // Server can convert HEIC even when this browser cannot preview it.
 try{
  for(const edge of [MAX_EDGE,1536,1024]){
   const scale=Math.min(1,edge/Math.max(decoded.width,decoded.height));const canvas=document.createElement('canvas');
   canvas.width=Math.max(1,Math.round(decoded.width*scale));canvas.height=Math.max(1,Math.round(decoded.height*scale));
   const context=canvas.getContext('2d');if(!context)return file;
   context.fillStyle='#ffffff';context.fillRect(0,0,canvas.width,canvas.height);context.drawImage(decoded.image,0,0,canvas.width,canvas.height);
   const blob=await new Promise<Blob|null>(resolve=>canvas.toBlob(resolve,'image/jpeg',JPEG_QUALITY));
   if(blob&&blob.size<=CATALOG_PHOTO_TARGET_BYTES){const name=file.name.replace(/\.[^.]+$/,'')||'dress-reference';return new File([blob],`${name}.jpg`,{type:'image/jpeg',lastModified:file.lastModified})}
  }
  return file;
 }catch{return file}finally{decoded.dispose()}
}

export async function prepareCatalogPhotos(files:File[]):Promise<{files:File[];totalBytes:number;compressedPhotos:number}>{
 // Sequential decoding avoids holding six full-resolution canvases in mobile memory.
 const prepared:File[]=[];let compressedPhotos=0;
 for(const file of files){const next=await compressPhoto(file);prepared.push(next);if(next!==file)compressedPhotos++}
 const totalBytes=prepared.reduce((total,file)=>total+file.size,0);
 if(totalBytes>MAX_CATALOG_UPLOAD_BYTES)throw new Error('These dress photos exceed the 28 MB upload limit after preparation. Choose fewer photos, or export large HEIC photos as JPEG and try again.');
 return {files:prepared,totalBytes,compressedPhotos};
}
