import { useEffect, useState } from 'react';
import { Check, ExternalLink, Images, Pencil, Plus, Search, Shirt, Trash2, X } from 'lucide-react';
import type { CatalogLabel, CatalogLabels, Category, Garment, Slot } from '../types';
import { api, errorMessage, patch, post } from '../lib/api';
import { garmentPhotos, MAX_GARMENT_PHOTOS, validateGarmentPhotos } from '../lib/catalog';
import { prepareCatalogPhotos } from '../lib/catalogUpload';
import { Empty, Modal, Notice, ProtectedImage, Spinner } from './Common';
import GarmentPhotos from './GarmentPhotos';

type LabelKind='type'|'store'|'brand';
const labelTitles:Record<LabelKind,string>={type:'Type',store:'Store Name',brand:'Brand Name'};
const emptyForm={name:'',description:'',category_id:'',store_id:'',brand_id:'',source_url:'',license:'',attribution:'',active:true};
const emptyLabel={name:'',slot:'full' as Slot,experimental:false};

export default function CatalogAdmin({categories,garments,labels,onRefresh}:{categories:Category[];garments:Garment[];labels:CatalogLabels;onRefresh:()=>Promise<void>}){
 const [editing,setEditing]=useState<Garment|'new'|null>(null);const [search,setSearch]=useState('');const [form,setForm]=useState(emptyForm);const [files,setFiles]=useState<File[]>([]);const [deleting,setDeleting]=useState<Garment|null>(null);const [viewing,setViewing]=useState<Garment|null>(null);const [error,setError]=useState('');const [busy,setBusy]=useState(false);const [labelKind,setLabelKind]=useState<LabelKind|null>(null);const [labelForm,setLabelForm]=useState(emptyLabel);const [savingLabel,setSavingLabel]=useState(false);
 function edit(garment:Garment|'new'){
  setError('');setEditing(garment);setFiles([]);setLabelKind(null);setLabelForm(emptyLabel);
  setForm(garment==='new'?{...emptyForm,category_id:categories[0]?.id??''}:{name:garment.name,description:garment.description??'',category_id:garment.category_id,store_id:garment.store_id??'',brand_id:garment.brand_id??'',source_url:garment.source_url??'',license:garment.license??'',attribution:garment.attribution??'',active:garment.active});
 }
 function beginLabel(kind:LabelKind){setLabelKind(kind);setLabelForm(emptyLabel);setError('')}
 async function addLabel(){
  if(!labelKind||savingLabel)return;const name=labelForm.name.trim();if(!name){setError(`Enter a ${labelTitles[labelKind]} label.`);return}
  setSavingLabel(true);setError('');
  try{
   const label=labelKind==='type'?await post<Category>('/api/admin/categories',{...labelForm,name}):await post<CatalogLabel>('/api/admin/catalog/labels',{kind:labelKind,name});
   await onRefresh();if(editing)setForm(previous=>({...previous,[labelKind==='type'?'category_id':`${labelKind}_id`]:label.id}));setLabelKind(null);setLabelForm(emptyLabel);
  }catch(err){setError(errorMessage(err))}finally{setSavingLabel(false)}
 }
 async function save(event:React.FormEvent){
  event.preventDefault();if(labelKind){setError('Save or cancel the new label before saving the piece.');return}setBusy(true);setError('');
  try{
   if(editing==='new'){
    const issue=validateGarmentPhotos(files);if(issue)throw new Error(issue);
    const prepared=await prepareCatalogPhotos(files);const data=new FormData();prepared.files.forEach(file=>data.append('files',file));Object.entries(form).forEach(([key,value])=>{if(value!==''||!['store_id','brand_id'].includes(key))data.set(key,String(value))});
    await api('/api/admin/garments',{method:'POST',body:data});
   }else if(editing){await patch(`/api/garments/${editing.id}`,{...form,store_id:form.store_id||null,brand_id:form.brand_id||null})}
   await onRefresh();setEditing(null);setFiles([]);
  }catch(err){setError(errorMessage(err))}finally{setBusy(false)}
 }
 function choosePhotos(next:FileList|null){const picked=Array.from(next??[]);if(!picked.length)return;const issue=validateGarmentPhotos(picked);if(issue){setError(issue);return}setError('');setFiles(picked)}
 const labelEditor=labelKind&&<fieldset className="inline-label-editor" disabled={savingLabel||busy}><legend>Add a new {labelTitles[labelKind]} label</legend><label>New {labelTitles[labelKind]}<input maxLength={120} value={labelForm.name} onChange={event=>setLabelForm({...labelForm,name:event.target.value})} onKeyDown={event=>{if(event.key==='Enter'){event.preventDefault();void addLabel()}}}/></label>{labelKind==='type'&&<><label>Body coverage<select value={labelForm.slot} onChange={event=>setLabelForm({...labelForm,slot:event.target.value as Slot})}><option value="upper">Upper body</option><option value="lower">Lower body</option><option value="full">Complete outfit / full body</option></select></label><label className="checkbox-label"><input type="checkbox" checked={labelForm.experimental} onChange={event=>setLabelForm({...labelForm,experimental:event.target.checked})}/> Label previews as experimental</label></>}<div className="modal-actions"><button type="button" className="button secondary compact" onClick={()=>setLabelKind(null)}>Cancel label</button><button type="button" className="button primary compact" onClick={()=>void addLabel()} disabled={!labelForm.name.trim()}>{savingLabel?<Spinner label="Saving label"/>:<><Check size={15}/> Save label</>}</button></div></fieldset>;
 return <section className="panel">
  <div className="panel-heading"><div><h3>Pieces with possibility</h3><p className="muted small">Dress photos, types, stores, and brands for your collection.</p></div><div className="row-actions"><button className="button secondary compact" onClick={()=>beginLabel('type')}><Plus size={15}/> Type</button><button className="button primary compact" onClick={()=>edit('new')}><Plus size={15}/> Garment</button></div></div>
  <div className="search-input admin-search"><Search size={17}/><input aria-label="Search collection" placeholder="Search the collection…" value={search} onChange={event=>setSearch(event.target.value)}/></div>
  {error&&!editing&&!labelKind&&!deleting&&<Notice tone="error">{error}</Notice>}
  <div className="table-wrap"><table><thead><tr><th>Garment</th><th>Type</th><th>Store Name</th><th>Brand Name</th><th>Visibility</th><th>Actions</th></tr></thead><tbody>{garments.filter(garment=>garment.name.toLowerCase().includes(search.toLowerCase())).map(garment=><tr key={garment.id}><td><div className="catalog-cell"><ProtectedImage src={garment.thumbnail_url||garment.image_url} alt={garment.name}/><div><strong>{garment.name}</strong><span className="table-secondary">{garment.description}</span><button className="text-button compact" onClick={()=>setViewing(garment)}><Images size={13}/> {garmentPhotos(garment).length} {garmentPhotos(garment).length===1?'photo':'photos'}</button></div></div></td><td>{categories.find(category=>category.id===garment.category_id)?.name||'Uncategorised'}</td><td>{labels.stores.find(label=>label.id===garment.store_id)?.name||'—'}</td><td>{labels.brands.find(label=>label.id===garment.brand_id)?.name||'—'}</td><td><button className={`status-pill status-toggle ${garment.active?'':'status-off'}`} disabled={busy} onClick={async()=>{setBusy(true);setError('');try{await patch(`/api/garments/${garment.id}`,{active:!garment.active});await onRefresh()}catch(err){setError(errorMessage(err))}finally{setBusy(false)}}}>{garment.active?'Active':'Hidden'}</button></td><td><div className="row-actions"><button className="icon-button" aria-label={`Edit ${garment.name}`} onClick={()=>edit(garment)}><Pencil size={17}/></button><button className="icon-button danger-text" aria-label={`Delete ${garment.name}`} onClick={()=>{setDeleting(garment);setError('')}}><Trash2 size={17}/></button></div></td></tr>)}</tbody></table>{!garments.length&&<Empty icon={<Shirt size={30}/>} title="A collection waiting to happen">Add your first dress and its photos.</Empty>}</div>
  {editing&&<Modal wide title={editing==='new'?'Add a new piece':'Edit this piece'} onClose={()=>{if(!busy&&!savingLabel){setEditing(null);setLabelKind(null)}}}><form className="form-stack" onSubmit={save}>
   {editing==='new'?<><label>Dress photos<input type="file" accept="image/jpeg,image/png,image/webp,image/heic,image/heif,.heic,.heif" multiple required={!files.length} disabled={busy||savingLabel} onChange={event=>choosePhotos(event.target.files)}/><span className="field-help">Add 1–{MAX_GARMENT_PHOTOS} photos, up to 12 MB each. Large photos are resized automatically; the complete upload must fit 28 MB. Photos on a model are welcome.</span></label><DraftPhotos files={files} onRemove={index=>setFiles(previous=>previous.filter((_,position)=>position!==index))} disabled={busy||savingLabel}/></>:<div><p className="small muted">Saved dress references</p><GarmentPhotos garment={editing}/></div>}
   <label>Name<input required maxLength={120} disabled={busy||savingLabel} value={form.name} onChange={event=>setForm({...form,name:event.target.value})}/></label>
   <label>Description<textarea rows={2} maxLength={2000} disabled={busy||savingLabel} value={form.description} onChange={event=>setForm({...form,description:event.target.value})}/></label>
   <div className="catalog-label-fields"><LabelSelect title="Type" value={form.category_id} choices={categories} onChange={value=>setForm({...form,category_id:value})} onAdd={()=>beginLabel('type')} disabled={busy||savingLabel} required/><LabelSelect title="Store Name" value={form.store_id} choices={labels.stores} onChange={value=>setForm({...form,store_id:value})} onAdd={()=>beginLabel('store')} disabled={busy||savingLabel}/><LabelSelect title="Brand Name" value={form.brand_id} choices={labels.brands} onChange={value=>setForm({...form,brand_id:value})} onAdd={()=>beginLabel('brand')} disabled={busy||savingLabel}/></div>
   {labelEditor}
   <details className="catalog-source-fields"><summary>Photo attribution and source (optional)</summary><div className="form-columns"><label>Licence<input maxLength={200} placeholder="e.g. CC BY 4.0" value={form.license} onChange={event=>setForm({...form,license:event.target.value})}/></label><label>Attribution<input maxLength={1000} placeholder="Photographer / creator" value={form.attribution} onChange={event=>setForm({...form,attribution:event.target.value})}/></label></div><label>Source URL<input type="url" maxLength={2000} placeholder="https://…" value={form.source_url} onChange={event=>setForm({...form,source_url:event.target.value})}/></label></details>
   <label className="checkbox-label"><input type="checkbox" disabled={busy||savingLabel} checked={form.active} onChange={event=>setForm({...form,active:event.target.checked})}/> Visible in the collection</label>{error&&<Notice tone="error">{error}</Notice>}
   <button className="button primary full-width" disabled={busy||savingLabel||!!labelKind}>{busy?<Spinner label="Saving piece"/>:<><Check size={16}/> Save piece</>}</button>
  </form></Modal>}
  {labelKind&&!editing&&<Modal title={`Add a ${labelTitles[labelKind]} label`} onClose={()=>{if(!savingLabel)setLabelKind(null)}}>{labelEditor}{error&&<Notice tone="error">{error}</Notice>}</Modal>}
  {viewing&&<Modal title={viewing.name} onClose={()=>setViewing(null)}><GarmentPhotos garment={viewing}/>{viewing.source_url&&<a className="text-button" href={viewing.source_url} target="_blank" rel="noreferrer">Source &amp; licence <ExternalLink size={14}/></a>}</Modal>}
  {deleting&&<Modal title="Remove this piece?" onClose={()=>{if(!busy)setDeleting(null)}}><p className="muted">Remove {deleting.name} and its dress photos from the collection. Previously generated looks remain in their owners’ galleries.</p>{error&&<Notice tone="error">{error}</Notice>}<div className="modal-actions"><button className="button secondary" onClick={()=>setDeleting(null)} disabled={busy}>Keep piece</button><button className="button danger" disabled={busy} onClick={async()=>{setBusy(true);try{await api(`/api/garments/${deleting.id}`,{method:'DELETE'});await onRefresh();setDeleting(null)}catch(err){setError(errorMessage(err))}finally{setBusy(false)}}}>{busy?<Spinner/>:'Remove piece'}</button></div></Modal>}
 </section>
}

