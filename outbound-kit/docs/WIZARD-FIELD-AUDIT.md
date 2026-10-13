# Wizard field audit: original Hermes Kit -> outbound installer

Date: 2026-10-13

This is a field and acceptance audit, not a claim that the current HTML page is an
installer. The current `wizard.html` creates a **non-secret plan** (`setup.json`). It
does not install Hermes, connect to a server, collect credentials, restart a gateway,
or prove a live channel. Those steps must not be represented as complete merely because
the plan file was downloaded.

## Executive verdict

The current wizard covers the outbound brief well enough to create a plan, but it covers
only a fraction of the original kit's setup contract. In particular:

1. `target=server` is metadata; there is no SSH destination, host-key verification,
   remote preflight, deployment, service installation, or reboot test.
2. Model/provider/auth are absent and delegated to an unspecified later Hermes screen.
3. Telegram and Discord collect only an owner ID. Token collection is a separate terminal
   prompt; guild/channel/intent/permission/install checks are absent.
4. Optional service selection exists, and credentials can be checked separately by
   `services.py`, but the selected service is not applied to the Hermes runtime and no
   end function is proven.
5. Vault choices exist in the plan and a separate Markdown workflow exists, but the main
   `kit.py setup` path does not implement the selected vault operation.

A viable integrated installer should therefore be a resumable sequence, not one long
form: **preflight -> target -> engine -> model -> channel -> outbound profile -> optional
services -> vault/schedule -> apply/restart -> live acceptance**. Secret input belongs in
the local installer session, never in `setup.json`.

## Required phase contract

| Phase | Purpose | Completion evidence |
|---|---|---|
| 0. Preflight | Identify OS/architecture, permissions, network, disk, existing Hermes and chosen home | Exact detected values plus blocking/non-blocking findings |
| 1. Target | Select local desktop or connect to a prepared Linux server | Local path is writable, or verified SSH host key and remote preflight succeed |
| 2. Engine | Install or reuse a supported Hermes version in the dedicated home | Exact executable/version; isolated model-free smoke test |
| 3. Model | Choose auth mode, provider and exact model; authenticate privately | A tool-free model request returns an expected probe result |
| 4. Channels | Configure each chosen bot and least-privilege owner/channel binding | Bot identity, platform settings and real owner message/reply all pass independently |
| 5. Outbound profile | Collect non-secret brief, workflows, filters and source mode | Schema-valid saved plan and fixture workflow output |
| 6. Optional services | Connect only explicitly selected services | Credential auth and service-specific functional acceptance are separate states |
| 7. Vault/schedule | Configure output and opt-in schedules/delivery | A generated record reaches the selected path; one manual scheduled run succeeds |
| 8. Apply/lifecycle | Commit config, restart the dedicated runtime, and (server only) install lifecycle | Foreground start/restart; server stop/start and reboot recovery |
| 9. Report | Produce evidence without secret values | Per-component `planned/configured/authenticated/functional/applied/live` states |

## Exhaustive field mapping

Status means the state in `hermes-outbound-kit` today, not what the documentation asks an
installation assistant to do manually.

### A. Target, runtime and server

