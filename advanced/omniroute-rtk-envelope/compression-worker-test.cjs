// OmniRoute's compression worker must load in its own thread. Upstream declares
// xxhash-wasm but the published image omits it; the worker then dies at import
// and every streamed token's compression falls back onto the main thread.
const { Worker } = require('node:worker_threads');
const assert = require('node:assert');
const appRequire = require('node:module').createRequire('/app/package.json');
(async () => {
  const worker = new Worker('/app/open-sse/services/compression/compressionWorker.js');
  const outcome = await new Promise((resolve) => {
    worker.once('error', (error) => resolve(error));
    worker.once('online', () => setTimeout(() => resolve('online'), 1500));
  });
  await worker.terminate();
  assert.strictEqual(outcome, 'online', `compression worker failed: ${outcome && outcome.message}`);
  const hash = (await appRequire('xxhash-wasm')()).h64ToString('hermes-kit');
  assert.match(hash, /^[0-9a-f]{16}$/);
  console.log('compression worker loads with xxhash-wasm; hash', hash);
})().catch((error) => { console.error(error.message); process.exit(1); });
