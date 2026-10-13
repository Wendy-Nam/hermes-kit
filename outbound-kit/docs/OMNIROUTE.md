# Optional OmniRoute + OMH routing

OmniRoute is an **optional local-Docker add-on** for Linux servers and
macOS/Windows Docker Desktop. It is not required for the
workshop's local model, fixture, sourcing, draft, channel or vault flow.

The helper installs a private digest-pinned container and then exposes explicit,
reviewable connect/apply/rollback phases:

```sh
python3 omniroute_setup.py plan --config setup.json --home ~/.hermes-outbound
python3 omniroute_setup.py install --config setup.json --home ~/.hermes-outbound
python3 omniroute_setup.py discover --config setup.json --home ~/.hermes-outbound
python3 omniroute_setup.py connect --config setup.json --home ~/.hermes-outbound \
  --chat-models openai/gpt-example --strong-models openai/gpt-example
python3 omniroute_setup.py apply --config setup.json --home ~/.hermes-outbound \
  --bindings omh-bindings.json
python3 omniroute_setup.py check --config setup.json --home ~/.hermes-outbound
python3 omniroute_setup.py check --live --config setup.json --home ~/.hermes-outbound
```

`install` prompts for the dashboard password without echoing it. Do not put the
password in `setup.json`, a command argument, an AI chat, a workshop form or a
support log.

## What the one command does

- requires `omniroute_enabled: true`;
- supports local Linux/amd64 Docker Engine plus Intel/Apple-Silicon macOS and
  x64/ARM64 Windows hosts running Docker Desktop in Linux-container mode;
- verifies Docker Engine, Docker Compose, a local Docker context and at least
  4 GiB assigned to the Docker Engine/VM (not merely host RAM);
- creates an isolated `hermes-outbound-omniroute` Compose project and named volume;
- stores the dashboard password in a mode-`0600` local env file on POSIX; on
  Windows it restricts the directory before secret creation and then restricts
  the env file to the current user with `icacls`, refusing persistence if either
  ACL step fails;
- binds the dashboard/API only to `127.0.0.1:20128`;
- pulls an immutable image digest and starts the container;
- verifies the Compose project/service, exact image, running state and exact
  loopback port binding before checking `/healthz`;
- records a non-secret install receipt.

`install` itself does **not** expose the dashboard publicly, connect a provider
account, create an inference key, pick a model, change Hermes' main model, apply
an OMH route or prove a delegated task. The later commands perform only their
named phase; provider OAuth/API-key consent remains in the private dashboard.

The image is pinned to:

```text
ghcr.io/wendy-nam/hermes-kit:omniroute-rtk-json-3@
sha256:1572375ba665cad6b46273257f2746834421191ee201cf5cb14b28e4a1cfc979
```

The registry described this digest as a single `linux/amd64` manifest when checked
on 2026-10-13. The generated Compose file therefore sets `platform: linux/amd64`.
Intel hosts run it natively. Apple-Silicon and Windows ARM64 Docker Desktop require
amd64 emulation; the preflight reports this as required-but-unverified. ARM Linux
servers remain unsupported. A tag can move; the installed digest cannot.

## Platform evidence and limits

| Target | Implemented contract | Validation status |
|---|---|---|
| Linux server, amd64 | Local Engine, Linux containers, Compose, >=4 GiB Engine RAM | deterministic tests; no live daemon started in this workspace |
| macOS Intel | Local Docker Desktop Linux VM | mocked contract tests; real device untested |
| macOS Apple Silicon | same, with explicit `linux/amd64` emulation | mocked contract tests; real device/emulation untested |
| Windows x64 | Docker Desktop Linux containers, local named-pipe context, current-user NTFS ACL | mocked contract tests; real device/ACL untested |
| Windows ARM64 | same, with explicit `linux/amd64` emulation | mocked contract tests; real device/emulation untested |
| WSL2 shell | treated as Linux; only a local Unix Docker endpoint and amd64 Engine pass | deterministic contract only |

The helper does not install Docker Desktop, enable WSL2, change Docker contexts,
change Docker daemon/VM settings or enable emulation. A remote `tcp://` context is
refused. Those prerequisites remain visible user/admin actions. Accordingly,
“supported in code” does not mean “live-validated on every device.”

## Honest state model

