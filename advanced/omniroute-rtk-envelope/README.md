# Hermes tool-result JSON adapter for OmniRoute RTK

The optional student Compose installs `ghcr.io/wendy-nam/hermes-kit:omniroute-rtk-json-1`.
This is an OmniRoute image, not the Hermes runtime image. The base is a pinned
`next-web` digest, with one public adapter added. It contains no instructor data,
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

Builds stop if upstream compiled patch anchors change. CI runs preservation tests
and the actual shipped RTK engine on all three wire formats before publishing.
Update the pinned base only after these checks pass; do not silently fall back to
an unpatched upstream image. A custom KIT_OMNIROUTE_IMAGE can bypass this adapter.

```sh
node --test advanced/omniroute-rtk-envelope/test.cjs
docker build -t kit-omniroute advanced/omniroute-rtk-envelope
docker run --rm --network none \
  -v "$PWD/advanced/omniroute-rtk-envelope/runtime-test.cjs:/tmp/runtime-test.cjs:ro" \
  --entrypoint node kit-omniroute /tmp/runtime-test.cjs
```