| Original/donor input or inferred value | Secret? | Required new phase and representation | Current status | Missing acceptance |
|---|---:|---|---|---|
| Local vs server target | No | Phase 1: `target=desktop|server` | **Implemented as plan only** | It does not choose an execution transport or change behavior |
| Dedicated Hermes home/data directory | No | Phase 0/2: resolved absolute path, existing/new choice | CLI `--home` exists; absent from wizard | Ownership, collision preview, same-home enforcement across every action |
| OS, CPU architecture, package/install privilege | No | Phase 0: detected, never user-guessed | **Missing** | Real Mac Intel/Apple Silicon, Windows native/WSL, supported Linux matrix |
| Existing Hermes executable/version | No | Phase 0/2: detect/reuse/upgrade choice | `kit.py` invokes an installed executable | Engine installation and version compatibility are not implemented |
| `SSH_ALIAS` from `hermes-vps-setup` | No | Phase 1: saved connection profile name, optional convenience only | **Missing** | Must not be treated as a host identity |
| Server host/IP | No (sensitive metadata possible) | Phase 1: explicit host | **Missing** | DNS/IP validation and host-key-bound connection |
| SSH port | No | Phase 1: integer 1-65535, default 22 | **Missing** | Connection probe |
| SSH username | No (sensitive metadata possible) | Phase 1: explicit unprivileged account | **Missing** | Remote UID/home/ownership and sudo requirements |
| SSH auth method | Yes-adjacent | Phase 1: agent or local key **path selected locally**; optional interactive password | **Missing** | Never serialize private key/password; prove non-interactive reconnect when service work needs it |
| SSH server identity | Security-critical | Phase 1: known-host fingerprint shown and accepted once | **Missing** | `StrictHostKeyChecking=no` is forbidden; changed keys block |
| Remote install directory / service name | No | Phase 1/8: user-owned path and collision-safe unique service name | **Missing** | Existing Hermes services must not be replaced |
| Remote OS/arch/RAM/disk/outbound HTTPS | No | Phase 1 preflight, detected through SSH | **Missing** | Fail before credential prompts if unsupported |
| Foreground vs long-running service | No | Phase 8: foreground first; service is a later explicit opt-in | Docs only | Stop/start/restart/log/reboot checks |
| `LOCAL_VAULT_ROOT`, `PORTABLE_ST_DIR` donor settings | No | Phase 7 advanced sync only | Current wizard has `vault_path`, not Syncthing transport | Keep out of MVP unless PC/server sync is actually offered |

### B. Discord bootstrap and `/setup` context

The original Discord `/setup` obtains important values implicitly from the interaction:
the invoking user, guild and channel. A pre-bot installer cannot infer those values and
must ask for or discover them explicitly.

| Original input/inference | Secret? | Required new phase and representation | Current status | Required validation / live acceptance |
|---|---:|---|---|---|
| `DISCORD_BOT_TOKEN` (original Compose input) | **Yes** | Phase 4 private password field or native secret prompt | Separate hidden terminal prompt | Call bot identity endpoint; never echo/log/token-in-argv |
| Discord Application ID | No | Derive from verified token; display read-only | Not persisted/shown | Must match the intended application before invite |
| Invite/install scopes (`bot`, `applications.commands`) | No | Phase 4 generated OAuth URL or installation-state check | **Missing** in outbound | Confirm selected guild contains this bot |
| Bot permission bit set | No | Phase 4 least-privilege permission preview | **Missing** | Check test-channel effective permissions, not just requested bits |
| Message Content Intent | No, but privileged setting | Phase 4 explicit check with portal deep link/remediation | Mentioned in PREPARE only | Receive a non-command owner message; do not infer success from token auth |
| Guild/server ID | No | Phase 4 explicit ID or choice discovered after token/invite | **Missing** | Verify guild identity and bot membership |
| Test/home channel ID | No | Phase 4 explicit channel choice; later delivery destination | **Missing** | Read, send, attach/embed/thread/history requirements as actually used |
| Invoking `/setup` user ID | No | Phase 4 owner/allowlist ID | `discord_owner` plan field | Token holder and guild owner are not the same concept; verify an owner message |
| Guild owner inference in donor | No | Replace with explicit authorized-user policy | **Missing semantics** | Do not automatically authorize every server member or assume ID is guild owner |
| `DISCORD_HOME_CHANNEL` | No | Phase 4/7 saved only after channel test | **Missing** | Restart greeting/delivery reaches the chosen channel |
| Non-owner rejection | No | Phase 4 negative acceptance test with a second account when feasible | Described only | Must remain `unverified` if a negative live test was not performed |
| Restart/apply notification channel | No | Phase 8 derive from verified home channel | **Missing** | Pending marker cleared on restart failure |

