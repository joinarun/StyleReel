import { useEffect, useRef, useState } from 'react';
import { QRCodeSVG } from 'qrcode.react';
import { Copy, Link, Unlink, ShieldCheck } from 'lucide-react';
import type { GalleryItem, Share, Upload } from '../types';
import { api, post, errorMessage } from '../lib/api';
import { dataUrlToBlob } from '../lib/images';
import { Modal, Notice, Spinner } from './Common';
import { saveGallery, captureGallerySession } from '../lib/gallery';
export default function ShareDialog({item,onClose,onUpdate}:{item:GalleryItem;onClose:()=>void;onUpdate:(item:GalleryItem)=>void}){const [share,setShare]=useState<Share|null>(item.share_id&&item.share_url&&item.share_expires_at&&Date.parse(item.share_expires_at)>Date.now()?{id:item.share_id,url:item.share_url,expires_at:item.share_expires_at}:null);const [error,setError]=useState('');const [busy,setBusy]=useState(false);const [copied,setCopied]=useState(false);const [now,setNow]=useState(Date.now());useEffect(()=>{const id=setInterval(()=>setNow(Date.now()),1000);return()=>clearInterval(id)},[]);const mounted=useRef(true);useEffect(()=>{mounted.current=true;return()=>{mounted.current=false}},[]);const remaining=share?Math.max(0,Math.ceil((Date.parse(share.expires_at)-now)/1000)):0;
 async function create(){
  setBusy(true);setError('');
  try{
   const sessionCurrent=captureGallerySession();const canContinue=()=>mounted.current&&sessionCurrent();
   let result:Share;
   try{result=await post<Share>('/api/shares',{result_id:item.id})}
   catch(error){
    if(!canContinue())return;
    if(!(error instanceof Error)||!('status'in error)||![404,410].includes((error as {status:number}).status))throw error;
    const photo=await dataUrlToBlob(item.after);if(!canContinue())return;
    const form=new FormData();form.set('file',photo,'styled-photo.jpg');form.set('consent','true');form.set('purpose','share');
    const upload=await api<Upload>('/api/uploads',{method:'POST',body:form});if(!canContinue())return;
    result=await post<Share>('/api/shares',{upload_id:upload.id});
   }
   if(!canContinue())return;
   const updated={...item,share_id:result.id,share_url:result.url,share_expires_at:result.expires_at};
   await saveGallery(updated);if(!canContinue())return;
   onUpdate(updated);setShare(result);
  }catch(err){if(mounted.current)setError(errorMessage(err))}
  finally{if(mounted.current)setBusy(false)}
 }
 async function revoke(){
  if(!share)return;setBusy(true);
  try{
   const sessionCurrent=captureGallerySession();const canContinue=()=>mounted.current&&sessionCurrent();
   await api(`/api/shares/${share.id}`,{method:'DELETE'});if(!canContinue())return;
   const updated={...item,share_id:undefined,share_url:undefined,share_expires_at:undefined};
   await saveGallery(updated);if(!canContinue())return;
   onUpdate(updated);setShare(null);
  }catch(err){if(mounted.current)setError(errorMessage(err))}
  finally{if(mounted.current)setBusy(false)}
 }
 const url=share?new URL(share.url,location.origin).href:'';
 return <Modal title="A look worth sharing" onClose={onClose}><p className="muted">A private, temporary link to this styled photo. Anyone with the link can view and download it.</p>{error&&<Notice tone="error">{error}</Notice>}{share&&remaining>0?<><div className="qr-frame"><QRCodeSVG value={url} size={208} level="M" marginSize={1}/></div><div className="share-expiry"><ShieldCheck size={16}/> Expires in {Math.floor(remaining/60)}:{String(remaining%60).padStart(2,'0')}</div><div className="share-link"><input aria-label="Temporary share link" readOnly value={url}/><button className="icon-button" aria-label="Copy share link" onClick={async()=>{try{await navigator.clipboard.writeText(url);setCopied(true)}catch{setError('Select the link and copy it manually.')}}}><Copy size={18}/></button></div>{copied&&<p className="small success-text">Link copied.</p>}<button className="button secondary full-width" onClick={revoke} disabled={busy}>{busy?<Spinner/>:<><Unlink size={16}/> Revoke link now</>}</button></>:<><div className="share-explainer"><Link size={32}/><p>The link expires after 15 minutes. You can revoke it sooner.</p></div><button className="button primary full-width" onClick={create} disabled={busy}>{busy?<Spinner label="Creating secure link"/>:<><Link size={16}/> Create 15-minute link</>}</button></>}<p className="muted small privacy-note">Creating a link uploads this result to private temporary storage. Source photos are never included.</p></Modal>}
