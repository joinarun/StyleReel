import { describe, expect, it } from 'vitest';
import { estimatedCalls, estimateCost, isExperimental, selectGarment } from './selection';
import type { Category, Garment, Provider } from '../types';
const categories:Category[]=[{id:'tops',name:'Tops',slot:'upper'},{id:'bottoms',name:'Bottoms',slot:'lower'},{id:'sarees',name:'Sarees',slot:'full',experimental:true}];
const make=(id:string,category_id:string):Garment=>({id,name:id,category_id,active:true,image_url:'/api/image'});
const garments=[make('shirt','tops'),make('blouse','tops'),make('jeans','bottoms'),make('saree','sarees')];
const google:Provider={id:'google',label:'Google',configured:true,status:'configured',models:['pro'],supports_holding:true,supports_multi:true,prompt_supported:true,estimated_cost_per_call_usd:0.25};
describe('compatible outfit selection',()=>{
 it('combines one upper-body and one lower-body garment',()=>expect(selectGarment(['shirt'],garments[2],garments,categories)).toEqual(['shirt','jeans']));
 it('replaces another garment in the same body slot',()=>expect(selectGarment(['shirt','jeans'],garments[1],garments,categories)).toEqual(['jeans','blouse']));
 it('full-body outfits replace all separate garments',()=>expect(selectGarment(['shirt','jeans'],garments[3],garments,categories)).toEqual(['saree']));
 it('selecting a separate garment clears a full-body selection',()=>expect(selectGarment(['saree'],garments[0],garments,categories)).toEqual(['shirt']));
 it('toggling a garment removes it without changing other pieces',()=>expect(selectGarment(['shirt','jeans'],garments[0],garments,categories)).toEqual(['jeans']));
 it('does not select a garment with an unknown body slot',()=>expect(selectGarment(['shirt'],make('other','missing'),garments,categories)).toEqual(['shirt']));
 it('labels traditional categories experimental',()=>{expect(isExperimental(['saree'],garments,categories)).toBe(true);expect(isExperimental(['shirt'],garments,categories)).toBe(false)});
});
describe('pre-submit provider estimates',()=>{
 it('charges one multi-garment call for a native provider',()=>expect(estimatedCalls('catalog',2,google)).toBe(1));
 it('shows two calls for sequential upper/lower outfits',()=>expect(estimatedCalls('catalog',2,{...google,supports_multi:false})).toBe(2));
 it('counts held-garment visibility checks',()=>expect(estimatedCalls('holding',0,google)).toBe(2));
 it('uses model metadata and never invents a missing estimate',()=>{expect(estimateCost(2,google,'pro')).toBe(0.5);expect(estimateCost(1,{...google,model_costs:{pro:0.137}},'pro')).toBe(0.137);expect(estimateCost(1,undefined,'pro')).toBeNull()});
});
