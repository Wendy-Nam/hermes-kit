#!/bin/sh
# Full student install on a fresh volume: scripts/e2e/run.sh <image>
set -eu
# With OMNI_IMAGE set, also runs OmniRoute mode against a real OmniRoute container.
IMG="$1"; N="kit-e2e-$$"; HERE=$(cd "$(dirname "$0")" && pwd); NET="kit-e2e-net-$$"; O="kit-e2e-omni-$$"
trap 'docker rm -f "$N" "$O" >/dev/null 2>&1 || true; docker volume rm -f "$N" >/dev/null 2>&1 || true; docker network rm "$NET" >/dev/null 2>&1 || true' EXIT
docker network create "$NET" >/dev/null
wait_seed() {
  i=0; until docker logs "$N" 2>&1 | grep -qE '^\[kit\] (done|kit [0-9]+ already seeded)'; do
    i=$((i+1)); [ $i -lt 150 ] || { docker logs "$N" 2>&1 | tail -40; exit 1; }; sleep 2; done
}
prep() {
  docker cp "$HERE/." "$N:/tmp/e2e"; docker exec -u root "$N" chown -R hermes /tmp/e2e
  docker exec -d -u hermes -e FAKE_HOST=0.0.0.0 "$N" /opt/hermes/.venv/bin/python /tmp/e2e/fake_openai.py; sleep 2
}
docker volume create "$N" >/dev/null
docker run -d --name "$N" --network "$NET" --network-alias kit-hermes -e DISCORD_BOT_TOKEN=dummy -v "$N:/opt/data" "$IMG" gateway run >/dev/null
wait_seed; prep
docker exec -u hermes -e HERMES_HOME=/opt/data "$N" /opt/hermes/.venv/bin/python /tmp/e2e/install_e2e.py stage1 || s1=1
docker restart "$N" >/dev/null; sleep 5; wait_seed; prep
docker logs "$N" 2>&1 | grep '^\[kit\]' | tail -8
docker exec -u hermes -e HERMES_HOME=/opt/data "$N" /opt/hermes/.venv/bin/python /tmp/e2e/install_e2e.py stage2 || s2=1
if [ -n "${OMNI_IMAGE:-}" ]; then
  docker run -d --name "$O" --network "$NET" --network-alias omniroute -e INITIAL_PASSWORD=e2e-omniroute-password \
    -e REQUIRE_API_KEY=true -e JWT_SECRET=e2e-jwt-secret-e2e-jwt-secret-e2e-jwt -e API_KEY_SECRET=e2e-api-secret-e2e-api-secret-e2e \
    --entrypoint sh "$OMNI_IMAGE" -c 'exec /app/check-permissions.sh node dev/run-standalone.mjs' >/dev/null
  i=0; until docker exec "$N" /opt/hermes/.venv/bin/python -c "import socket;socket.create_connection(('omniroute',20128),3)" >/dev/null 2>&1; do
    i=$((i+1)); [ $i -lt 90 ] || { echo "omniroute did not start"; docker logs "$O" 2>&1 | tail -20; exit 1; }; sleep 3; done
  docker exec -u hermes -e HERMES_HOME=/opt/data "$N" /opt/hermes/.venv/bin/python /tmp/e2e/install_e2e.py stage3a || s3=1
  docker stop "$O" >/dev/null
  docker exec -u hermes -e HERMES_HOME=/opt/data "$N" /opt/hermes/.venv/bin/python /tmp/e2e/install_e2e.py stage3b || s3=1
fi
[ -z "${s1:-}${s2:-}${s3:-}" ] && echo "install e2e: passed" || { echo "install e2e: FAILED"; exit 1; }