| State | Evidence |
|---|---|
| selected | `omniroute_enabled: true` |
| configured | owned Compose and private env files exist |
| installed | digest-pinned owned container identity and loopback binding were verified, then a receipt was written |
| dashboard healthy | loopback `/healthz` answered |
| provider authenticated | a user connected a provider in the private dashboard |
| model discovered | OmniRoute returned the model for that exact connection |
| model tool-tested | a two-turn tool call and tool-result response passed on that connection |
| routing applied | Hermes provider/delegation and OMH route documents refer to tested combos |
| live | after restart, a real delegated task used the expected connection |

Plain `check` proves local files, secret-file shape, POSIX file mode, a saved
container identity result and current loopback health. On Windows it reports ACL
privacy as unknown because it does not parse localized `icacls` output; the install
receipt means ACL application succeeded at install time, not that a later ACL change
was ruled out. It does not re-inspect the live
container, so current health alone must not be treated as fresh identity proof.
`check --live` additionally prompts privately for the dashboard password, verifies
the exact installation-owned key and combo IDs still exist, and repeats every
selected model's two-turn tool call. It still does not claim that a restarted Hermes
process used the route.

## Connect, apply and rollback

After the user connects provider accounts in the loopback dashboard, `discover`
lists only active non-browser-scraper connections and chat-capable model IDs.
`connect` then:

1. creates a fresh no-log inference key restricted to the selected connection IDs;
2. tests each selected route with a forced `kit_echo` tool call and a second turn
   that consumes the tool result;
3. only after all probes pass, creates separate priority `chat` and `strong` combos;
4. saves the inference key as `KIT_OMNIROUTE_API_KEY` in the private local `.env`
   and a non-secret ownership receipt under `omniroute/`.

On failure it deletes only the newly created object IDs and restores only the exact
local key line it just changed. A new connect is refused while an old route is
applied; run rollback first.

`apply` accepts a non-secret JSON object whose keys are public OMH aliases and whose
values are either `chat` or `strong`, for example:

```json
{
  "gpt-6-astra": "strong",
  "kimi-k3": "strong",
  "deepseek-flash": "chat",
  "glm-5.3": "chat"
}
```

Every OMH category must retain at least one explicitly bound candidate. The file
must not contain provider keys, cookies, OAuth tokens, dashboard passwords or the
inference key. `apply` writes the Hermes 0.21.7 named-provider contract:

```yaml
providers:
  kit-omniroute:
    base_url: http://127.0.0.1:20128/v1
    key_env: KIT_OMNIROUTE_API_KEY
    api_mode: chat_completions
```

It routes delegation to the tested strong combo and writes OMH's
`model_provider_routes/v1` and `mixture_chain_overrides/v1` documents under
`.omh/routing`. If Hermes already has a concrete direct main model, it moves that
exact route to `fallback_providers` before switching main chat to the tested chat
combo. Without a safe direct fallback, main chat stays unchanged. A conflicting
named provider, delegation route or fallback chain blocks with a manual-merge
instruction; it is never overwritten.

The config and route files are replaced atomically and a private rollback snapshot
is retained. `rollback` restores that snapshot only when the current config hash
still matches the applied receipt; post-apply user edits intentionally block
automatic rollback. Apply and rollback both require a Hermes restart. Neither
command stops a process itself.

The older offline-only mapping export remains useful for preview:

```sh
python3 omniroute_setup.py routes \
  --config setup.json \
  --bindings tested-omniroute-bindings.json \
  --output staged-omh-routes.json
```

`routes` accepts alias-to-combo strings and writes no runtime config. Its
`mapping_only_not_applied_or_tool_tested` claim is deliberately weaker than
`connect` plus `apply`.

## Actual donor architecture

The public donor is `Wendy-Nam/hermes-kit` at commit
`858fd1b7d2b25a1a3844dc71e8005493a49df228`.

- `advanced/docker-compose.omniroute.yml` runs the add-on as a second project,
  keeps the dashboard on loopback, generates JWT/API signing secrets inside the
  private volume, requires inference API keys, and limits memory to 2 GiB.
