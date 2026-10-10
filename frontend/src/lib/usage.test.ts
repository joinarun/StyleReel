import { describe, expect, it } from 'vitest';
import { usageCsv, usageTokens } from './usage';
import { validatePasswordChange } from './password';
describe('reported provider token metadata',()=>{
 it('maps actual Google usage instead of inventing missing normalized fields',()=>expect(usageTokens({id:'attempt',reported_usage:{promptTokenCount:321,candidatesTokenCount:1290,thoughtsTokenCount:108}})).toEqual({input:321,output:1290,thinking:108}));
 it('preserves measured zero tokens and falls back to explicitly recorded normalized counts',()=>{expect(usageTokens({id:'attempt',reported_usage:{promptTokenCount:0,candidatesTokenCount:0}})).toMatchObject({input:0,output:0});expect(usageTokens({id:'attempt',input_tokens:3,output_tokens:7})).toMatchObject({input:3,output:7});expect(usageTokens({id:'attempt'})).toEqual({input:undefined,output:undefined,thinking:undefined})});
 it('exports reported tokens and quotes event metadata correctly',()=>{const csv=usageCsv([{id:'attempt',model:'model "one"',reported_usage:{promptTokenCount:321,candidatesTokenCount:1290,thoughtsTokenCount:108}}]);expect(csv).toContain('"321","1290","108"');expect(csv).toContain('"model ""one"""');expect(csv.split('\r\n')).toHaveLength(2)});
});
describe('voluntary password changes',()=>{
 it('rejects mismatched confirmations',()=>expect(validatePasswordChange('new-password-123','different-password-123','old-password-123')).toMatch(/do not match/));
 it('rejects reusing the current password',()=>expect(validatePasswordChange('old-password-123','old-password-123','old-password-123')).toMatch(/different password/));
 it('allows a valid confirmed new password and enforces backend length bounds',()=>{expect(validatePasswordChange('new-password-123','new-password-123','old-password-123')).toBeNull();expect(validatePasswordChange('short','short')).toMatch(/at least/);expect(validatePasswordChange('x'.repeat(129),'x'.repeat(129))).toMatch(/no more/)});
});
