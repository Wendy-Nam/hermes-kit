ARG OMNIROUTE_BASE_IMAGE=diegosouzapw/omniroute:next-web@sha256:3c8698a83d40205914aa9e343fd3b1378c4ba8940a3a3adb5ecfc7f0b1b9cb61
FROM ${OMNIROUTE_BASE_IMAGE}
USER root
COPY envelope.cjs /app/hermes-rtk-envelope.cjs
COPY patch.cjs /tmp/patch-hermes-rtk.cjs
COPY reconcile-patch.cjs /tmp/patch-hermes-reconcile.cjs
RUN node /tmp/patch-hermes-rtk.cjs && node /tmp/patch-hermes-reconcile.cjs && rm /tmp/patch-hermes-rtk.cjs /tmp/patch-hermes-reconcile.cjs
# The standalone image omits packages OmniRoute declares for its compression worker
# (xxhash-wasm, uuid, ...); the worker then dies at import and compression falls back
# to the main thread on every streamed token. Install exactly the locked set
# (integrity-checked, no install scripts) and add only packages the image lacks.
COPY worker-deps/package.json worker-deps/package-lock.json /tmp/worker-deps/
RUN cd /tmp/worker-deps && npm ci --ignore-scripts --no-audit --no-fund \
 && node -e 'const fs=require("fs"),path=require("path");const src="/tmp/worker-deps/node_modules",dst="/app/node_modules";const top=d=>fs.readdirSync(d).filter(n=>!n.startsWith(".")).flatMap(n=>n.startsWith("@")?fs.readdirSync(path.join(d,n)).map(m=>n+"/"+m):[n]);for(const n of top(src)){if(fs.existsSync(path.join(dst,n)))throw new Error("already in image, refusing to mix versions: "+n);fs.cpSync(path.join(src,n),path.join(dst,n),{recursive:true})}' \
 && chown -R node:node /app/node_modules && rm -rf /tmp/worker-deps /root/.npm
USER node
