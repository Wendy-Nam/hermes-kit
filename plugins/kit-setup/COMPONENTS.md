# Student component installation contract

Basic job/sales/mkt/pm/dev skills ship in `seed/kits`. They work without a
private repository access code. `components.retry_components()` persists the
selected IDs separately from the core image's `.kit-version`, so interrupted
component installation can be retried without re-seeding user configuration.

Each component has a `manifest.json` with `schema_version: kit-component/v1`,
`id`, semantic `version` (three integers), and a `files` mapping of relative
paths to SHA-256 values. Only inventoried files are installed. Links, path
traversal, same-version content changes, and downgrades are rejected. A target
with changed or added user files is preserved and reported, never overwritten.
A staged directory replaces an unchanged target; failed swaps restore the old
one. State writes use atomic replacement under a process lock. A process crash
between directory replacement and receipt persistence can require operator
reconciliation; it does not authorize overwriting an unrecognized target.

Optional private bundles require an explicit 40-character Git commit and an
access code. Their top-level manifest is `kit-bundle/v1`, includes a semantic
version, and lists component IDs. Every component resides at `kits/<id>` and
uses the above manifest. Validate the entire bundle before installing its
components. Each component is an independent transaction; the bundle is not a
cross-component transaction. Private bundles never install plugins or scripts.

## Optional upstream OMH

`upstream_omh.install_upstream_omh(data_dir, routing=..., host_version=...)`
installs the upstream **core** workflow pack. The student's configured aux
provider/model routes every task category, at OMH 2.0.5's shipped chain-head
effort for that category capped at `high` (ultrabrain/deep/architect/artistry/
visual-engineering/deep-work `high`; writing/capable/unspecified-high `medium`;
quick/simple-work/unspecified-low `low`). No instructor accounts, personal chains,
anonymous pools, or private settings are copied.

Routing is upstream's own: `omh_delegate_route` writes `delegation.*` for the next
dispatch from `.omh/routing/model-chains.json` + `model-providers.json`, and walks
fallback candidates itself. Hermes 0.21.2 has no `delegate_task(routing=...)`; the
kit never depends on one (k6's per-dispatch design did, which is why its image
never published).

