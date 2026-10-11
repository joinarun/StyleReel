import { useState } from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import type { Garment } from '../types';
import { garmentPhotos } from '../lib/catalog';
import { ProtectedImage } from './Common';

export default function GarmentPhotos({garment}:{garment:Garment}){
 const photos=garmentPhotos(garment);const [current,setCurrent]=useState(0);
 const index=Math.min(current,Math.max(0,photos.length-1));
 return <div className="garment-photos" aria-label={`Photos of ${garment.name}`}>
  <ProtectedImage src={photos[index]} alt={`${garment.name}, photo ${index+1} of ${photos.length}`} className="garment-detail-image"/>
  {photos.length>1&&<>
   <div className="garment-photo-navigation"><button className="icon-button" aria-label="Previous dress photo" onClick={()=>setCurrent((index+photos.length-1)%photos.length)}><ChevronLeft size={21}/></button><span aria-live="polite">Photo {index+1} of {photos.length}</span><button className="icon-button" aria-label="Next dress photo" onClick={()=>setCurrent((index+1)%photos.length)}><ChevronRight size={21}/></button></div>
   <div className="garment-photo-thumbnails" aria-label="All dress photos">{photos.map((url,position)=><button key={url} type="button" aria-label={`View dress photo ${position+1}`} aria-pressed={position===index} onClick={()=>setCurrent(position)}><ProtectedImage src={url} alt=""/></button>)}</div>
  </>}
 </div>
}
