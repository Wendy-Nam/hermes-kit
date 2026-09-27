'use strict';
// Execute the actual shipped resolver and reconciler against an isolated DB.
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const home=fs.mkdtempSync(path.join(os.tmpdir(),'reconcile-runtime-'));
process.env.DATA_DIR=home;process.env.CONTEXT_WINDOW_RECONCILE_INTERVAL='0';
require('/app/.build/next/server/app/api/compression/preview/route.js');
const runtime=require('/app/.build/next/server/webpack-runtime.js');
(async()=>{
 await runtime.e(88705);await runtime.e(89935);
 const reconciler=await runtime(488705),resolver=await runtime(789935),snapshots=await runtime(838997),catalog=await runtime(281653),database=await runtime(33653);
 const db=database.getDbInstance();
 const provider='openai',sameModel='gpt-4o',newModel='hermes-kit-synthetic-window',manualModel='hermes-kit-synthetic-manual';
 const baseline=resolver.w8({provider,model:sameModel},{persistedOverrides:false}).contextWindow;
 assert(Number.isInteger(baseline)&&baseline>0,'fixture needs a known catalog context window');
 function seed(window){
  db.prepare("INSERT OR REPLACE INTO key_value(namespace,key,value) VALUES('syncedAvailableModels',?,?)").run(provider+':synthetic',JSON.stringify([{id:sameModel,contextWindow:baseline},{id:newModel,contextWindow:window},{id:manualModel,contextWindow:32768}]));
 }
 seed(16384);
 db.prepare("INSERT OR REPLACE INTO model_context_overrides(provider,model_id,real_context,source) VALUES(?,?,?,?)").run(provider,sameModel,1024,'auto:discovery');
 db.prepare("INSERT OR REPLACE INTO model_context_overrides(provider,model_id,real_context,source) VALUES(?,?,?,?)").run(provider,manualModel,7777,'manual');
 const snapshot=snapshots.m();
 for(const model of [sameModel,newModel,manualModel])assert.equal(resolver.w8({provider,model},{persistedOverrides:false},snapshot).contextWindow,resolver.w8({provider,model},{persistedOverrides:false}).contextWindow);
 const first=await reconciler.runContextWindowReconcile();
 const get=model=>db.prepare('SELECT real_context,source FROM model_context_overrides WHERE provider=? AND model_id=?').get(provider,model);
 assert.equal(get(sameModel),undefined,'redundant automatic override must be removed');
 assert.equal(get(newModel).real_context,16384);assert.equal(get(newModel).source,'auto:discovery');
 assert.equal(get(manualModel).real_context,7777);assert.equal(get(manualModel).source,'manual');
 seed(24576);
 // Invalidate the upstream synced catalog cache, just as its writer does.
 const synced=await runtime(118027);synced.uo();
 const second=await reconciler.runContextWindowReconcile();
 assert.equal(get(newModel).real_context,24576,'a later run must see fresh discovery');
 assert.equal(get(manualModel).real_context,7777);
 console.log(JSON.stringify({snapshotWindowsEquivalent:true,manualOverridePreserved:true,redundantAutoOverrideRemoved:true,nextRunFresh:true,first,second}));
 process.exit(0);
})().catch(error=>{console.error(error);process.exit(1)});
