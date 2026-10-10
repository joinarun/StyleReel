export interface CropArea {x:number;y:number;width:number;height:number}
export async function cropImage(source:string,area:CropArea):Promise<File>{
 const image=new Image();image.src=source;await image.decode();
 const canvas=document.createElement('canvas');canvas.width=Math.round(area.width);canvas.height=Math.round(area.height);
 const context=canvas.getContext('2d');if(!context)throw new Error('Cropping is unavailable in this browser.');
 context.drawImage(image,area.x,area.y,area.width,area.height,0,0,canvas.width,canvas.height);
 const blob=await new Promise<Blob>((resolve,reject)=>canvas.toBlob(b=>b?resolve(b):reject(new Error('Could not crop the photo.')),'image/jpeg',0.94));
 return new File([blob],'person-cropped.jpg',{type:blob.type});
}
export function blobToDataUrl(blob:Blob):Promise<string>{return new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result));reader.onerror=()=>reject(new Error('Could not read the image.'));reader.readAsDataURL(blob)})}
export async function dataUrlToBlob(url:string){return (await fetch(url)).blob()}
export function downloadImage(url:string,name:string){const link=document.createElement('a');link.href=url;link.download=name;document.body.append(link);link.click();link.remove()}
