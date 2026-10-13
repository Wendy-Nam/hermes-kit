# Scenario and adversarial review

Review date: 2026-10-13. Scope: the checked-in 0.1 kit, proposed optional service
fields, and the workshop runtime contract. This review does not treat mocked APIs,
fixture executables, or an offline sample as evidence of a live integration.

## Recommendation

The current kit is suitable as an **alpha configuration generator and offline skill-pack
installer**. It is not yet a one-click Hermes installer or a verified outbound automation
runtime. For a workshop MVP, keep live sending and scheduled collection disabled, make
OmniRoute a later module, and require a manual run with synthetic or user-supplied data
before enabling any external collector.

The release should remain no-go for a claim such as “Mac/Windows/server one-click setup,
all selected services active, and 24-hour automation” until the gates at the end of this
document pass.

## Evidence executed here

| Check | Result | What it establishes |
|---|---:|---|
| `python3 -m unittest discover -s tests -v` | Passed, 24 tests | Python validation, file preservation, fixture channel staging, eight config combinations, and setup orchestration on this Linux cloud machine |
| `python3 tests/browser_flow.py` | Passed, 2 flows | The exact `wizard.html` DOM generated both-channel and local-only downloads in headless Linux Chromium without HTTP(S) requests |
| Missing-Hermes setup fixture | Passed | Setup stops nonzero after producing recoverable offline install/sample outputs |
| Model-command failure fixture | Passed | A nonzero model step prevents channel collection and doctor execution |
| Doctor failure fixture | Passed | Doctor's nonzero status is returned after a successful channel step |
| Existing `.env` fixture | Passed | Adding one channel preserves prior model text and the replacement file is mode `0600` on this POSIX host |

The browser test had to load the checked-in HTML with `page.set_content` because managed
Chromium blocks `file://` navigation. It therefore does **not** prove that double-clicking
the launcher works on an attendee machine.

Not verified: a real Hermes binary or supported CLI version, actual model login/response,
Telegram/Discord message delivery, any of the four proposed services, macOS, Windows,
NTFS ACLs, a Linux background service, process restart, reboot recovery, or a live data
source. The fake `hermes` executable in `tests/test_flow.py` checks argument order and
`HERMES_HOME`; it is not engine evidence.

## Severity-ranked findings

### Blockers — observed in current code

1. **Setup is not resumable after channel commit.** `connect()` rejects the selected
   channel when any selected token or allowlist key already exists. If credentials are
   saved and the later doctor step fails, a second `setup` run stops in `connect()` before
   doctor. A completed setup is similarly not idempotent. The correct behavior is to
   report an existing complete channel as `configured, needs live check`, reject only
   incomplete or conflicting pairs, and resume at the first unfinished step.

2. **A success message precedes the final gate.** `main()` prints “구성 완료” before
   executing doctor. A nonzero doctor is propagated, but the user has already seen a
   completion claim. Completion text must follow doctor and the real model/channel checks;
   otherwise use “configuration saved; runtime checks remain.”

3. **Model selection is not model readiness.** Setup accepts exit code zero from
   `hermes model`, then validates bot identity and runs doctor. It never sends a model
   prompt or receives a response. The installer and slides must keep `model configured`
   separate from `model response passed`.

4. **Bot identity is not channel readiness.** `check_token()` calls Telegram `getMe` or
   Discord `/users/@me`. It does not prove owner allowlist behavior, Discord intents,
   bot invitation, Start state, receive permission, or a message round trip. Each selected
   channel needs its own live status and test message.

5. **No-channel mode skips secret-file permission review.** `connect()` returns before
   inspecting `.env` when the channel is `none`. An existing model `.env` can therefore
   remain group/world readable on POSIX. On Windows, a mode check would still not prove
   an adequate NTFS ACL. Secret-file privacy is a home-level preflight, not a channel step.

6. **Business criteria are written with ambient permissions.** `outbound-profile.json`
   may contain a private product, customer segment, region, and sourcing terms, but
   `preserve_write()` uses the process umask. A multi-user server can commonly produce a
   world-readable file. Create the dedicated home as `0700` and profile/state as `0600`
   on POSIX; document and verify the intended-user ACL on Windows.

7. **The proposed services are not implemented in the reviewed version.** Unknown fields
   are correctly rejected, but this also means `services`, `job_keywords`,
   `funding_keywords`, `region`, and `exclude_keywords` cannot yet be claimed as supported.
   Wizard presence, schema acceptance, secret activation, and a real capability test are
   separate gates.

