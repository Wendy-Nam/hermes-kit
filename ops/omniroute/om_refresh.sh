#!/bin/sh
# Weekly: wake freellmapi only to pull its premium live catalog, rebuild the OmniRoute combos from it
# (om_pool.py plan -> full re-probe -> apply), smoke-test, then put freellmapi back to sleep.
# cron (host):  20 4 * * 1  /docker/omniroute/migrate/om_refresh.sh >> /docker/omniroute/refresh.log 2>&1
set -eu
M=/docker/omniroute/migrate
FLC="docker compose -f /docker/freellmapi/docker-compose.yml"
pw() { grep "^INITIAL_PASSWORD=" /docker/omniroute/.env | cut -d= -f2- | sed "s/^[\"']//; s/[\"']$//"; }
fl() { docker exec -i -w /app/server freellmapi-freellmapi-1 sh -c 'cat > .kit.mjs && node .kit.mjs; rm -f .kit.mjs' < "$1"; }

echo "== $(date -Is) refresh"
t0=$(($(date +%s) * 1000))
$FLC start freellmapi >/dev/null
# freellmapi syncs the catalog 10s after boot and stamps catalog_last_sync_ms on success (services/catalog-sync.ts)
i=0
until [ "$(fl $M/fl_state.mjs 2>/dev/null | cut -d' ' -f1 || echo 0)" -gt "$t0" ] 2>/dev/null; do
  i=$((i + 1)); [ "$i" -gt 36 ] && { echo "catalog sync not seen in 3 min; using the cached catalog"; break; }; sleep 5
done
fl $M/fl_catalog.mjs > $M/fl_catalog.json.new && mv $M/fl_catalog.json.new $M/fl_catalog.json
used=$(fl $M/fl_state.mjs | cut -d' ' -f2)
# ponytail: "used in the last 24h" is the whole liveness rule; our own catalog export makes no requests rows
if [ "$used" -eq 0 ]; then $FLC stop freellmapi >/dev/null; echo "freellmapi stopped (no traffic in 24h)"
else echo "freellmapi left running: $used requests in 24h still go to it"; fi

pw | python3 $M/om_models.py http://127.0.0.1:20128 | tail -1
python3 $M/om_pool.py plan | tail -1
[ -f $M/probe.json ] && mv $M/probe.json $M/probe.prev.json   # full re-probe: dead models leave, new free ones enter
python3 $M/om_pool.py probe | tail -1
pw | python3 $M/om_pool.py apply
python3 $M/om_suite.py loop solar-pro4 hermes-fast hermes-private hermes-coding
