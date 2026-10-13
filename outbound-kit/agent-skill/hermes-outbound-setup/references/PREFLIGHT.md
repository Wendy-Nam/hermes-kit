# Preflight and execution contract

Use this reference after reading `SKILL.md`. Always inspect local `--help` before executing
a helper; examples in plans or another kit version do not define the installed interface.

## Common checks

Record values, not secrets:

- target type, OS version, architecture, shell, user identity, and whether the session is interactive;
- kit root and dedicated Hermes home;
- free disk and ownership/write access for the dedicated home and output directory;
- Python launcher/version when required by the current helper; if absent, use only the
  pinned native download/hash fallback documented for the engine before invoking Python helpers;
- `hermes` path/version/help and whether another Hermes home/service exists;
- network reachability for selected providers and source endpoints;
- when Hermes is missing, `engine_bootstrap.py plan` conflicts, pinned installer commit/hash,
  dedicated install directory, and the shared launcher/PATH locations it would touch;
- selected workflow, channel, services, source mode, and Obsidian choice;
- current profile validation and the last known evidence state per component.

Reject or pause on:

- secrets found in `setup.json`, ZIPs, tracked files, generated plans, or command arguments;
- a dedicated home or secret file that is a symlink or owned by another user;
- a request to overwrite an unrelated Hermes home/service;
- an existing Hermes checkout, shared launcher, or `hermes` on PATH when attempting the
  fresh-engine bootstrap; preserve and inspect it instead of forcing a second owner;
- unsupported OS/architecture/runtime;
- noninteractive secret collection;
- an unreviewed paid Actor, write scope, automatic send, or schedule;
- an external source with no documented allowed access path.

Do not read secret values to check them. Inspect names/presence and filesystem metadata only.

## macOS desktop

- Distinguish Apple Silicon and Intel. Certification on one does not certify the other.
- Start from Finder at least once when validating the participant path; a Terminal-only run
  does not prove Finder/Gatekeeper behavior or GUI PATH discovery.
- Support spaces and Korean characters in user paths.
- Use a user-owned install location. Do not remove quarantine flags or disable Gatekeeper.
- Verify private prompt behavior and dedicated-home permissions.
- Run foreground first. If launchd support exists, inspect current helper/Hermes help and
  install it only after a manual workflow passes.
- Report sleep behavior honestly and test a resume if scheduled desktop work is enabled.

## Windows desktop

- State whether the current path is Windows native, WSL2, or unsupported. Never silently
  switch between them.
- Check current helper support for `py -3`; do not assume `python3`, Bash, `chmod`, `tar`,
  Git Bash, or WSL exists.
- Validate standard-user operation, Korean/space paths, long paths, Defender/SmartScreen,
  controlled-folder access, and execution-policy effects without weakening protections.
- A POSIX `0600` mode is not Windows evidence. Verify intended-user-only NTFS ACL behavior
  using a supported implementation; otherwise mark secret storage unverified.
- If Task Scheduler support exists, enable only after a manual workflow passes and verify
  the exact dedicated home, user, stop path, and sleep/wake semantics.

## Prepared Linux server

- Require a supported distro/architecture, an already working SSH route, an unprivileged
  target user, sufficient disk/RAM, and outbound HTTPS to selected endpoints.
- Run setup in a private interactive terminal on the server. Do not transport secrets
  through AI chat, an SCP bundle, shell history, process arguments, or a unit file.
- Use a target-user-owned dedicated home. Refuse a conflicting existing service/home.
- Run model response, sources, and channels in the foreground first.
- If the installed Hermes version exposes a supported service command, inspect its help,
  preview changes, then install for this dedicated home only.
- Verify start, stop, restart, redacted logs, and a real reboot before claiming 24-hour mode.
- Do not enable root mounts, privileged containers, swap creation, firewall changes, or
  system-wide package changes as hidden defaults.

## Component minimum probes

### Model

1. Login/key configured through official private flow.
2. Harmless prompt returns a real response.
3. If the workflow needs tools, a harmless tool-capability check succeeds.

### Telegram

1. Token identity check.
2. Owner ID configured without allow-all.
3. Owner presses Start and receives a reply.
4. A non-owner is rejected.

### Discord

1. Bot identity check.
2. Invite, required intent, and channel permissions confirmed.
3. Owner receives a reply.
4. A non-owner is rejected.

### Webshare

1. Explain that queries/traffic transit the proxy provider.
2. Read-only entitlement/auth check through the supported helper.
3. Source-specific transport probe only for a reviewed permitted source.
4. Distinguish proxy auth failure, source denial, timeout, and empty result.

### Groq STT

1. Explain external audio transfer and obtain consent.
2. Auth/quota/model entitlement check through the supported helper.
3. Transcribe a short synthetic/nonpersonal Korean sample.
4. Confirm where transcript/audio is retained or deleted.

### Apify

1. Read-only account/auth check without starting an Actor.
2. Name and pin the approved Actor and review its developer/source policy.
3. Show input, request/result/cost limit, and dataset retention.
4. Run one bounded job; distinguish partial/timed-out/failed/empty.

### Composio

1. Provider/project layer reachable.
2. User completes OAuth in provider UI for one named app.
3. Display granted read/write/send scopes; default to read or draft-only.
4. Run one harmless allowed operation and show provider-side revoke path.

### Sources

1. Fixture import/run succeeds with evidence schema.
2. Live adapter is listed by current help/status.
3. Bounded live run returns evidence or a precise failure class.
4. Duplicate, empty, denied, timeout, partial, and schema-change states are distinct.

### Obsidian

1. User chooses a new vault or explicitly approves an existing vault.
2. Preview collisions; do not overwrite `.obsidian` or notes.
3. Fixture run creates only expected non-secret notes.
4. Status reports managed paths and output location without reading unrelated notes.

## Resume decision table

| Observed state | Action |
|---|---|
| profile invalid | correct non-secret fields, validate again |
| pack file conflict | preserve it; show diff/choose another home or request review |
| offline fixture passed, model failed | keep fixture; repair model only |
| credential present, capability unverified | do not re-ask secret; rerun supported probe |
| one channel passed, the other failed | preserve passed channel; repair failed row only |
| optional service failed | keep core and other services; mark partial |
| source empty | confirm successful request and query; do not label source failure |
| source denied/schema changed | stop live collection; use fixture/file fallback |
| doctor failed after configuration | do not print/delete secrets; diagnose and resume probe |
| server foreground passed, service absent | preview supported service install; do not improvise unit syntax |
| vault already exists | status/preview first; never blind init |

## Evidence receipt

For each command/probe record only:

- timestamp, component, installed version or manifest hash;
- target OS/runtime and non-secret configuration choice;
- `passed`, `failed`, `blocked`, `skipped`, or `unverified`;
- redacted error class and artifact/output path;
- whether evidence is fixture, mocked, live, platform E2E, or user-observed.

Do not record raw API responses, token fragments, email addresses, user IDs, message text,
OAuth connection identifiers, SSH endpoints, or private company lists in a support receipt.
