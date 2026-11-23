# AGENTS.md — Autonomous & Human-in-the-Loop Setup Guide for `hermes-kit`

If a user gives you this repository (or its GitHub URL) and asks you to **install, migrate, or configure `hermes-kit` on their VPS over SSH**, follow this runbook. Your job is to handle all remote server operations automatically and **only pause for human input at the explicit Human Gates below**.

---

## Hard Safety Rules (Never Violate)

1. **Never ask the user to paste secrets into chat.** Tokens (`DISCORD_BOT_TOKEN`, `KIT_OMNIROUTE_PASSWORD`, API keys) must never be typed into chat or printed in logs. At Secret Gates, ask the user to enter them directly in their own terminal (`read -rs`) or in Discord `/setup`.
2. **Single Active Rule (for migrations).** Never run the same Discord bot token, cron jobs, OAuth sessions, or Syncthing Device ID on two servers simultaneously. Freeze the old VPS first (`docker compose stop && docker update --restart=no <cid>`).
3. **Non-Destructive Guarantee.** Never delete `/opt/data`, `.env`, `auth.json`, `vaults/`, or `state.db`. Always use `./bin/hermes-kit-deploy.sh`, which creates atomic pre-migration backups automatically.
4. **Verify Mechanically.** Never claim success based on "looks fine". Always finish with `./bin/hermes-kit-deploy.sh verify` (checks build-time voice patches, OMH routing, installed components, and `state.db` `PRAGMA quick_check`).

---

## Step 1 — Inspect First (Read-Only)

Ask the user for their SSH target (e.g., `root@<VPS-IP>` or SSH alias) if not already provided, then run a read-only probe:

```bash
ssh <SSH_TARGET> 'docker ps --format "{{.Names}}\t{{.Image}}\t{{.Status}}" && free -m && df -h /'
```

Decide the path automatically from the output:
- **No running Hermes container** → **Fresh Install**
- **Existing Hermes container** → **In-Place Migration**
- **User also wants multi-provider routing** → add `--with-omniroute`
- **User also wants Korean job-hunt automation** → run `job-hunt` step after Hermes is up

---

## Step 2 — Human Gate: Secrets (Only When Missing)

Check if `/opt/hermes-kit/.env` (or existing container `.env`) already has `DISCORD_BOT_TOKEN` (and `KIT_OMNIROUTE_PASSWORD` if `--with-omniroute`).

If missing, **stop and give the user this exact terminal snippet** to run locally (never ask them to paste values in chat):

```bash
read -rs -p "DISCORD_BOT_TOKEN: " DISCORD_BOT_TOKEN; echo
# Only if using OmniRoute:
read -rs -p "KIT_OMNIROUTE_PASSWORD: " KIT_OMNIROUTE_PASSWORD; echo
export DISCORD_BOT_TOKEN KIT_OMNIROUTE_PASSWORD
```

---

## Step 3 — Deploy or Migrate via CLI

All heavy lifting is handled by [`bin/hermes-kit-deploy.sh`](bin/hermes-kit-deploy.sh) (supports both local execution and `--ssh <user@host>`):

- **Fresh install (base stack: Hermes v0.23.3-k19 + Syncthing):**
  ```bash
  ./bin/hermes-kit-deploy.sh --ssh <SSH_TARGET> install
  ```
- **Fresh install + OmniRoute 3.8.54 (stock image, hardened):**
  ```bash
  ./bin/hermes-kit-deploy.sh --ssh <SSH_TARGET> install --with-omniroute
  ```
- **In-place non-destructive migration (preserves `.env`, `auth.json`, vaults, sessions, OMH chains):**
  ```bash
  ./bin/hermes-kit-deploy.sh --ssh <SSH_TARGET> migrate --with-omniroute
  ```
- **Optional — Install/update `Wendy-Nam/hermes-job-hunt-for-korean` natively:**
  ```bash
  ./bin/hermes-kit-deploy.sh --ssh <SSH_TARGET> job-hunt
  ```

---

## Step 4 — Human Gate: Discord `/setup` & OAuth

Once the container is up, fetch the invite link (read-only, no secrets printed):

```bash
ssh <SSH_TARGET> 'docker logs $(docker ps -qf name=hermes | head -1) 2>&1 | grep "\[kit\] 봇 초대:" | tail -1'
```

Ask the user to:
1. Invite the bot to a private Discord server using that link.
2. Run `/setup` in Discord and complete steps **1 → 4** (Model login/key → Gemini key → Job kit → **4. 권장 설정 적용**, which installs OMH v5.0.0 and role profiles).
3. *(If OmniRoute is enabled)* Open the dashboard via `/setup → 고급 설정 → OmniRoute 연결 → 1. 대시보드 열기` (or SSH tunnel `ssh -L 20128:127.0.0.1:20128 <SSH_TARGET>`) and connect their OAuth/API providers.

---

## Step 5 — Wire OmniRoute Combos + OMH 12-Category Routing & Verify

> **Adapt to the user's own resources:** The provider list in `docs/omniroute-providers.md` is a reference catalog, not a requirement. Even if the user only connected 1–2 providers (e.g., ChatGPT OAuth, Gemini, or a free aggregator), `preset plan` / `preset apply` automatically builds combos only from their active connections and wires OMH accordingly. If the user wants custom combos tailored to their specific models, build them via OmniRoute API or `/setup → 2. 모델 고르기`.

Once the user confirms they connected providers in OmniRoute (and finished Step 4):

```bash
# Preview combo plan first (dry-run, privacy-safe: training-free providers never enter private combos)
./bin/hermes-kit-deploy.sh --ssh <SSH_TARGET> preset plan

# Apply combos + wire OMH 12-category chains + quota-aware routing patches
./bin/hermes-kit-deploy.sh --ssh <SSH_TARGET> preset apply

# Final mechanical verification (read-only)
./bin/hermes-kit-deploy.sh --ssh <SSH_TARGET> verify
```

Ask the user to click **적용하기 (재시작)** in Discord `/setup` (or restart the Hermes container) and run `/doctor` in Discord to confirm all green.

---

## Reference Docs in This Repo
- [`docs/omniroute-setup-guide.md`](docs/omniroute-setup-guide.md) — OmniRoute 3.8.54 tuning, feature flags, compression bundles, role combos
- [`docs/omniroute-providers.md`](docs/omniroute-providers.md) — Provider privacy tiers (`PRIVATE_PROVIDERS` vs `TRAINING_FREE_PROVIDERS`)
- [`docs/ops/vps-migration-playbook.md`](docs/ops/vps-migration-playbook.md) — Full VPS-to-VPS cutover, encrypted backup, and rollback playbook
