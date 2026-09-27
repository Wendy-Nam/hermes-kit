'use strict';
// Preserve the envelope bytes; only replace the top-level output string token.
function outputSpan(text) {
  let i = text.indexOf('{') + 1;
  const seen = new Set(); let span;
  const space = () => { while (/\s/.test(text[i] || '') && i < text.length) i++; };
  const quoted = () => {
    const start = i++;
    while (i < text.length) {
      if (text[i] === '\\') { i += 2; continue; }
      if (text[i++] === '"') return [start, i];
    }
    throw Error('unterminated string');
  };
  while (i < text.length) {
    space(); if (text[i] === '}') break;
    if (text[i] !== '"') throw Error('key');
    const [ks, ke] = quoted(), key = JSON.parse(text.slice(ks, ke));
    if (seen.has(key)) throw Error('duplicate key');
    seen.add(key); space(); if (text[i++] !== ':') throw Error('colon'); space();
    const start = i; let depth = 0;
    while (i < text.length) {
      const ch = text[i];
      if (ch === '"') { quoted(); continue; }
      if (ch === '{' || ch === '[') depth++;
      if (ch === '}' || ch === ']') { if (!depth) break; depth--; }
      if (ch === ',' && !depth) break;
      i++;
    }
    let end = i; while (/\s/.test(text[end - 1] || '') && end > start) end--;
    if (key === 'output') span = [start, end];
    if (text[i] === ',') { i++; continue; }
    break;
  }
  return span;
}
function protect(original, compressed) {
  const fences = original.match(/```[^\n]*\n[\s\S]*?```/g) || [];
  if (!fences.every(block => compressed.includes(block))) return false;
  return original.split(/\r?\n/).filter(line => /error|failed|exception|traceback|\bFAIL\b|TS\d{4}/i.test(line))
    .every(line => compressed.includes(line));
}
module.exports = function envelope(text, options, compress, estimate) {
  if (options.__hermesEnvelopeInner || typeof text !== 'string' || ! /^[{[]/.test(text.trimStart())) return null;
  const unchanged = () => ({text, compressed:false, originalTokens:estimate(text), compressedTokens:estimate(text), techniquesUsed:[], rulesApplied:[]});
  try {
    const obj = JSON.parse(text);
    if (!obj || Array.isArray(obj) || typeof obj.output !== 'string' ||
        !(Object.hasOwn(obj, 'exit_code') || Object.hasOwn(obj, 'error')) ||
        options.skipFilters || typeof options.command !== 'string' || !options.command.trim()) return unchanged();
    const span = outputSpan(text); if (!span) return unchanged();
    if (/^[{[]/.test(obj.output.trimStart())) { try { JSON.parse(obj.output); return unchanged(); } catch {} }
    const inner = compress(obj.output, {...options, __hermesEnvelopeInner:true});
    if (!inner.compressed || typeof inner.text !== 'string' || !protect(obj.output, inner.text)) return unchanged();
    const result = text.slice(0, span[0]) + JSON.stringify(inner.text) + text.slice(span[1]);
    const before = estimate(text), after = estimate(result);
    if (after >= before) return unchanged();
    // Validate syntax without reserializing metadata (large integers stay exact).
    JSON.parse(result);
    return {...inner, text:result, originalTokens:before, compressedTokens:after, compressed:true,
      techniquesUsed:[...new Set([...(inner.techniquesUsed || []),'rtk-hermes-json-output'])]};
  } catch { return unchanged(); }
};

// Responses API keeps function calls at input[] rather than messages[]. Preserve
// that wire format and join output to the corresponding terminal call by call_id.
module.exports.responses = function responses(body, config, compress, stats) {
  if (!Array.isArray(body.input) || Array.isArray(body.messages)) return null;
  if (!config.applyToToolResults) return {body,compressed:false,stats:null};
  const calls=new Map(), techniques=[], rules=[];
  for(const item of body.input) {
    if (item?.type !== 'function_call' || typeof item.call_id !== 'string') continue;
    if(calls.has(item.call_id)){calls.set(item.call_id,null);continue;}
    let command;try{const a=JSON.parse(item.arguments);command=a.command??a.cmd}catch{}
    calls.set(item.call_id,/\b(bash|shell|terminal|run_command|execute_command|exec|command)\b/.test(String(item.name).toLowerCase()) && typeof command==='string' ? command:null);
  }
  let changed=false;
  const input=body.input.map(item=>{
    if(item?.type!=='function_call_output'||typeof item.output!=='string'||item.cache_control!=null)return item;
    const command=calls.get(item.call_id);if(!command)return item;
    const result=compress(item.output,{config,command,skipFilters:false});
    if(!result.compressed)return item;
    changed=true;techniques.push(...result.techniquesUsed);rules.push(...result.rulesApplied);
    return {...item,output:result.text};
  });
  if(!changed)return {body,compressed:false,stats:null};
  const next={...body,input};const report=stats(body,next,'rtk',[...new Set(techniques)],[...new Set(rules)],0);report.engine='rtk';
  return {body:next,compressed:true,stats:report};
};
