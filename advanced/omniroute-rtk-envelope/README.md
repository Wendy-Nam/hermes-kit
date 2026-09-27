# Hermes tool-result JSON adapter for OmniRoute RTK

The optional student Compose installs `ghcr.io/wendy-nam/hermes-kit:omniroute-rtk-json-3`.
This is an OmniRoute image, not the Hermes runtime image. The base is a pinned
`next-web` digest, with public compatibility and performance patches. It contains no instructor data,
keys, routing pools, profiles, or personal plugins.

When OmniRoute RTK is enabled, terminal JSON results can have their top-level
`output` string compressed. Every other envelope byte is preserved, including
`exit_code`, `error`, nested metadata, and integers larger than JavaScript can
represent exactly. Malformed/unsupported payloads pass through unchanged.
Loss of error lines or fenced code cancels compression. This is conservative
protection, not a guarantee that every semantically important log line survives.

Supported wire formats: OpenAI Chat Completions, Anthropic Messages, and OpenAI
Responses. Only results associated with a recognized terminal command qualify.
The adapter does not enable RTK or change existing compression profiles by itself.
Start with RTK alone, minimal intensity, generic-output filter, no comment removal,
no grouping/renderers, and no compression of assistant messages/code blocks.
Additional pipeline engines can alter content outside this adapter's protections.

Hermes calls sent directly to another provider bypass OmniRoute. Keep Hermes RTK
available for those paths; avoid compressing the same tool result twice. Neither
placement reduces the billed cost of a direct TTS/STT/image-generation request.

Context-window reconciliation stays enabled. At startup and on its normal schedule,
it refreshes automatically discovered context limits, preserves manual overrides,
and removes redundant automatic overrides. The pinned standalone Node startup module
now builds the upstream capability snapshot once per run instead of re-reading the
whole catalog for each model. Each later run obtains a fresh snapshot; this is not a
long-lived cache and does not disable provider/model discovery. Alternate upstream
build targets are not supported by this pinned-image patch.

An isolated comparison over 8,932 installed catalog models returned identical
context windows: 23.25 seconds without the snapshot versus 0.23 seconds including
snapshot construction. These are local benchmark results, not an inference-latency
promise. Runtime tests additionally verify manual overrides, redundant override
removal, and changed discovery data on a later run.

Builds stop if upstream compiled patch anchors change. CI runs preservation tests
and the actual shipped RTK engine on all three wire formats before publishing.
Update the pinned base only after these checks pass; do not silently fall back to
an unpatched upstream image. A custom KIT_OMNIROUTE_IMAGE can bypass this adapter.

```sh
node --test advanced/omniroute-rtk-envelope/test.cjs advanced/omniroute-rtk-envelope/reconcile-test.cjs
docker build -t kit-omniroute advanced/omniroute-rtk-envelope
docker run --rm --network none \
  -v "$PWD/advanced/omniroute-rtk-envelope/runtime-test.cjs:/tmp/runtime-test.cjs:ro" \
  --entrypoint node kit-omniroute /tmp/runtime-test.cjs
docker run --rm --network none \
  -v "$PWD/advanced/omniroute-rtk-envelope/reconcile-runtime-test.cjs:/tmp/reconcile-test.cjs:ro" \
  --entrypoint node kit-omniroute /tmp/reconcile-test.cjs
```

## Compression worker dependencies (`omniroute-rtk-json-3`)

OmniRoute 3.8.51's standalone image omits eight packages its own `package.json`
declares and `open-sse/services/compression/compressionWorker.js` imports
(`xxhash-wasm`, `uuid`, `@toon-format/toon`, `omniglyph`, `safe-regex`, `smol-toml`,
`socks`, `yazl`). The worker then fails at import and compression runs on the main
thread for every streamed token; installing `xxhash-wasm` alone still fails on `uuid`.
`worker-deps/package-lock.json` pins that set (13 packages with dependencies, all
MIT/BSD, no install scripts); the build runs `npm ci --ignore-scripts` and copies only
packages absent from the image, refusing to mix versions. `compression-worker-test.cjs`
checks the worker comes online in its own thread.
