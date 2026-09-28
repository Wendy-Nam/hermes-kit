# syntax=docker/dockerfile:1
# hermes-kit image: upstream Hermes (pinned) + voice patches + selected core patches + rtk + kit seed.
# Build: set -a; . ./versions.env; set +a; docker build --build-arg HERMES_BASE_IMAGE --build-arg HERMES_VERSION --build-arg RTK_VERSION --build-arg KIT_VERSION -t hermes-kit:dev .
ARG HERMES_BASE_IMAGE
FROM ${HERMES_BASE_IMAGE}
ARG RTK_VERSION
ARG KIT_VERSION
ARG HERMES_VERSION
USER root

# rtk, checksum-verified (python urllib: the base image's tool set is not guaranteed)
RUN python3 - <<EOF
import hashlib, io, os, shutil, tarfile, urllib.request
base = "https://github.com/rtk-ai/rtk/releases/download/v${RTK_VERSION}/"
name = "rtk-x86_64-unknown-linux-musl.tar.gz"
blob = urllib.request.urlopen(base + name, timeout=60).read()
sums = urllib.request.urlopen(base + "checksums.txt", timeout=60).read().decode()
want = next(l.split()[0] for l in sums.splitlines() if l.strip().endswith(name))
assert hashlib.sha256(blob).hexdigest() == want, "rtk checksum mismatch"
with tarfile.open(fileobj=io.BytesIO(blob)) as t:
    m = next(m for m in t.getmembers() if os.path.basename(m.name) == "rtk" and m.isfile())
    with t.extractfile(m) as src, open("/usr/local/bin/rtk", "wb") as dst:
        shutil.copyfileobj(src, dst)
os.chmod("/usr/local/bin/rtk", 0o755)
EOF

# Patches fail the build when an anchor no longer matches = base version drift.
# The import checks run against a throwaway HERMES_HOME: importing Hermes creates state dirs, and
# anything left in /opt/data here would be copied (root-owned) into every new volume and break boot.
COPY patches /opt/kit/patches
RUN set -eu; PY=/opt/hermes/.venv/bin/python; \
    export HERMES_HOME=/tmp/kit-build-home HOME=/tmp/kit-build-home; mkdir -p /tmp/kit-build-home; \
    $PY /opt/kit/patches/core/patch-terminal-failure-status.py --root /opt/hermes --apply; \
    $PY /opt/kit/patches/core/patch-process-hint-names.py --root /opt/hermes --apply --no-enforce-hash; \
    sh /opt/kit/patches/voice/apply.sh; \
    for f in hook-overlap-skip hook-policy-serialization lifecycle-guard-sqlite kanban-interval kanban-progress-notify kanban-heartbeat-note budget-caps skills-view-cap cron-max-turns cron-iteration-outcome skills-compact vision-inbound skill-context-reuse; do \
      $PY /opt/kit/patches/core/patch-$f.py; \
    done; \
    cd /opt/hermes && $PY -c "import gateway.run, gateway.kanban_watchers_notifier, tools.terminal_tool, hermes_cli.plugins_dispatch, agent.prompt_builder, agent.system_prompt, tools.skills_tool, tools.budget_config, cron.scheduler"; \
    rm -rf /tmp/kit-build-home; \
    leaked="$(find /opt/data -mindepth 1 -user root)"; [ -z "$leaked" ] || { echo "build leaked into /opt/data: $leaked"; exit 1; }

# Obsidian community plugins for both vault templates, pinned (all MIT)
COPY seed /opt/kit/seed
RUN python3 - <<'EOF'
import os, urllib.request
plugins = [("dataview", "blacksmithgu/obsidian-dataview", "0.5.70"),
           ("obsidian-tasks-plugin", "obsidian-tasks-group/obsidian-tasks", "8.4.0"),
           ("tasknotes", "callumalpass/tasknotes", "4.13.5")]
for vault in ("work", "personal"):
    for pid, repo, ver in plugins:
        d = f"/opt/kit/seed/vaults/{vault}/.obsidian/plugins/{pid}"
        os.makedirs(d, exist_ok=True)
        for a in ("main.js", "manifest.json", "styles.css"):
            with urllib.request.urlopen(f"https://github.com/{repo}/releases/download/{ver}/{a}", timeout=60) as r, open(f"{d}/{a}", "wb") as f:
                f.write(r.read())
EOF

COPY bin /opt/kit/bin
COPY plugins /opt/kit/plugins
COPY rootfs/etc/cont-init.d/10-kit-seed /etc/cont-init.d/10-kit-seed
RUN chmod 0755 /etc/cont-init.d/10-kit-seed /opt/kit/bin/*.py && echo "${KIT_VERSION}" > /opt/kit/VERSION && echo "${HERMES_VERSION}-k${KIT_VERSION}" > /opt/kit/RELEASE_VERSION && rtk --version
