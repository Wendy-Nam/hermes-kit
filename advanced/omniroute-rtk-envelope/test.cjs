const test = require('node:test'), assert = require('node:assert/strict');
const adapt = require('./envelope.cjs');
const estimate = s=>Math.ceil(s.length/4);
const compress = s=>({text:s.replace(/(?:progress\n){3,}/g,'[progress repeated]\n'),compressed:/(?:progress\n){3,}/.test(s),techniquesUsed:['dedup'],rulesApplied:[]});
const options={command:'pytest',skipFilters:false};
const log='progress\n'.repeat(100)+'ERROR E42 /tmp/check.py:12\nFAILED test_checksum\n```python\ndef f():\n    return "한글\\n"\n```';
const run=(s,o=options,c=compress)=>adapt(s,o,c,estimate);
test('compress output and preserve all metadata including large integer bytes',()=>{
 const input='{ "output" : '+JSON.stringify(log)+', "exit_code": 1, "error":{"message":"failure"}, "cwd":"/tmp", "id":900719925474099312345, "meta":{"output":"untouched"} }';
 const r=run(input);assert(r.compressed);assert(r.text.endsWith(input.slice(input.indexOf(', "exit_code"'))));assert.equal(JSON.parse(r.text).output,compress(log).text);assert(r.compressedTokens<r.originalTokens);
});
for(const [name,obj] of Object.entries({nullOutput:{output:null,exit_code:0},objectOutput:{output:{a:1},exit_code:0},nestedOnly:{data:{output:log},exit_code:0},missingMarker:{output:log},array:[{output:log,exit_code:0}]}))test(name+' unchanged',()=>{const s=JSON.stringify(obj);assert.equal(run(s).text,s)});
test('malformed JSON unchanged',()=>{assert.equal(run('{"output": bad').text,'{"output": bad')});
test('duplicate keys unchanged',()=>{const s='{"output":'+JSON.stringify(log)+',"output":"last","exit_code":0}';assert.equal(run(s).text,s)});
test('escaped output key and quote/backslash metadata',()=>{const s='{"outpu\\u0074":'+JSON.stringify(log)+',"exit_code":0,"extra":"a\\\"b\\\\c"}';const r=run(s);assert(r.compressed);assert.equal(JSON.parse(r.text).extra,JSON.parse(s).extra)});
test('nonterminal and orphan unchanged',()=>{const s=JSON.stringify({output:log,exit_code:1});assert.equal(run(s,{command:'cat x',skipFilters:true}).text,s);assert.equal(run(s,{}).text,s)});
test('nested JSON output not recursively compressed',()=>{const s=JSON.stringify({output:JSON.stringify({output:log,exit_code:0}),exit_code:0});assert.equal(run(s).text,s)});
test('reject loss of errors or fenced code',()=>{const s=JSON.stringify({output:log,exit_code:1});assert.equal(run(s,options,()=>({text:'short',compressed:true})).text,s)});
test('no growth and compressor exception pass through',()=>{const s=JSON.stringify({output:'short',exit_code:0});assert.equal(run(s,options,()=>({text:'x'.repeat(100),compressed:true})).text,s);assert.equal(run(s,options,()=>{throw Error('failure')}).text,s)});
test('plain output delegates to native RTK',()=>assert.equal(run(log),null));
test('inner guard prevents recursion',()=>assert.equal(run(JSON.stringify({output:log,exit_code:1}),{...options,__hermesEnvelopeInner:true}),null));
test('null error and zero exit are preserved',()=>{const r=run(JSON.stringify({output:log,exit_code:0,error:null}));assert.equal(JSON.parse(r.text).exit_code,0);assert.equal(JSON.parse(r.text).error,null)});
test('patcher checks anchor, is idempotent and fails on incompatible versions',()=>{
 const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),{spawnSync}=require('node:child_process');
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'rtk-patch-'));
 try {
  const file=path.join(dir,'fixture.js'),anchor='function B(a,b={}){let c=z(b.config),d=(0,e.estimateCompressionTokens)(a),f=[],h=[],q=[];return a} function D(a){if(!g.enabled)return{body:a,compressed:!1,stats:null};let h=(0,r.m)(a)}';fs.writeFileSync(file,anchor);
  const go=()=>spawnSync(process.execPath,[path.join(__dirname,'patch.cjs'),dir],{encoding:'utf8'});
  assert.equal(go().status,0);const first=fs.readFileSync(file,'utf8');assert(first.includes('hermes-rtk-envelope.cjs'));assert.equal(go().status,0);assert.equal(fs.readFileSync(file,'utf8'),first);
  fs.writeFileSync(file,first.replace('.responses(a,g,B,e.createCompressionStats)', '.oldResponses(a,g,B,e.createCompressionStats)'));assert.notEqual(go().status,0);
  fs.writeFileSync(file,'function different(){}');assert.notEqual(go().status,0);assert.equal(fs.readFileSync(file,'utf8'),'function different(){}');
 }finally {fs.rmSync(dir,{recursive:true,force:true})}
});
