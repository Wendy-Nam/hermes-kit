# Support and evidence matrix

This matrix describes the checked-in 0.1 baseline and the rule for detecting newer helpers.
It is not a promise that a planned component works.

## Baseline observed in 0.1

| Capability | Checked-in implementation | Existing evidence | Honest label before a new run |
|---|---|---|---|
| secret-free profile | `wizard.html`, `kit.py validate` | Linux automated tests | implemented / Linux fixture-tested |
| isolated skill pack | `kit.py install` | Linux automated and local isolated run | implemented / Linux-tested |
| offline sample | `kit.py sample` | synthetic three-record output | fixture-verified only |
| model setup/doctor | delegates to installed `hermes` | no real model evidence in `VALIDATION.md` | configured-unverified until live probe |
| Telegram credential check | `kit.py connect` | mocked API test | implemented, live-unverified |
| Discord credential check | `kit.py connect` | mocked API test | implemented, live-unverified |
| channel message round trip | delegated to gateway/manual check | not recorded | unverified |
| desktop macOS | launcher opens wizard | no clean-device E2E | unverified |
| desktop Windows | launcher opens wizard | no clean-device E2E/ACL proof | unverified |
| Linux server foreground | documented | no real service evidence | unverified |
| background/reboot | upstream-dependent manual plan | not recorded | planned/unverified |
| jobs/funding source adapters | `sources.py`: file import, public ATS, bounded funding | Linux synthetic/unit tests; live endpoint not recorded | implemented / fixture-tested / live-unverified |
| Webshare/Groq/Apify/Composio optional services | `services.py` auth plus `runtime_connect.py` reviewed apply; Webshare exact-origin fetch and explicit Apify run | Linux synthetic endpoint/unit tests | implemented contracts / live-unverified / functionally unverified |
| Obsidian Markdown flow | `vault_flow.py init/run/status` | Linux synthetic/unit tests | implemented / fixture-tested / GUI and platform-unverified |
| OMH core | `omh_setup.py plan/install/check`, pinned OMH 2.0.5 in dedicated home | archive/layout/receipt/static smoke unit tests | implemented installer / host load, route, restart, delegated task live-unverified |
| OMH routing | pinned public recommendation mapping plus receipt-gated apply/rollback in `omniroute_setup.py` | offline route-map/application tests | implemented / live delegated task unverified |
| optional OmniRoute | `omniroute_setup.py plan/install/discover/connect/apply/check/rollback/routes`; local Linux Engine or macOS/Windows Docker Desktop | synthetic Linux/macOS/Windows and connector unit tests | implemented / real-platform-live-unverified / provider functionally unverified |
| automatic sending | intentionally not supported | none | out of safe workshop scope |

The current `kit.py setup` can reuse complete owner-matching channel pairs and add a missing
second channel, while refusing partial/conflicting pairs. Reuse does not revalidate the
preserved token, and doctor still does not prove a model response or channel round trip.
Report each gate separately.

## Detecting a newer checkout

The current checkout includes these helpers:

- `services.py`: `plan`, `status`, `connect`, `apply`, `check`, and explicit `run-apify` for
  selected optional services. `runtime_connect.py proxy-fetch` is the exact-origin Webshare
  transport. Auth/config/submission statuses remain distinct from `functional_verified`.
- `sources.py`: `jobs-import`, `ats`, and `funding` read-only adapters. Fixtures do not prove
  current live endpoint access or source permission.
- `vault_flow.py`: `init`, `run`, and `status` for a Markdown vault. It does not install the
  Obsidian GUI or community plugins and does not send messages.

The action names above are present now, but their arguments remain defined by local
`--help`. A setup agent must still inspect top-level/relevant help and use only the shown
interface. It becomes fixture- or live-verified only after the matching run succeeds now.

## Certification dimensions

Do not compress support into one checkmark. Record:

1. interface implemented;
2. contract/unit tested;
3. fixture/integration tested;
4. live provider/source tested;
5. platform clean-install tested;
6. restart/resume/removal tested;
7. workshop rehearsal tested.

Mac Apple Silicon, Mac Intel, Windows native, WSL2, Linux native, Linux Docker, and server
architectures are separate certification cells. Telegram, Discord, and both are separate
cells. A 128-combination plan/compiler test is not 128 live tests.

## Required outcome matrix

| Selected workflow | Core proof | Optional proof |
|---|---|---|
| job-posting buying signal | fixture plus bounded permitted live job evidence; company/signal output; evidence-backed draft | proxy/Apify only if selected and allowed |
| funded-startup headhunt | funding evidence kept separate from open-role evidence; score explains unknowns; draft | enrichment/Composio export if selected |
| procurement | plan vs actual notice labeled; stable IDs and dates | Sheets/CRM export if selected |
| overseas partner | allowed evidence source and country/partner-type criteria | translation/proxy/Apify only if selected |
| supplied file | import validation, dedupe, score, draft, local output | Composio or vault export if selected |

No workflow is live-verified solely because an API key was accepted, a fixture ran, or a
Markdown instruction exists.