- `advanced/omniroute-rtk-envelope/Dockerfile` builds on OmniRoute `next-web` digest
  `sha256:3c8698a83d40205914aa9e343fd3b1378c4ba8940a3a3adb5ecfc7f0b1b9cb61`.
  It adds the Hermes JSON RTK envelope and context-reconciliation compatibility
  patches. This outbound helper consumes the already-published final image digest;
  it does not rebuild that image.
- `plugins/kit-setup/omniroute_setup.py:configure` creates installation-scoped
  provider/combination/key objects, limits the inference key to the selected
  connection, performs a two-turn tool probe, then changes **delegation only**.
- `plugins/kit-setup/omniroute_mode.py:connect_mode` discovers active dashboard
  connections and model IDs, rejects browser-session scraper providers, tool-tests
  each selection, creates separate `chat` and `strong` priority combinations and
  keeps the prior direct main model as a fallback. It does not switch main chat
  when no working direct fallback exists.
- `plugins/kit-setup/omh_enhancements.py:compose` emits
  `model_provider_routes/v1` and `mixture_chain_overrides/v1` documents. A stable
  alias maps each provider/model identity exactly once, which avoids ambiguous
  fallback positions.
- `plugins/kit-setup/omh_routing.py` installs an additional quota/readiness mapper
  for OmniRoute-managed combinations. It is a version-sensitive patch layer, not
  part of this standalone deployment helper.

The donor's safety properties worth keeping are: no public dashboard, scoped
no-log inference keys, tool-call testing before config mutation, preservation of
the direct main-model fallback, installation-owned object names/IDs, atomic local
updates, and removal of only resources whose exact IDs were recorded by that
installation.

## Exact OMH source and mappings

The donor pins upstream OMH as follows:

| Field | Value |
|---|---|
| Repository | `https://github.com/rlaope/oh-my-hermes` |
| Source/package version | `2.0.5` (`pyproject.toml`) |
| Commit | `b84f096e59d50fc933ed4b43fd36675e8cff593a` |
| Archive SHA-256 | `3a27c03301cc7f4dcb96a1476bd5a38bef57117148ba7f7e7aba4f15fffe608a` |
| License | MIT |
| Definition | `src/plugin_bundle/omh/hermes_delegation.py:HERMES_MIXTURE_CATEGORY_CHAINS` |
| Override path | `$OMH_HOME/routing/model-chains.json` |
| Override schema | `mixture_chain_overrides/v1` |

The archive hash above was independently matched before reading the definitions.
The public default routes are:

| Category | Ordered aliases and effort |
|---|---|
| ultrabrain | `gpt-6-astra:xhigh` |
| deep | `gpt-5.6-terra:high -> deepseek-flash:high` |
| architect | `claude-fable-5-1:xhigh -> gpt-6-astra:xhigh -> kimi-k3:xhigh` |
| unspecified-high | `kimi-k3:medium -> claude-opus-5:medium` |
| unspecified-low | `glm-5.3:low -> deepseek-flash:low -> claude-opus-5:low` |
| quick | `glm-5.3-flash:low -> kimi-k3:low -> gpt-5.6-luna:low -> claude-fable-5-1:low` |
| writing | `kimi-k3:medium -> qwen3-coder:medium -> gemini-3.1-pro:medium` |
| visual-engineering | `claude-fable-5-1:high -> kimi-k3:high` |
| artistry | `gemini-3.1-pro:high -> claude-fable-5-1:high -> kimi-k3:high` |
| capable | `claude-fable-5-1:medium -> claude-opus-5:medium -> kimi-k3:medium -> glm-5.3:medium` |
| simple-work | `gpt-5.6-luna:low -> deepseek-flash:low -> claude-haiku-4-5:low` |
| deep-work | `gpt-6-astra:high` |

These are editorial recommendations, not a promise that an account serves any of
the named models. `omniroute_setup.route_documents()` is the deterministic offline
adapter: it accepts only exact public aliases mapped to already tested OmniRoute
combo IDs, preserves category order and effort, omits unavailable aliases, and
reports categories left with no candidate. It never silently maps Astra to Sol,
one Claude tier to another, or one model family to another.

The standalone function produces the same two public schema families used by the
donor and labels its output `mapping_only_not_applied_or_tool_tested`. The runtime
connector adds the missing evidence boundary: `connect` obtains current discovery
and two-turn probe evidence; `apply` then writes those documents and records a
rollback snapshot. Alias-to-chat/strong bindings remain an explicit user-reviewed
semantic choice, not an inferred model substitution.

