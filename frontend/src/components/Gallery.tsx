import { useEffect, useRef, useState } from 'react';
import { Images, Download, Trash2, QrCode, LockKeyhole, Plus } from 'lucide-react';
import type { GalleryItem } from '../types';
import { api, ApiError, errorMessage } from '../lib/api';
import { removeGallery, captureGallerySession } from '../lib/gallery';
import { selectedLook } from '../lib/resultSelection';
import { AsyncViewGate } from '../lib/viewLifecycle';
import type { ShareViewToken } from '../lib/viewLifecycle';
import { downloadImage } from '../lib/images';
import { dateLabel, Empty, Modal, Notice, Spinner } from './Common';
import RecentLooks from './RecentLooks';
import ShareDialog from './ShareDialog';

export default function Gallery({items,max,onRefresh,onCreate}:{items:GalleryItem[];max:number;onRefresh:()=>Promise<void>;onCreate:()=>void}){
 const [selection,setSelection]=useState<string[]>([]);const [currentId,setCurrentId]=useState<string|null>(null);const [sharing,setSharing]=useState<GalleryItem|null>(null);const [confirm,setConfirm]=useState<string[]>([]);const [busy,setBusy]=useState(false);const [error,setError]=useState('');
 const current=selectedLook(items,currentId);const shareGate=useRef(new AsyncViewGate());const mounted=useRef(true);const [shareToken,setShareToken]=useState<ShareViewToken|null>(null);
 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;shareGate.current.close()}},[]);
 function openShare(item:GalleryItem){setShareToken(shareGate.current.open(item.id));setSharing(item)}
 function closeShare(){shareGate.current.close();setShareToken(null);setSharing(null)}
 function toggle(id:string){setSelection(previous=>previous.includes(id)?previous.filter(value=>value!==id):[...previous,id])}
 async function deleteItems(){
  setBusy(true);setError('');
  try{
   const sessionCurrent=captureGallerySession();const canContinue=()=>mounted.current&&sessionCurrent();const deleting=confirm;
   for(const id of deleting){
    if(!canContinue())return;
    const item=items.find(item=>item.id===id);
    if(item?.share_id){try{await api(`/api/shares/${item.share_id}`,{method:'DELETE'})}catch(err){if(!(err instanceof ApiError)||err.status!==404)throw err}if(!canContinue())return}
    try{await api(`/api/tryon/results/${id}`,{method:'DELETE'})}catch(err){if(!(err instanceof ApiError)||err.status!==404)throw err}
   }
   if(!canContinue())return;
   await removeGallery(deleting);if(!canContinue())return;
   setSelection(previous=>previous.filter(id=>!deleting.includes(id)));setConfirm([]);await onRefresh();
  }catch(err){if(mounted.current)setError(errorMessage(err))}
  finally{if(mounted.current)setBusy(false)}
 }

 return <><div className="page-title-row"><div><span className="eyebrow subtle">A COLLECTION OF POSSIBILITIES</span><h1>Your looks, your story.</h1><p className="page-subtitle">A private edit of everything you’ve tried on.</p></div><button className="button primary" onClick={onCreate}><Plus size={17}/> Create a look</button></div><div className="gallery-toolbar"><div className="gallery-storage"><span>{items.length}<span className="muted"> / {max} looks</span></span><div className="storage-meter"><span style={{width:`${Math.min(100,items.length/max*100)}%`}}/></div></div><div className="gallery-tool-buttons">{items.length>0&&<button className="text-button" onClick={()=>setSelection(selection.length===items.length?[]:items.map(item=>item.id))}>{selection.length===items.length?'Clear selection':'Select all'}</button>}{selection.length>0&&<><button className="button secondary compact" onClick={()=>{for(const id of selection){const item=items.find(item=>item.id===id);if(item)downloadImage(item.after,`stylereel-${id}.jpg`)}}}><Download size={16}/> Download ({selection.length})</button><button className="button danger-outline compact" onClick={()=>setConfirm(selection)}><Trash2 size={16}/> Delete</button></>}</div></div>{error&&<Notice tone="error">{error}</Notice>}
 {current?<section className="result-layout gallery-result"><div className="panel result-photo"><div className="panel-heading"><span className="eyebrow">YOUR SAVED LOOK</span><span className="small-label">{dateLabel(current.created_at)}</span></div><div className="generated-image"><img src={current.after} alt={`${current.garment_names.join(' + ')||'Your own garment'} generated preview`}/></div><RecentLooks items={items} currentId={current.id} onSelect={item=>setCurrentId(item.id)} selection={selection} onToggle={toggle}/></div><div className="result-details"><span className="eyebrow subtle">YOUR STYLE REEL</span><h2>{current.garment_names.join(' + ')||'Your own garment'}</h2><p>{current.provider} · {current.model}</p>{(current.experimental||current.workflow==='holding')&&<span className="experimental-preview-label">Experimental preview</span>}<div className="result-actions"><button className="button primary" aria-label="Download look" onClick={()=>downloadImage(current.after,`stylereel-${current.id}.jpg`)}><Download size={17}/> Download look</button><button className="button secondary" aria-label="Share look with QR" onClick={()=>openShare(current)}><QrCode size={17}/> Share with QR</button><button className="text-button danger-text" aria-label="Delete look" onClick={()=>setConfirm([current.id])}><Trash2 size={16}/> Delete this look</button></div><p className="muted small">AI previews may differ from real fit, drape, colour, and fine details.</p></div></section>:<div className="panel"><Empty icon={<Images size={36}/>} title="Your first look is waiting">Create a preview in the studio, and it will appear here. Your collection stays encrypted on this device.</Empty><div className="empty-cta"><button className="button primary" onClick={onCreate}><Plus size={16}/> Step into the studio</button></div></div>}
 <div className="gallery-privacy"><LockKeyhole size={16}/><p>Encrypted for your account, saved on this device. Signing out locks your gallery. Clearing browser data removes these looks.</p></div>
 {sharing&&shareToken&&<ShareDialog item={sharing} onClose={closeShare} onUpdate={item=>{if(shareGate.current.accepts(shareToken))setSharing(item);if(mounted.current)void onRefresh().catch(err=>{if(mounted.current)setError(errorMessage(err))})}}/>}{confirm.length>0&&<Modal title={`Delete ${confirm.length===1?'this look':`${confirm.length} looks`}?`} onClose={()=>{if(!busy)setConfirm([])}}><p className="muted">This removes the saved {confirm.length===1?'look':'looks'} from this device and deletes available server results and share links. Download anything you want to keep first.</p><div className="modal-actions"><button className="button secondary" disabled={busy} onClick={()=>setConfirm([])}>Keep {confirm.length===1?'look':'looks'}</button><button className="button danger" onClick={deleteItems} disabled={busy}>{busy?<Spinner label="Deleting"/>:<><Trash2 size={16}/> Delete</>}</button></div></Modal>}</>
}
