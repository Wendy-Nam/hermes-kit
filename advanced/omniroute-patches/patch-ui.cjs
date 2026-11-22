const fs=require("fs"),path=require("path"),vm=require("vm");
const anchorRe=/for\(let t of ([gm])\)\{let ([li])=t\.providerSpecificData\?\.apiKeyHealth;if\(!\2\)continue;/;
let files=[];function scan(d){if(!fs.existsSync(d))return;for(const f of fs.readdirSync(d)){let p=path.join(d,f);if(fs.statSync(p).isDirectory())scan(p);else if(f.endsWith(".js")){let s=fs.readFileSync(p,"utf8");if(s.includes("apiKeyWarningAlertTitle")&&(anchorRe.test(s)||s.includes("if(t.isActive===false)continue;")))files.push(p);}}}
scan("/app/.build/next/static");scan("/app/.next/static");
if(files.length!==1)throw Error("Expected one pinned dashboard notification chunk: "+files.length);
const p=files[0],s=fs.readFileSync(p,"utf8");
if(!s.includes("if(t.isActive===false)continue;")){
 const m=anchorRe.exec(s);
 if(!m||s.split(m[0]).length!==2)throw Error("Ambiguous patch anchor");
 const replacement=`for(let t of ${m[1]}){if(t.isActive===false)continue;let ${m[2]}=t.providerSpecificData?.apiKeyHealth;if(!${m[2]})continue;`;
 const n=s.replace(m[0],replacement);new vm.Script(n);fs.writeFileSync(p,n);
}
console.log("Patched active-only API-key alert selector",p);