8. **Restart/service ownership is absent.** Saving `.env` does not activate a gateway that
   was already running. The kit neither records `restart_required` nor identifies whether
   a foreground process or an installed service owns the gateway. It must never kill a
   generic Hermes process or replace an existing service merely to apply settings.

### Important — observed limitations

9. `install()` checks all current managed files for conflicts before normal writes, which
   is useful, but its multiple writes are not a filesystem transaction. Disk failure or
   interruption can leave a partial pack. A resume manifest must verify every managed
   file instead of treating directory existence as completion.

10. Channel values are validated before the one atomic `.env` replacement, so a failed
    second channel currently saves neither channel. That is good. However, existing
    Telegram plus a request to add Discord using `both` is rejected wholesale. The design
    needs explicit incremental-add behavior without silently replacing either credential.

11. Telegram validation necessarily places the bot token in the Telegram Bot API URL.
    User-visible errors are redacted, but the token can still appear in local HTTP proxy,
    diagnostic, or intermediary URL logs. Never enable urllib debug logging, shell tracing,
    full request logging, or error dumps around this request. Token rotation belongs in
    the incident procedure.

12. `sample()` is honestly labeled synthetic and never sends. Preserve that wording.
    Real sourcing must not silently reuse the sample's successful status, and future CSV
    exports must neutralize spreadsheet formula prefixes (`=`, `+`, `-`, `@`).

### Hypotheses requiring targeted validation

These are risks inferred from the implementation, not reproduced failures:

- `.env` has a compare-before-replace check but no inter-process lock. Two installers can
  both pass the final comparison and the later replace can lose the earlier update.
- `preserve_write()` rejects a final symlink but does not reject symlinked output parents.
  This matters if the installer is ever run as a more privileged user. The supported rule
  should be “never run the workshop installer with sudo/Administrator.”
- Upstream `hermes model`, `doctor`, `gateway run`, and service-install syntax may vary by
  Hermes release. No compatible version is pinned or exercised here.
- The launcher and wizard may behave differently under Gatekeeper, Windows browser download
  policy, controlled-folder access, non-ASCII usernames, or enterprise antivirus.
- Provider validation endpoints, quotas, billing state, and retention policies can change;
  a token-shape check or one successful identity call is not a durable capability test.

## Required state model and resume contract

Use explicit step states rather than a single success flag:

1. `config_validated`
2. `pack_installed`
3. `sample_generated`
4. `model_configured`
5. `model_response_passed`
6. one state per service: `selected`, `credential_validated`, `authorized`, `capability_passed`
7. one state per channel: `credential_validated`, `configured`, `live_roundtrip_passed`
8. `doctor_passed`
9. server only: `service_installed`, `restart_passed`, `reboot_passed`

The state file must contain no tokens, raw API responses, email addresses, OAuth codes, or
message content. It may record timestamps, component versions, non-secret failure classes,
and a one-way credential fingerprint only if there is a demonstrated need. A rerun resumes
at the first incomplete state. “Selected” must never render as “connected.”

Atomicity is per local integration. Validate a token before acquiring the write lock, then
lock, re-read, merge, write a `0600` temporary file, `fsync`, atomically replace, and preserve
unrelated keys/comments. Reject duplicate or half-present key pairs. Remote OAuth grants and
Apify runs are external side effects and cannot be rolled back by replacing `.env`; expose
them as separate steps with provider-side revoke links.

## Hard constraints for optional services

The configuration may contain only a unique enum list such as
`["webshare", "groq", "apify", "composio"]`. Secret values must remain forbidden in
`setup.json`, wizard fields, URLs shown to the user, command arguments, generated artifacts,
test fixtures that ship, and status files. Unknown and duplicate service names are errors.

The optional sourcing fields `job_keywords`, `funding_keywords`, `region`, and
`exclude_keywords` are non-secret profile text, not proof that a live collector exists.
Apply the same single-line and size limits as other profile text. The wizard must omit empty
values consistently, or the validator must define an empty-string canonical form.

### Webshare

- Treat as an explicit network proxy integration, not a generic “blocking bypass.” Never
  use it to defeat CAPTCHA, authentication, paywalls, rate limits, robots directives, or an
  explicit access denial.
- Validate account/proxy entitlement with a documented read-only provider operation. Do not
  probe Wanted, Saramin, LinkedIn, or another third-party target merely to declare setup
  successful.
- Proxy credentials and target queries are sensitive. Show the egress/privacy consequence
  before activation and keep proxy use disabled until a permitted source is selected.

### Groq

- Validate the credential with a minimal documented read-only or tiny inference operation;
  distinguish key validity, model entitlement, quota, and actual response.
- If used for voice, state that audio leaves the device and obtain explicit consent before
  uploading it. Do not activate microphone capture as part of setup.
