import { useRef } from 'react';
import { Check, ChevronLeft, ChevronRight } from 'lucide-react';
import type { GalleryItem } from '../types';
import { dateLabel } from './Common';

export default function RecentLooks({items,currentId,onSelect,selection=[],onToggle}:{items:GalleryItem[];currentId:string;onSelect:(item:GalleryItem)=>void;selection?:string[];onToggle?:(id:string)=>void}){
 const strip=useRef<HTMLDivElement>(null);
 const scroll=(direction:number)=>strip.current?.scrollBy({left:direction*Math.max(160,strip.current.clientWidth*.75),behavior:'smooth'});
 return <section className="recent-looks" aria-label="Recent saved looks"><div className="recent-heading"><h3>Recent looks</h3><div><span>{items.length} saved</span><button className="icon-button" aria-label="Scroll to previous looks" disabled={items.length<2} onClick={()=>scroll(-1)}><ChevronLeft size={17}/></button><button className="icon-button" aria-label="Scroll to next looks" disabled={items.length<2} onClick={()=>scroll(1)}><ChevronRight size={17}/></button></div></div><div className="recent-strip" ref={strip} role="list">{items.map(item=><article className={`recent-look ${currentId===item.id?'recent-current':''}`} role="listitem" key={item.id}><button className="recent-image" aria-label={`View ${item.garment_names.join(' + ')||'your own garment'} from ${dateLabel(item.created_at)}`} aria-pressed={currentId===item.id} onClick={()=>onSelect(item)}><img src={item.after} alt={item.garment_names.join(' + ')||'Your own garment preview'}/><span>{dateLabel(item.created_at)}</span></button>{onToggle&&<button className={`recent-checkbox ${selection.includes(item.id)?'selected':''}`} aria-label={`Select look from ${dateLabel(item.created_at)}`} aria-pressed={selection.includes(item.id)} onClick={()=>onToggle(item.id)}>{selection.includes(item.id)&&<Check size={13}/>}</button>}</article>)}</div><p>Scroll or swipe to explore your saved looks.</p></section>
}
