#!/bin/sh
# Fails if the public image carries anything personal or secret. Usage: scripts/secret-scan.sh <image>
# Scans only what the kit adds (/opt/kit, the cont-init hook) plus /opt/data, which must stay pristine.
set -eu
IMG="$1"
exec docker run --rm --entrypoint sh "$IMG" -c '
bad=0
say() { echo "secret-scan: $*"; bad=1; }
roots="/opt/kit /etc/cont-init.d/10-kit-seed"

# 1. files that must never ship
f=$(find $roots -type f \( -name ".env" -o -name "*.env" -o -name "auth.json" -o -name "*.db" -o -name "*.bak*" -o -name "*.pem" -o -name "id_*" \) 2>/dev/null | grep -v "/opt/kit/versions.env" || true)
[ -z "$f" ] || say "forbidden files: $f"

# 2. key/token shapes
# vendored Obsidian plugin bundles under .obsidian (pinned upstream releases) are minified and false-positive on these shapes
k=$(grep -rIlE --exclude-dir=.obsidian "(sk-[A-Za-z0-9_-]{20,}|gsk_[A-Za-z0-9]{20,}|AIza[0-9A-Za-z_-]{35}|ghp_[A-Za-z0-9]{30,}|xox[bp]-[A-Za-z0-9-]{20,}|[MN][A-Za-z0-9]{23}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27}|apify_api_[A-Za-z0-9]{20,})" $roots 2>/dev/null || true)
[ -z "$k" ] || say "key-shaped strings in: $k"

# 3. the author s private plugins, pools, paths and ids
for p in hermes-self turn-router session-sticky hermes-snow-search ux-improvements shared-music \
         unfiltered ehr-wiki personal-wiki work-wiki 1523328379951120526 1078199419058524170 187.127.124.238; do
  h=$(grep -rIl -- "$p" $roots 2>/dev/null || true)
  [ -z "$h" ] || say "private marker \"$p\" in: $h"
done

# 4. /opt/data must be exactly what the base image ships (anything else is copied into every new volume)
extra=$(find /opt/data -mindepth 1 ! -name ".bash_logout" ! -name ".bashrc" ! -name ".profile")
[ -z "$extra" ] || say "/opt/data polluted: $extra"

[ "$bad" = 0 ] && echo "secret-scan: clean"
exit $bad
'
