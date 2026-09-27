'use strict';
const assert=require('node:assert/strict');
require('/app/.build/next/server/app/api/compression/preview/route.js');
const runtime=require('/app/.build/next/server/webpack-runtime.js');
(async()=>{
 const rtk=await runtime(653846);
 const config={enabled:true,intensity:'minimal',applyToToolResults:true,applyToCodeBlocks:false,applyToAssistantMessages:false,enabledFilters:['generic-output'],maxLinesPerResult:120,maxCharsPerResult:12000,rawOutputRetention:'never',enableGrouping:false,enableRenderers:false};
 const log='progress: completed check\n'.repeat(160)+'ERROR E_RTK_ADAPTER /tmp/a.py:12\nFAILED test_checksum\n```python\ndef checksum():\n    return "한글"\n```';
 const envelope=JSON.stringify({output:log,exit_code:1,error:'checksum mismatch',cwd:'/tmp',full_output_path:'/tmp/raw.log',metadata:{flag:true,id:9007199254740991}});
 const result=rtk.sy(envelope,{command:'pytest',config});assert(result.compressed);
 const before=JSON.parse(envelope),after=JSON.parse(result.text);
 const {output:oldOutput,...oldMeta}=before,{output:newOutput,...newMeta}=after;
 assert.deepEqual(newMeta,oldMeta);assert(newOutput.includes('ERROR E_RTK_ADAPTER'));assert(newOutput.includes('FAILED test_checksum'));assert(newOutput.includes('```python\ndef checksum():\n    return "한글"\n```'));
 const fixtures=[
  {name:'openai',body:{model:'test',messages:[{role:'assistant',content:null,tool_calls:[{id:'c1',type:'function',function:{name:'terminal',arguments:'{"command":"pytest"}'}}]},{role:'tool',tool_call_id:'c1',content:envelope}]},extract:b=>b.messages[1].content},
  {name:'anthropic',body:{model:'test',messages:[{role:'assistant',content:[{type:'tool_use',id:'c1',name:'terminal',input:{command:'pytest'}}]},{role:'user',content:[{type:'tool_result',tool_use_id:'c1',content:envelope}]}]},extract:b=>b.messages[1].content[0].content},
  {name:'responses',body:{model:'test',input:[{type:'function_call',call_id:'c1',name:'terminal',arguments:'{"command":"pytest"}'},{type:'function_call_output',call_id:'c1',output:envelope}]},extract:b=>b.input[1].output}
 ];
 for(const f of fixtures){const untouched=JSON.stringify(f.body);const r=rtk.yA(f.body,{config});assert(r.compressed,f.name);assert.equal(JSON.stringify(f.body),untouched);const content=f.extract(r.body);assert.equal(content,result.text);const restored=structuredClone(r.body);if(f.name==='openai')restored.messages[1].content=envelope;else if(f.name==='anthropic')restored.messages[1].content[0].content=envelope;else restored.input[1].output=envelope;assert.deepEqual(restored,f.body);console.log(f.name+': envelope compressed, IDs/metadata unchanged')}
 console.log(JSON.stringify({originalTokens:result.originalTokens,compressedTokens:result.compressedTokens,techniques:result.techniquesUsed}));
})().catch(e=>{console.error(e);process.exitCode=1});
