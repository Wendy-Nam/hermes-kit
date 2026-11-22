'use strict';
const fs = require('node:fs'), path = require('node:path');
const root = process.argv[2] || '/app/.build/next/server/chunks';
const anchorRe = /function ([A-Z])\(a,b=\{\}\)\{let c=([A-Za-z]+)\(b\.config\),d=\(0,e\.estimateCompressionTokens\)\(a\),f=\[\],h=\[\],([qr])=\[\]/;
const responsesRe = /if\(!([fg])\.enabled\)return\{body:a,compressed:!1,stats:null\};let (h=\(0,r\.m\)\(a\)|g=\(0,s\.mu\)\(a\))/;
const candidates = fs.readdirSync(root).filter(x=>x.endsWith('.js')).map(x=>path.join(root,x));
const changed = [], writes = [];
const vm = require('node:vm');
for (const file of candidates) {
  const text = fs.readFileSync(file,'utf8');
  if (text.includes('require("/app/hermes-rtk-envelope.cjs")')) {
    if (!/\.responses\(a,[fg],[A-Z],e\.createCompressionStats\);if\(__hr\)return __hr;/.test(text)) {
      throw Error('Partial Hermes RTK patch: Responses adapter missing');
    }
    new vm.Script(text, {filename:file});
    changed.push(file); continue;
  }
  const m = anchorRe.exec(text);
  if (!m) continue;
  if (text.split(m[0]).length !== 2) throw Error('Ambiguous RTK anchor: '+file);
  const [full, fn, cfgFn, arrVar] = m;
  const prefix = `function ${fn}(a,b={}){const __h=require("/app/hermes-rtk-envelope.cjs")(a,b,${fn},e.estimateCompressionTokens);if(__h)return __h;let c=${cfgFn}(b.config),d=(0,e.estimateCompressionTokens)(a),f=[],h=[],${arrVar}=[]`;
  let patched = text.replace(full, prefix);
  const rm = responsesRe.exec(patched);
  if (!rm || patched.split(rm[0]).length !== 2) throw Error('Responses RTK anchor missing or ambiguous');
  const [rFull, cfgVar, tail] = rm;
  patched = patched.replace(rFull, `if(!${cfgVar}.enabled)return{body:a,compressed:!1,stats:null};const __hr=require("/app/hermes-rtk-envelope.cjs").responses(a,${cfgVar},${fn},e.createCompressionStats);if(__hr)return __hr;let ${tail}`);
  new vm.Script(patched, {filename:file});
  writes.push([file,patched]); changed.push(file);
}
if (!changed.length) throw Error('Unsupported OmniRoute build: RTK anchor missing. Do not deploy an unpatched image.');
for (const [file,text] of writes) fs.writeFileSync(file,text);
console.log('Hermes RTK JSON adapter patched: '+changed.map(x=>path.basename(x)).join(', '));

