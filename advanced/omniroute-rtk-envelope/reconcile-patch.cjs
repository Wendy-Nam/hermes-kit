'use strict';
// The pinned upstream already supports per-request capability snapshots. Reuse
// one per reconciliation run instead of re-reading every catalog for each row.
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const ROOT='/app/.build/next/server/chunks';
const before='}(a);return i(b,{getCatalogWindow:(a,b)=>(0,f.w8)({provider:a,model:b},{persistedOverrides:!1}).contextWindow';
const after='}(a);const __hermesReconcileSnapshot=(await c(838997)).m();return i(b,{getCatalogWindow:(a,b)=>(0,f.w8)({provider:a,model:b},{persistedOverrides:!1},__hermesReconcileSnapshot).contextWindow';
function patch(root=ROOT){
 const files=fs.readdirSync(root).filter(f=>f.endsWith('.js')).map(f=>path.join(root,f));
 // Patch the Node standalone startup module observed in this pinned build.
 // Other Next build targets contain independent copies with different imports.
 const candidates=files.map(file=>({file,text:fs.readFileSync(file,'utf8')})).filter(x=>x.text.includes('488705:(a,b,c)=>')&&x.text.includes('runContextWindowReconcile:'));
 if(candidates.length!==1)throw Error('Unsupported OmniRoute reconcile module count');
 const {file,text}=candidates[0];
 // This is a capability-snapshot API in the pinned upstream, not a private cache.
 if(!files.some(f=>fs.readFileSync(f,'utf8').includes('838997:(a,b,c)=>')))
  throw Error('Unsupported OmniRoute build: capability snapshot module missing');
 if(text.includes(after)){
  if(text.includes(before)||text.split(after).length!==2)throw Error('Partial reconcile snapshot patch');
  new vm.Script(text,{filename:file});return file;
 }
 if(text.includes('__hermesReconcileSnapshot')||text.split(before).length!==2)
  throw Error('Unsupported OmniRoute build: reconcile anchor missing or ambiguous');
 const result=text.replace(before,after);new vm.Script(result,{filename:file});fs.writeFileSync(file,result);return file;
}
if(require.main===module)console.log('OmniRoute per-run reconciliation snapshot patched: '+path.basename(patch(process.argv[2])));
module.exports={patch,before,after};