The donor's `owner.py` tries to configure application flags/install parameters and creates
an invite URL, while its comments also say Message Content Intent may require a manual
portal action. The new installer must report the actual API/portal result. It must not turn
"PATCH attempted" into "intent enabled".

### C. Telegram

Telegram was not the primary original `hermes-kit` setup UI, so these are outbound/upstream
requirements rather than fields copied from that Discord flow.

| Required input/inference | Secret? | Required phase | Current status | Required validation / live acceptance |
|---|---:|---|---|---|
| BotFather bot token | **Yes** | Phase 4 private input | Separate hidden terminal prompt | `getMe` bot identity, no value in output |
| Owner numeric user ID | No | Phase 4 plan/allowlist | `telegram_owner` implemented | Validate ID syntax and preserve conflicting existing binding |
| Bot username/identity confirmation | No | Phase 4 derived display | Probe checks bot shape but UX does not confirm intended identity | User confirms correct bot before commit |
| `/start` completed | No | Phase 4 state | **Missing** | Bot can receive an update/message from owner |
| Owner message/reply | No | Phase 4 live test | **Missing** | End-to-end gateway reply, not API authentication |
| Non-owner rejection | No | Phase 4 negative live test | **Missing** | Record `unverified` if not tested |
| Delivery chat/thread ID | No | Phase 7 when schedules are enabled | **Missing** | Manual delivery succeeds before cron registration |

### D. Model and authentication

| Original `/setup` input/action | Secret? | Required new phase and representation | Current status | Required acceptance |
|---|---:|---|---|---|
| Auth mode: ChatGPT device login vs API key | Choice | Phase 3 explicit choice | **Missing from wizard**; `kit.py model` delegates upstream | Exact provider path selected and resumable |
| ChatGPT device authorization | OAuth credential | Phase 3 provider-owned browser/device flow; installer shows only verified URL/code | Not integrated | Login result plus tool-free model response |
| Main provider | No | Phase 3 controlled list from installed Hermes capabilities | **Missing** | Never accept a provider that runtime cannot load |
| Exact main model ID | No | Phase 3 provider discovery/recommended default plus editable ID | **Missing** | Actual response; account entitlement and rate limit matter |
| API key (Command Code/OpenCode Go/Gemini where used) | **Yes** | Phase 3 private provider-specific prompt | Not integrated | Auth and model response; atomic add without overwriting unrelated keys |
| Main vs auxiliary role | No | Phase 3 advanced; default to main only for MVP | **Missing** | Delegation probe separately if enabled |
| Auxiliary provider/model | No + secret auth | Phase 3 advanced | **Missing** | Actual delegated child task, not main-model fallback |
| Gemini key for video summarization | **Yes** | Phase 3 or optional capability, only if that feature ships | **Missing** | Keep out of outbound MVP unless video workflow is demonstrated |
| Model response check | No | Phase 3 mandatory acceptance | `kit.py doctor/model` can invoke upstream, not orchestrated in wizard | Fresh, tool-free prompt with provider/model recorded |
| Free-account route | Account-dependent | Phase 3 offer only after live capacity probe | **Not guaranteed** | Never promise workshop-wide free availability/rate limits |

### E. Original kit packs and outbound services