function LabelSelect({title,value,choices,onChange,onAdd,disabled,required=false}:{title:string;value:string;choices:CatalogLabel[];onChange:(value:string)=>void;onAdd:()=>void;disabled:boolean;required?:boolean}){
 return <div className="catalog-label-field"><label>{title}<select value={value} required={required} disabled={disabled} onChange={event=>onChange(event.target.value)}><option value="">{required?'Choose a type':'Not specified'}</option>{choices.map(label=><option key={label.id} value={label.id}>{label.name}</option>)}</select></label><button type="button" className="text-button" disabled={disabled} onClick={onAdd}><Plus size={13}/> Add new {title}</button></div>
}
function DraftPhotos({files,onRemove,disabled}:{files:File[];onRemove:(index:number)=>void;disabled:boolean}){
 const [urls,setUrls]=useState<string[]>([]);useEffect(()=>{const next=files.map(file=>URL.createObjectURL(file));setUrls(next);return()=>next.forEach(url=>URL.revokeObjectURL(url))},[files]);
 return files.length?<div className="dress-photo-drafts" aria-label="Selected dress photos">{files.map((file,index)=><div className="dress-photo-draft" key={`${file.name}-${index}`}><img src={urls[index]} alt={`Dress reference ${index+1}`} onError={event=>{event.currentTarget.hidden=true}}/><span>{index+1}. {file.name}</span><button type="button" className="icon-button" disabled={disabled} aria-label={`Remove dress photo ${index+1}`} onClick={()=>onRemove(index)}><X size={15}/></button></div>)}</div>:null;
}
