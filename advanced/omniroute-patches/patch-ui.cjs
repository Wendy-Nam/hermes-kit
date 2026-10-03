const fs=require("fs"),path=require("path"),vm=require("vm");
const old="for(let t of g){let l=t.providerSpecificData?.apiKeyHealth;if(!l)continue;";
const replacement="for(let t of g){if(t.isActive===false)continue;let l=t.providerSpecificData?.apiKeyHealth;if(!l)continue;";
let files=[];function scan(d){if(!fs.existsSync(d))return;for(const f of fs.readdirSync(d)){let p=path.join(d,f);if(fs.statSync(p).isDirectory())scan(p);else if(f.endsWith(".js")){let s=fs.readFileSync(p,"utf8");if(s.includes("apiKeyWarningAlertTitle")&&s.includes(old))files.push(p);}}}
scan("/app/.build/next/static");scan("/app/.next/static");
if(files.length!==1)throw Error("Expected one pinned dashboard notification chunk: "+files.length);
const p=files[0],s=fs.readFileSync(p,"utf8");if(s.split(old).length!==2)throw Error("Ambiguous patch anchor");let n=s.replace(old,replacement);new vm.Script(n);fs.writeFileSync(p,n);console.log("Patched active-only API-key alert selector",p);