| Original pack/input | Secret? | New phase | Current status | What still distinguishes auth from function |
|---|---:|---|---|---|
| Gemini base pack / `GEMINI_API_KEY` | **Yes** | Phase 3 optional model/capability | Not in service choices | A real intended Gemini operation |
| Groq voice / `GROQ_API_KEY` | **Yes** | Phase 6 | Selection + private auth discovery implemented separately | Consent, audio input, transcription, Korean quality, runtime config and restart |
| Webshare / `WEBSHARE_API_KEY`; runtime-selected direct proxy credentials | **Yes** | Phase 6 | Selection, API auth discovery, exact-origin contract, and bounded `runtime_connect.py proxy-fetch` implemented | Live source response and source permission remain unverified; no bypass claims |
| Apify / `APIFY_TOKEN` | **Yes** | Phase 6 | Selection + account auth discovery implemented separately | Actor ID/version, reviewed input schema, max spend, run, result schema, retention |
| Composio / `COMPOSIO_CONSUMER_KEY` | **Yes** | Phase 6 | Selection + MCP discovery implemented separately | Per-app OAuth, scopes, tool allowlist and a read-only app action; sending remains off |
| OpenCode Go / `OPENCODE_GO_API_KEY` | **Yes** | Phase 3 provider/auth, not generic service | **Missing** | Model response |
| Command Code / `COMMANDCODE_API_KEY` | **Yes** | Phase 3 provider/auth, not generic service | **Missing** | Model response and correct transport/base URL |
| Service selection | No | Phase 5/6 multi-select | `services[]` implemented | Selection does not mean connected |
| Service runtime patch | No, but references secrets | Phase 6 preview then apply | `services.py` stages a non-secret plan only | Runtime version compatibility, apply/restart/rollback |

Each service needs separate state: `selected`, `credential_saved`, `authenticated`,
`runtime_configured`, `functional`, and `live_after_restart`. A green check on one state
must not color the whole row green.

### F. Workflows, sources and sales profile

| Input | Origin | Required phase | Current status | Remaining requirement |
|---|---|---|---|---|
| Product/service description | New outbound | Phase 5 | Implemented |
| Target customer | New outbound | Phase 5 | Implemented |
| General search keywords | New outbound | Phase 5 | Implemented |
| Workflows: jobs/funding/tenders/overseas | New outbound | Phase 5 | Implemented | UI correctly labels tenders/overseas as design/manual, but installer report must too |
| Job keywords | New outbound | Phase 5 | Implemented |
| Funding keywords | New outbound | Phase 5 | Implemented |
| Region | New outbound | Phase 5 | Implemented |
| Exclusion keywords | New outbound | Phase 5 | Implemented |
| Original `KitSelect` job/role skill choice | Original kit | Phase 5 maps to workflow/skill pack selection | Partly replaced by workflows | Show exact skill files to install; do not imply every workflow has a live source |
| Source mode: fixture/file/live adapter | Needed for truthful demo | Phase 5 explicit choice per workflow | **Missing from wizard** | Evidence provenance, fetch time, partial/zero/error distinctions |
| Send vs draft policy | Needed for sales safety | Phase 5 default `draft_only` | **Missing** | No outbound auto-send in MVP; explicit later approval and rate limits |

### G. Vault, sync, schedule and other original advanced inputs

| Original/new input | Secret? | Required phase | Current status | Recommendation / acceptance |
|---|---:|---|---|---|
| Vault mode: none/new/existing | No | Phase 7 | Implemented in plan only | Main setup must call a reviewed operation; existing vault needs collision preview/approval |
| Vault path | Sensitive local metadata | Phase 7 local path chooser | Implemented in plan only | Resolve locally; forbid symlink/path escape; write a sample and show exact path |
| Syncthing PC device ID | No but device identifier | Phase 7 advanced sync | **Missing** | Cut from MVP unless server-PC two-way sync is a stated workshop outcome |
| Import ZIP filename | Sensitive content adjacent | Post-install import | **Missing** | Cut from installer; separate explicit import with archive traversal/size checks |
| Proactive send time (`HH:MM`) | No | Phase 7 schedules | **Missing** | Include timezone, destination, pause state; run once manually before enabling |
| Proactive topic | Potentially sensitive | Phase 7 | **Missing** | Local config only; preview prompt/data exposure |
| Timezone (donor hard-coded Korean time) | No | Phase 7 | **Missing** | Explicit IANA timezone, especially on server |
| Schedule delivery channel ID | No | Phase 7 derived from verified channel | **Missing** | Manual delivery acceptance |
| OMH task category/provider/model/fallback/effort | No + provider keys | Advanced model routing | **Missing/deferred** | Cut from workshop MVP; only enable after core model/channel path is live |
| OmniRoute dashboard password/provider/key/model/mode | **Yes** in part | Separate advanced product setup | **Missing/deferred** | Keep optional and outside default installer; it expands service, network and rollback scope |
| OmniRoute vision bridge connect/disconnect | Security-impacting | Separate advanced setup | **Missing** | Never default; shared-bridge impact requires explicit confirmation |
| Crawl4AI install/uninstall | No | Optional source dependency | **Missing** | Cut unless one chosen live adapter requires it; document ~1 GB and platform support |
| Apply/restart action | No | Phase 8 | `kit.py setup` runs sequential commands, but no managed lifecycle | Config readiness, atomic apply, restart and post-restart probes |
| Disconnect/reset/backup actions | Destructive/sensitive | Post-install management | **Missing** | Preview exact owned keys/files; provider-side OAuth revocation remains external |