- A Groq key is optional and must never become the default fallback merely because it exists.

### Apify

- Validate identity or account access without starting an Actor. Actor execution can incur
  cost, create retained datasets, and contact third-party sites.
- Require a separately named Actor/source, pinned input schema, run budget, result limit,
  retention/delete policy, and source-specific terms review before the first run.
- Record failed/partial/timed-out Actor runs distinctly from an empty result. Never schedule
  an Actor until one manual run is reviewed.

### Composio

- A consumer/project key does not authorize Gmail, calendar, CRM, or sending. Represent each
  app connection and permission scope separately.
- OAuth must occur in the user's provider UI with least privilege. Keep read and send/write
  permissions separate; the workshop MVP should request read-only or draft-only access.
- Setup completion must not depend on granting an unrelated app. Provide provider-side revoke
  instructions and verify revocation without printing connection metadata that identifies
  the participant.

## Channel constraints

- Telegram and Discord remain independent. Failure of one in `both` must not be reported as
  success for both; the UI needs two rows.
- Validate owner IDs syntactically before secret prompts, then confirm with a message from the
  configured owner. Never provide an allow-all fallback.
- Do not put tokens in chat, browser local storage, `setup.json`, QR codes, process arguments,
  screenshots, doctor output, or support bundles.
- Discord success requires bot invitation, message-content intent where needed, channel
  permissions, receive, and reply. Telegram success requires the user to start the bot and
  receive a reply.
- If a gateway is running, configuration changes produce `restart_required`. Restart only a
  process/service created for this dedicated `HERMES_HOME`, then repeat both live checks.

## Platform and server constraints

### macOS

Verify both Intel and Apple Silicon when claimed. Test the launcher from Finder, quarantine
and Gatekeeper behavior, Python/Hermes discovery in a GUI-launched environment, spaces and
Korean characters in paths, private terminal input, sleep/resume, and clean removal. Do not
disable Gatekeeper or TLS verification.

### Windows

Test Windows native PowerShell/cmd separately from Git Bash or WSL and publish exactly which
one is supported. Verify `py -3`, long/non-ASCII paths, downloaded-file reputation prompts,
controlled-folder access, bot-token input without echo, and an intended-user-only NTFS ACL.
POSIX `0600` evidence does not apply. Do not require hidden Bash, `tar`, or Python dependencies
without preflight and an actionable error.

### Linux server

First pass foreground model response and channel round trips. Only then install a service
under the same unprivileged user, with the exact dedicated `HERMES_HOME`. Refuse to overwrite
an existing Hermes service. Secret values must not appear in the unit command line, unit file,
world-readable environment file, or logs. Verify start, stop, restart, log redaction, and a
real reboot. Desktop sleep behavior is not equivalent to 24-hour server operation.

## Data and outbound guardrails

- Use user-supplied/synthetic records or an official, permitted API for the workshop default.
- Keep evidence URL and collection date, label unknowns, and separate procurement plans from
  actual notices. A hiring post is not evidence of budget or intent.
- No invented email addresses, access-control bypass, bulk personal-profile enrichment,
  automatic sending, or scheduled collection by default.
- Before enabling a source, document its terms/API license, robots/rate limits, personal-data
  basis, retention/deletion, and opt-out/suppression behavior. Public visibility alone is not
  permission for systematic collection or unsolicited messaging.
- Prompt-injection resistance in the outbound skill is necessary but not sufficient: fetched
  pages remain untrusted data, and their instructions must never change tools, destinations,
  recipients, or approval rules.

## Go/no-go gates

1. Pin and test a supported Hermes version and perform a real model response, not only model
   selection and doctor.
2. Make setup resumable after every failure point; move completion wording after all selected
   required checks.
3. Lock and atomically merge secret state, verify POSIX modes and Windows ACLs, and add a
   redacted status report.
4. Run real clean installs on each advertised macOS/Windows environment and one fresh Linux
   server. Clearly label unsupported architectures/shells.
5. Pass independent live owner-only message round trips for each advertised channel, including
   restart. No credentials may appear in logs or artifacts.
6. For every advertised optional service, pass credential, entitlement, and one bounded
   capability test; document provider revocation and data/cost implications.
7. Use a permitted source and synthetic fallback in class. Keep sends and schedules off until
   a reviewed manual run and a separate explicit enablement.
8. Rehearse the exact attendee flow under expected concurrency and network conditions, with a
   recovery path for engine install, login, provider quota, and channel failure.

Until these gates pass, describe the kit as an installation-support alpha with an offline
configuration wizard and synthetic outbound exercise—not a verified one-click sales agent.
