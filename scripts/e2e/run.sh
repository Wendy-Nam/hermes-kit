#!/bin/sh
# Full student install on a fresh volume: scripts/e2e/run.sh <image>
set -eu
IMG="$1"; N="kit-e2e-$$"; HERE=$(cd "$(dirname "$0")" && pwd)
trap 'docker rm -f "$N" >/dev/null 2>&1 || true; docker volume rm -f "$N" >/dev/null 2>&1 || true' EXIT
wait_seed() {
  i=0; until docker logs "$N" 2>&1 | grep -qE '^\[kit\] (done|kit [0-9]+ already seeded)'; do
    i=$((i+1)); [ $i -lt 150 ] || { docker logs "$N" 2>&1 | tail -40; exit 1; }; sleep 2; done
}
prep() {
  docker cp "$HERE/." "$N:/tmp/e2e"; docker exec -u root "$N" chown -R hermes /tmp/e2e
  docker exec -d -u hermes "$N" /opt/hermes/.venv/bin/python /tmp/e2e/fake_openai.py; sleep 2
}
docker volume create "$N" >/dev/null
docker run -d --name "$N" -e DISCORD_BOT_TOKEN=dummy -v "$N:/opt/data" "$IMG" gateway run >/dev/null
wait_seed; prep
docker exec -u hermes -e HERMES_HOME=/opt/data "$N" /opt/hermes/.venv/bin/python /tmp/e2e/install_e2e.py stage1 || s1=1
docker restart "$N" >/dev/null; sleep 5; wait_seed; prep
docker logs "$N" 2>&1 | grep '^\[kit\]' | tail -8
docker exec -u hermes -e HERMES_HOME=/opt/data "$N" /opt/hermes/.venv/bin/python /tmp/e2e/install_e2e.py stage2 || s2=1
[ -z "${s1:-}${s2:-}" ] && echo "install e2e: passed" || { echo "install e2e: FAILED"; exit 1; }