## Safe secret-input design for an integrated installer

### Boundary

`setup.json` remains a portable, non-secret plan. A separate installer process runs **on
the target that will own the runtime** and collects credentials only when their phase is
reached. An instructor laptop, workshop web host, analytics endpoint, AI chat, QR code, ZIP,
vault and support bundle must never receive a token, API key, OAuth token, SSH password or
private key.

For a desktop, use a native window or a loopback-only local web UI. For a server, prefer a
verified SSH session followed by a remote TTY prompt (`getpass`) so the secret never returns
to a controller process. If the installer transports a secret over SSH, it must use stdin
over the already verified encrypted connection, never a command argument, environment shown
by process listings, generated shell script, or shell history.

### Local web UI security requirements

- Bind only `127.0.0.1`/`::1`; choose a random high port. Do not expose on LAN or `0.0.0.0`.
- Create a high-entropy one-time session token and require it plus same-origin checks on every
  state-changing request. Reject cross-origin requests and all unexpected `Host` headers.
- Use `POST` for secret submission, with `Cache-Control: no-store`, `Referrer-Policy:
  no-referrer`, a restrictive CSP, `frame-ancestors 'none'`, and no third-party scripts,
  fonts, telemetry or error reporting.
- Secret inputs use password controls and are never written to URL, DOM summaries,
  `localStorage`, `sessionStorage`, clipboard helpers, browser download, crash reports or
  installer logs. Disable request-body logging.
- Keep values in memory only until provider verification and the atomic target-side commit.
  Overwrite/release buffers where practical; do not claim perfect memory erasure in Python or
  a browser.
- OAuth uses the provider-owned browser/device page. The installer stores only the resulting
  runtime credential in the target's supported credential store; it never asks the user to
  paste an OAuth callback URL or bearer token into chat.

### Storage and updates

- Prefer the OS credential store where the Hermes runtime supports it. If Hermes requires an
  `.env`, use a target-user-owned file with mode `0600` on POSIX and a user-only ACL on Windows.
- Use an interprocess lock, parse the existing file, reject partial pairs/conflicting owners,
  write a same-directory temporary file, `fsync`, atomically replace, and retain only a
  permission-protected recovery copy when the user explicitly requests rollback.
- Updates are additive by default. Never blank or overwrite an unrelated existing model,
  channel or service key. A replacement requires identity preview and explicit confirmation.
- Config files refer to secret **environment variable names**, never embed values. Reports show
  `present/missing`, credential fingerprint only if provider-safe and non-reversible, and last
  validation time; never prefixes/suffixes of secrets.
- A failed auth probe writes nothing. A successful auth probe may save the credential but must
  still label runtime/application/function checks as pending.
- Provide rotation and removal: stop the dependent runtime, remove only installer-owned
  bindings, restart, and instruct provider-side revoke/rotation.

### SSH-specific requirements

- Resolve host, port and username before any secret prompt. Show the server key algorithm and
  SHA-256 fingerprint on first contact; require confirmation and save to an installer-owned
  known-hosts file. A changed fingerprint is a hard stop.