`omh_enhancements` owns only (a) those two documents, composed from the delegation route (the aux model, or the main model when no aux is set)
plus per-task chains saved in /setup (one to five models each, merged across saves,
each probed with the student's keys first), and (b) one addition to the upstream
`pre_tool_call` hook. A spawn whose live delegation keys OMH did not write for this
session (upstream's locked `route-restore.json` record, dropped at turn end) is sent
back once per session turn asking for `omh_delegate_route`; the retry dispatches, so
a model that cannot route (tool missing, chain exhausted to the baseline) is never
stuck. For a routed spawn it appends OMH's native `calibration_for_route` text to
each child's context. OMH writes it for
`high` and above; at `medium` the family text is borrowed without raising the effort (as on
the author's server), `low` gets none; the kit's own OmniRoute combo is calibrated as its
single underlying model. Internal errors dispatch unchanged and the hook never writes config. Enabling also appends a
marked `omh_delegate_route` rule to a SOUL that never mentions it (students seeded
before k7); boot upgrades an earlier calibration receipt in place, keeping task chains.
It is enabled with the basic pack and can be turned off in /setup, which restores
the upstream hook byte-for-byte. A changed delegation route (model selection or OmniRoute
connection) is synced into every task category the student did not assign; routing
documents edited outside the kit are preserved, never overwritten.

Beyond `--core`, `upstream_omh.WORKFLOW_SKILLS` (plus `KIT_WORKFLOW_SKILLS` for the
selected job kits) are added with upstream's own installer: their upstream render is
written, then `install_skill_pack` manifests them, and upstream refreshes on-disk
skills whatever profile is recorded, so they survive `omh update`. Failure here
leaves the core pack installed and is reported. `omh update` replaces the hook file:
calibration and route requests stop, and /setup reports the files as changed. For a route whose model family OMH
cannot name (a combo that may switch vendors), a fixed route floor is appended at
any effort. Calibration is computed in-process from the OMH venv when the
interpreter version matches, with the subprocess as fallback, cached per model/effort.

Pinned source: `rlaope/oh-my-hermes` tag `v2.0.5`, commit
`b84f096e59d50fc933ed4b43fd36675e8cff593a`, codeload archive SHA-256
`3a27c03301cc7f4dcb96a1476bd5a38bef57117148ba7f7e7aba4f15fffe608a`.
The installer accepts Hermes `>=0.21.1,<0.22.0`; it preserves existing OMH
installations. It installs in an isolated environment and exposes its command
at `~/.local/bin/omh`. Setup uses core skills, memory mode off, no TUI change,
no menu bar, and the Hermes executor. Existing main model settings remain.
On failure, activation config is restored and failed artifacts are kept in the
installation's recovery folder.

A real local isolated installation verified the pinned package, setup's
import/register smoke, configuration preservation, and route file creation.
This is **not** live Hermes child execution evidence. Restart and verify an
actual OMH tool and a harmless delegated task before claiming operational
readiness. `scripts/omh-enhancement-smoke.py` runs the real upstream install on the
shipped Hermes runtime and checks every category's route, fallback, calibration
and profile isolation without model requests. The instructor's personal patches
are not included. The upstream source package has no runtime dependencies; its
Python build tooling is resolved by pip and is not an offline bundled wheel.

For separately reviewed plugin archives, `components.install_optional()`
accepts an explicit trusted registry mapping a source directory and pinned
manifest SHA-256. It stages the verified OMH plugin only; activation and host
compatibility checks are separate. No registry entry is shipped by default.

## Optional OmniRoute API connection

`omniroute_setup.configure(data_dir, password, provider, api_key, model)` accepts
only Gemini, OpenAI, or Anthropic API credentials and an explicit model ID.
It talks to the compose service at `http://omniroute:20128`, uses the management
password only in memory, and creates installation-scoped connection/combo/key
names. The combo has one model and one explicit connection; its inference key
allows only that connection. No account pool or unrelated router settings change.

Two real inference requests must complete a `kit_echo` tool round trip before
local configuration changes. A text-only reply to the first request is a failure.
On success only Hermes delegation changes to `kit-omniroute`; the main model and
its existing fallback configuration are preserved. The inference key lives in
`.env` at mode 0600. Retry journals contain IDs and model metadata, not credentials.
Previously successful kit objects are retired only by their recorded IDs after a
new configuration passes. Failed attempts can leave inactive/unreferenced kit
objects for a retry to reuse; unrelated objects are never removed. Lost journals
need operator reconciliation and must not be reconstructed from credentials.

Management API shape was checked against the running OmniRoute 3.8.51 compiled
routes and official source. Mock integration tests cover success, two-turn failure,
retry, changed user combos, scoped cleanup, and local rollback. A real isolated OmniRoute 3.8.51 container was also tested on an internal
Docker network with a deterministic fake upstream (no production credentials
or network egress). Provider creation, connection-pinned combo, scoped key,
two-turn tool round trip, local delegation update, and a second idempotent setup
all passed. Hermes 0.21.2 resolved the installed custom provider to the expected
URL and inference key while preserving the main model. The test container and
network were removed. Paid provider behavior and the student's real account
entitlement remain checked only when the student runs setup.

## Optional Cline model selection

Connect your own Cline account using the OmniRoute dashboard's OAuth flow.
The kit does not register Cline credentials or copy an instructor's accounts,
models, or routes. `python cline_catalog.py --list` explicitly fetches the public
pricing catalog once; it does not run inference or modify configuration.

Only candidates with explicit zero prompt/completion prices and zero in every
other advertised price field are listed. Missing cache prices remain **unknown**.
The check expires after 15 minutes (the library permits at most one hour).
A `:free` suffix, successful response, or negative account balance does not prove
that a model is free. Prices and promotional access can change; refresh before
selection and check your account's API entitlement. The catalog can also include
non-chat models, so listing is not a compatibility recommendation.

`cline_catalog.propose_removals()` only proposes removal of positive-price or
unknown-price Cline entries from supplied model lists. It preserves other entries
and metadata, rejects stale evidence, and never calls a management API. Review
fresh dashboard settings before applying any proposal. Separately verify a small,
explicitly authorized two-turn tool call before using a model for delegation;
price verification does not establish tool support or account access.

## Optional JS page extractor

`crawl4ai_setup.install(data_dir)` creates `crawl4ai-env` on the data volume with
`crawl4ai==0.9.4` and `playwright==1.63.0`, whose chromium-headless-shell revision
1243 is the one the Hermes image ships; no browser is downloaded. It writes
`bin/jsextract` (public http(s) only; private, loopback and link-local addresses
refused) and the `kit-tools/js-page-extract` skill. Default extraction remains
`web.extract_backend: parallel` (keyless). `uninstall` removes all of it.
`scripts/jsextract-smoke.py` verifies install, refusal and rendering in the image.