## Private-repository inspection boundary

The personal repository contains a separately vendored, wrapper-oriented OMH tree
whose metadata reports `1.0.3`; it is not the pinned public `2.0.5` source tree.
That version number alone does not establish compatibility or incompatibility.
Its `AGENTS.md` and `docs/DIRECTION.md`
explicitly state that OMH is a Hermes-native wrapper orchestration layer and **not
an LLM router or network service**. That code has useful deterministic configuration
and evidence-boundary patterns, but it is not the OmniRoute daemon adapter used by
the donor above.

No personal routing registry, model-usage ledger, vault content, account setting,
token or credential file was read or copied. Job/headhunt material was not used:
it is unrelated to OmniRoute runtime compatibility, and copying it would expand the
privacy and workshop scope without helping this installer.

The one personal-repository adapter inspected was code-only:
`plugins/omh/omh_provider_mapper.py`. Its SHA-256 is
`9f22c94cf302a3face6f5d950e67d6cb7a2565380a275d58686476d9119c9dcb`, exactly
the same bytes as the public donor's
`patches/omh-routing/files/omh_provider_mapper.py`. The adjacent
`plugins/omh/route_readiness.py` is likewise byte-identical to the public donor
(`527503084166788fee4c73a7e76feeeb0b68944e308c03e466e22a622d0329c1`).
Those two matching files do not imply that either whole plugin tree is identical.
They do establish that this reusable adapter logic is already in the public donor,
so no private configuration needs to be copied.

That adapter does handle:

- exact aliases and bounded same-family/version classification, including the
  public `deepseek-flash -> deepseek-v4.1-flash` editorial alias;
- model discovery with `/api/combos` as the authoritative executable routes;
- `/api/providers` active/test/quota readiness, including exhausted rolling windows;
- `/api/models` only as a secondary catalog hint;
- deterministic usable-provider ordering and reporting of exact vs family-only
  matches.

It does **not** install OmniRoute, log a user into a provider, perform OAuth, create
the least-privilege inference key, run the two-turn model probe, support a public
cloud/desktop endpoint, or discover a daemon outside its fixed internal
`http://omniroute:20128` address. It reads an `OMNIROUTE_API_KEY` management token
from the process environment; this is runtime authentication, not credential
onboarding. Its public scenario checker is
`patches/omh-routing/verify.py`, while the donor's unit coverage for installation
ownership, probe-before-mutation and rollback lives under
`plugins/kit-setup/tests/test_omniroute_setup.py`,
`test_omniroute_vision.py`, `test_omh_routing.py` and
`test_omh_enhancements.py`.

## Remaining live gates

The local Docker deployment, credential-scoped connector, config application and
rollback are implemented as separate commands. This is still not a truthful
"provider login in one click": provider authentication may require OAuth/web
consent, CAPTCHA or account-specific terms and must remain user-visible.

Before calling the route live, all of the following are still required:

1. authorize each provider in the private loopback dashboard;
2. run `discover`, `connect`, `apply`, restart Hermes, then `check --live`;
3. observe one main conversation turn and one delegated task selecting the expected
   installation-owned combo;
4. exercise rollback after a deliberate stopped-container failure;
5. repeat the flow on real Intel/Apple-Silicon macOS and x64/ARM64 Windows devices.

No live daemon, provider account or Hermes process was changed in the Linux cloud
workspace. The accurate product wording is "one-command private OmniRoute install,
then guided provider consent and verified apply," not "fully authenticated one click."

## Third-party notice for the OMH mapping

The category names, ordered model aliases and reasoning-effort defaults in
`omniroute_setup.py` are derived from oh-my-hermes at the commit and archive hash
listed above. That project is distributed under the following MIT license:

> MIT License
>
> Copyright (c) 2026 oh-my-hermes contributors
>
> Permission is hereby granted, free of charge, to any person obtaining a copy
> of this software and associated documentation files (the "Software"), to deal
> in the Software without restriction, including without limitation the rights
> to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
> copies of the Software, and to permit persons to whom the Software is
> furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in all
> copies or substantial portions of the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
> IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
> FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
> AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
> LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
> OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
> SOFTWARE.
