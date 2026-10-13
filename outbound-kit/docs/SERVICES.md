# Optional service integration contract

`services.py` prepares the four optional integrations selected in `setup.json`:
Webshare, Groq STT, Apify, and Composio Connect MCP. It does not install Hermes and does
not claim a provider is functionally ready merely because it accepted a credential.

## Commands

```sh
python3 services.py plan --config setup.json --home ~/.hermes-outbound
python3 services.py status --config setup.json --home ~/.hermes-outbound
python3 services.py connect --config setup.json --home ~/.hermes-outbound
python3 services.py apply --config setup.json --home ~/.hermes-outbound
python3 services.py check --config setup.json --home ~/.hermes-outbound
```

- `plan` writes `outbound-services.runtime.json`, a non-secret, generated application plan.
- `status` reports only selection and credential **presence**. It never prints values and
  does not make network requests.
- `connect` privately prompts for missing credentials, performs bounded read-only auth
  discovery, validates every newly entered credential, then performs one additive `.env`
  update. Existing model and bot bindings are preserved.
- `apply` writes only configuration shapes supported by the pinned Hermes `0.21.7`, plus
  installation-owned non-secret connector contracts. It refuses an unknown value at a path
  it would own and rolls back a partial multi-file write.
- `check` compares files to the requested configuration. It is not a network or end-to-end
  check and therefore keeps `functional_verified=false`.

The CLI is intentionally separate from `kit.py`. The installer may call it, but must not turn
`auth_valid`, `runtime_configured`, or `functional_verified` into one generic success state.

## Secret and filesystem behavior

- Secret values are forbidden in `setup.json`, the browser wizard, command arguments,
  generated runtime plans, status output, and error messages.
- POSIX uses a `0700` service home and a `0600` atomically replaced `.env`. Windows uses
  the same private-input and atomic-replace path, but must additionally be checked for an
  intended-user-only NTFS ACL on a real Windows machine.
- `.env` updates use a stable cross-platform interprocess lock, preserve existing bytes,
  refuse duplicate or existing bindings, `fsync` the temporary file, and replace only
  after every newly selected provider passes authentication discovery.
- Existing credentials are preserved and reported as present; `connect` does not read them
  back into a prompt or silently replace/revalidate them. Rotation remains an explicit
  provider/upstream Hermes operation.
- Fixed HTTPS origins, disabled ambient proxies, refused redirects, response-size bounds,
  structured response checks, and generic errors reduce SSRF and secret-leak risk. DNS and
  provider compromise remain outside this local check's trust boundary.

## What each probe means

| Service | Environment binding | Read-only authentication discovery | Explicitly not verified |
|---|---|---|---|
| Groq | `GROQ_API_KEY` | Retrieve the models envelope | STT model entitlement, audio upload, transcription quality, consent |
| Apify | `APIFY_TOKEN` | Retrieve the current-user envelope | Actor selection, source legality, cost, run, dataset result/retention |
| Webshare | `WEBSHARE_API_KEY` | Retrieve one proxy-list page | Proxy transport in Hermes, any target, source permission, bypass |
| Composio | `COMPOSIO_CONSUMER_KEY` | MCP `initialize`, initialized notification, `tools/list` | OAuth app authorization, scopes, Gmail/calendar/CRM reads, drafting or sending |

Every successful probe returns `auth_valid=true` and
`functional_verified=false`. That distinction is part of the API contract.

## Runtime application contract (Hermes 0.21.7)

The generated runtime plan and applied YAML use environment **references**, never secret
values. `runtime_connect.py` was checked against the pinned `0.21.7`
`cli-config.yaml.example` and MCP interpolation code.

| Service | What `apply` actually changes | Remaining acceptance gate |
|---|---|---|
| Groq STT | `stt.enabled=true`, `stt.provider=groq`, `stt.groq.model=whisper-large-v3-turbo`; Hermes reads `GROQ_API_KEY` from `.env` | after explicit audio-upload consent, restart and transcribe a non-sensitive synthetic clip |
| Composio | fixed `mcp_servers.composio` URL, `${COMPOSIO_CONSUMER_KEY}` header reference, and `strict_redirect_headers=true` | authorize each app/scope in provider UI, restart, list tools, run one read-only tool |
| Webshare | an installation-owned exact HTTPS **origin** and key reference in `outbound-connectors.json`; `runtime_connect.webshare_fetch` selects one direct proxy and performs one bounded GET | run one reviewed target fetch; no generic/global Hermes egress proxy is configured |
| Apify | actor identity, hard USD cap, token reference, and `automatic_runs=false` in `outbound-connectors.json` | review terms/input/retention, then run exactly one explicitly confirmed Actor invocation |

Apify never runs during `connect` or `apply`. A manual submission is:

```sh
python3 services.py run-apify --config setup.json --home ~/.hermes-outbound \
  --apify-input reviewed-input.json --confirm-paid-run
```

The command sends the reviewed JSON object to the configured Actor with
`maxTotalChargeUsd=<configured cap>`. It disables ambient proxies and redirects so the bearer
is not forwarded elsewhere. `submitted_not_completed` means only that Apify returned a run ID;
cost, completion state and dataset contents still require inspection.

Webshare is likewise explicit rather than a global proxy setting:

```sh
python3 runtime_connect.py proxy-fetch --config setup.json --home ~/.hermes-outbound \
  --url 'https://the-approved-origin.example/reviewed-path' \
  --output fetched-source.bin
```

The helper reads `WEBSHARE_API_KEY` only from the private local `.env`, asks the fixed
Webshare API for one direct proxy, and performs one GET only when the URL's normalized HTTPS
origin exactly equals the applied contract. It disables ambient proxies for provider discovery,
refuses redirects and userinfo, caps the target response at 5 MiB, and stops on 403/429. It does
not rotate proxies, retry a denial, solve CAPTCHA, log in, or bypass source controls. The helper
is a source transport; it is not a claim that the fetched material may legally be collected or
contacted.

An existing conflicting STT or `mcp_servers.composio` value is preserved and reported as a
blocked apply. Existing unrelated model, bot, channel and MCP settings remain intact. YAML
comments/formatting are not promised to survive PyYAML serialization; semantic settings are.

After applying Groq or Composio, restart only the foreground gateway or service owned by this
dedicated `HERMES_HOME`. Webshare and Apify connector files do not themselves require a Hermes
restart. Do not kill a generic Hermes process or replace an existing service. Run the
provider-specific functional check and record it separately.

## Platform and operational status

The implementation and synthetic endpoint tests were exercised in the Linux cloud workspace.
They do not establish macOS Keychain behavior, Windows ACLs, a real provider credential,
Hermes adapter compatibility, server service restart, or attendee-network concurrency.

Before workshop publication:

1. Test one disposable credential per provider without displaying it in logs or support output.
2. Verify the installed runtime really is the pinned Hermes 0.21.7 before advertising the
   applied shapes as compatible.
3. Complete one bounded functional test per selected provider and keep the auth/functional
   statuses distinct.
4. Test rotation/revocation, restart, and a failed/partial provider response.
5. Keep Webshare targets, Apify Actors, Composio app grants, and Groq audio disabled by default.
