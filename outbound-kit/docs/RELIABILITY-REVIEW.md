# Reliability review: guided full-kit journeys

This review treats a workshop install as a chain of independently evidenced states. A
configuration matrix, a successful download, or an exit code of zero is not an end-to-end
result. Tests use synthetic inputs and mocked external boundaries unless a row explicitly
says `live`.

## Supported journey shapes

The same logical journey applies to five entry routes:

| Entry route | Engine route | Credential boundary | Required device evidence |
|---|---|---|---|
| macOS terminal | scoped POSIX install | user-owned private terminal or official browser flow | scoped launcher, model response, selected channel round trips |
| Windows terminal | scoped PowerShell install | user-owned private terminal or official browser flow | scoped launcher, NTFS secret ACL, model response, selected channel round trips |
| Linux terminal | scoped POSIX install | user-owned private terminal or official browser flow | scoped launcher, model response, selected channel round trips |
| Hermes Desktop app | desktop build selected during the scoped engine install | official app/browser UI; no secret copied to AI chat | app artifact, app launch, same dedicated `HERMES_HOME`, model response |
| prepared Linux server | SSH staging, then the same installer on the server | user's private SSH terminal or official browser/device flow | host trust, scoped launcher, foreground probe, service/reboot recovery |

For every route, `none`, Telegram, Discord, and `both` are distinct channel requests.
`none` still requires the local model flow; it is not a bypass for engine or secret-file
privacy checks. Telegram and Discord each require credential validation, configuration,
an owner round trip, and an unauthorized-user rejection. `both` requires independent
evidence for both channels; one passing channel must not make the combined step green.

The four workshop scenarios are `job_signal`, `funding_signal`, `tender_watch`, and
`overseas_partner`. Each journey must preserve this chain:

1. validated non-secret requirement profile;
2. scoped Hermes engine and exact reviewed revision;
3. installed outbound profile and skills;
4. real model response, when live mode is requested;
5. requested channel and optional-service gates;
6. requested OMH installation, with static install distinguished from host/plugin/tool use;
7. optional OmniRoute platform, provider, model/tool and route-activation gates;
8. one selected scenario source envelope with evidence and freshness fields;
9. profile-aware scoring/draft artifacts in the requested output and Obsidian vault;
10. doctor, redacted status, stop/start instructions, and contextual resume.

The optional service set is not a power set used to inflate test counts. Webshare, Groq,
Apify, and Composio each get a representative contract and failure injection because their
functional proofs differ. Likewise, OMH and OmniRoute are tested as explicit requested and
unrequested branches, not as interchangeable booleans.

## Evidence rules

| Claim | Minimum evidence | Not sufficient |
|---|---|---|
| engine installed | dedicated launcher executes and checkout revision matches the reviewed pin | ambient `hermes` on `PATH`, downloaded installer |
| model ready | harmless real response from the configured model route | model screen opened, doctor passed |
| channel ready | owner round trip plus unauthorized-user rejection for that channel | bot identity/getMe, token saved |
| service ready | provider-specific functional probe | credential accepted or tools listed |
| OMH installed | pinned receipt, distribution version, hook hash and static doctor | `omh_enabled=true` |
| OMH live | host restart, plugin/tool visibility and delegated task | static import/register smoke |
| OmniRoute ready | owned container plus provider login, model discovery and repeated tool probe | dashboard health only |
| scenario result | source envelope, evidence/freshness, nonempty/empty/blocked distinction, profile-aware artifact | sample file exists |
| vault result | artifacts belong to the selected scenario/profile and preserve human review | seed vault initialized |
| resumable | receipt matches config, execution context and current implementation; first incomplete action is named | a prior zero exit code |

## Failure-injection focus

`tests/test_guided_contracts.py` is reserved for hand-offs that unit tests inside one module
cannot establish. It should cover only callable interfaces that exist in the current tree:

- missing or unverified scoped engine blocks downstream mutation;
- selected OMH cannot be silently skipped and cannot run before engine verification;
- a selected workflow reaches the actual scenario runner and carries the profile into the
  vault rather than producing only generic seed data;
- changing home, output, platform route, configuration, or implementation invalidates a
  receipt instead of resuming in the wrong context;
- timeout, interrupt, malformed helper output, and selected-channel partial failure return
  a stable support code and next action without a traceback or secret-bearing diagnostics;
- every plan/help action names a file and subcommand that is present and callable in the
  shipped bundle;
- official-document assistance remains pinned and cited, while executable syntax comes
  from the installed version's `--help`.

## Current review state

The guided installer now makes engine, pack/profile, model response, OMH, channels,
services, routing, first workflow, doctor, gateway, operations, and Desktop launch explicit
steps. Offline mode skips connected components and runs an explicitly labelled synthetic
scenario; it does not pretend to install an engine. Context-bound receipts include the
configuration, home/output/vault paths, and the current implementation fingerprint. Resume
reuses only current `passed`/`configured` receipts. OMH static setup is `configured`, with
host load and delegation left false rather than being promoted to live success.

The deterministic modules demonstrate meaningful offline behavior for the four scenario
runners, source normalization, profile-aware vault artifacts, pinned engine material,
OMH rollback, OmniRoute ownership checks, runtime service configuration, and official-doc
caching. The release ZIP contract checks that every advertised runtime helper is shipped.
Captured child results must be JSON objects and cannot hide an explicit failure status
behind exit zero; child stderr is not copied into support output.

On 2026-10-13, `python3 -m unittest discover -s tests -q` completed 222 tests successfully
on this Linux cloud machine. The focused guided journey suite completed 12 tests covering
named macOS Desktop/both-channel, Windows terminal/Telegram, Linux terminal/Discord, and
prepared-server/local-chat plans, schema contradictions, resume, helper failure injection,
official-doc/engine pin coherence, OMH evidence, and distribution contents. These are
fixture/static results, not Mac/Windows/server or provider live results. Earlier matrix-count
tests are not used as evidence for live readiness.

Live gates that cannot be completed in this Linux cloud environment remain:

- clean-device macOS, Windows native, Desktop app, and Linux server installs;
- Windows NTFS ACL recheck and macOS/Windows Docker Desktop behavior, including ARM
  `linux/amd64` emulation;
- real model/provider authentication and response;
- Telegram/Discord owner round trips and unauthorized-user rejection;
- provider-specific Webshare/Groq/Apify/Composio functional probes;
- Hermes host restart, OMH tool visibility/delegation, OmniRoute route activation and
  direct-model fallback;
- server service start, stop, reboot recovery, and schedule execution.

These are reported as live gates, not converted to passes by mocks, synthetic fixtures, or
matrix iteration counts.
