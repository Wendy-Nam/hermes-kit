'use strict';
const fs = require('node:fs'), path = require('node:path');
const root = process.argv[2] || '/app/.build/next/server/chunks';
const anchor = 'function B(a,b={}){let c=z(b.config),d=(0,e.estimateCompressionTokens)(a),f=[],h=[],q=[]';
const prefix = 'function B(a,b={}){const __h=require("/app/hermes-rtk-envelope.cjs")(a,b,B,e.estimateCompressionTokens);if(__h)return __h;let c=z(b.config),d=(0,e.estimateCompressionTokens)(a),f=[],h=[],q=[]';
const candidates = fs.readdirSync(root).filter(x=>x.endsWith('.js')).map(x=>path.join(root,x));
const changed = [], writes = [];
const vm = require('node:vm');
for (const file of candidates) {
  const text = fs.readFileSync(file,'utf8');
  if (text.includes(prefix)) {
    if (!text.includes('.responses(a,g,B,e.createCompressionStats);if(__hr)return __hr;')) throw Error('Partial Hermes RTK patch: Responses adapter missing');
    new vm.Script(text, {filename:file});
    changed.push(file); continue;
  }
  if (!text.includes(anchor)) continue;
  if (text.split(anchor).length !== 2) throw Error('Ambiguous RTK anchor: '+file);
  let patched=text.replace(anchor,prefix);
  const responsesAnchor='if(!g.enabled)return{body:a,compressed:!1,stats:null};let h=(0,r.m)(a)';
  if(patched.split(responsesAnchor).length!==2) throw Error('Responses RTK anchor missing or ambiguous');
  patched=patched.replace(responsesAnchor,'if(!g.enabled)return{body:a,compressed:!1,stats:null};const __hr=require("/app/hermes-rtk-envelope.cjs").responses(a,g,B,e.createCompressionStats);if(__hr)return __hr;let h=(0,r.m)(a)');
  new vm.Script(patched, {filename:file});
  writes.push([file,patched]); changed.push(file);
}
if (!changed.length) throw Error('Unsupported OmniRoute build: RTK anchor missing. Do not deploy an unpatched image.');
for (const [file,text] of writes) fs.writeFileSync(file,text);
console.log('Hermes RTK JSON adapter patched: '+changed.map(x=>path.basename(x)).join(', '));