- Prefer an SSH agent or a user-selected local private-key **path**. Never copy a private key
  into the kit, plan or remote host. Do not ask the AI assistant to read it.
- Do not use `StrictHostKeyChecking=no`, broad `sudo`, password automation tools, or a shared
  workshop SSH account. Probe the exact required privilege and explain any sudo action before
  it runs.
- Perform every provider auth probe from the server when the server is the target. A laptop
  success does not establish the server's DNS, egress, clock or TLS path.

## Wizard UX and state rules

The UI should show one row per component and one badge per state. Suggested state machine:

`not_selected -> planned -> input_needed -> configured -> authenticated -> functional -> applied -> live`

`blocked`, `failed`, `restart_required`, `reboot_unverified`, and `skipped` are explicit side
states. Resume starts from durable non-secret state plus secret presence metadata. It never
re-prompts for an existing matching credential/owner pair. It refuses a partial pair or
conflicting owner until the user chooses an explicit repair/rebind flow.

Examples of wording:

- Good: `Discord token accepted; Message Content Intent and test-channel reply are pending.`
- Bad: `Discord connected.`
- Good: `Apify account authenticated; no Actor was run and no cost was incurred.`
- Bad: `Apify ready.`
- Good: `Server service restarted; reboot recovery has not been tested.`
- Bad: `24/7 server complete.`

## MVP cuts and go/no-go gates

To make a three-hour workshop credible, the default path should include one desktop engine
path, one model route, local/Telegram **or** local/Discord (not force both), the sales pack,
fixture/file input, draft generation, and an optional Markdown vault. Keep these out of the
default path: OMH category tuning, OmniRoute, vision bridge, Syncthing, Crawl4AI, proactive
messages, automatic sending, and unreviewed scraping.

Server installation is an advanced path only if the server already exists and all of these
gates pass before the event:

1. Clean supported Linux VM install, verified host key, interruption/resume and reinstall.
2. Real model response and at least one chosen real channel owner round trip from that VM.
3. Foreground start, managed service start/stop/restart, log location and reboot recovery.
4. No key appears in process arguments, shell history, generated plan, logs or support report.
5. Rollback/removal preserves unrelated Hermes homes and services.

Desktop claims require separate real-device gates on supported macOS and Windows variants;
Linux simulation is not evidence for either. Optional services remain workshop demonstrations
only after auth **and** their service-specific functional gate has passed using a low-cost,
consented test.

## Evidence inspected

Read-only donor references:

- `../hermes-kit/plugins/kit-setup/packs.json` — provider/service keys and config patches.
- `../hermes-kit/plugins/kit-setup/views.py` — `/setup` model, pack, kit, Syncthing,
  proactive, OMH/OmniRoute and apply/restart inputs.
- `../hermes-kit/plugins/kit-setup/owner.py` — Discord token-derived application identity,
  install URL/permissions and owner allowlist behavior.
- `../hermes-kit/plugins/kit-setup/model_setup.py` and `oauth_login.py` — exact provider/model,
  device login and tool-free response probe.
- `../hermes-kit/plugins/kit-setup/proactive.py` — time/topic/channel delivery and schedule.
- `../hermes-vps-setup/setup.env.example` and `scripts/lib.sh` — SSH alias and local sync paths.

Current outbound references:

- `wizard.html` and `kit.py` — plan schema, pack install, private channel prompts and command
  orchestration.
- `services.py` and `docs/SERVICES.md` — selected-service authentication discovery and staged
  non-secret runtime requirements.
- `vault_flow.py`, `docs/PREPARE.md`, `docs/SERVER.md` and
  `agent-skill/hermes-outbound-setup/SKILL.md` — current separately documented/manual paths.

This audit deliberately treats donor behavior as evidence, not as a specification to copy.
For example, a Discord interaction can infer its channel and caller, while a pre-install HTML
page cannot; a safe integrated installer must make that hidden dependency explicit.
