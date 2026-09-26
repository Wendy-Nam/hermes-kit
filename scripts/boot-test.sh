#!/bin/sh
# Boots the image twice on a fresh volume: 1st boot must seed, 2nd must change nothing.
# Usage: scripts/boot-test.sh <image>. Uses a dummy bot token (the gateway won't log in; cont-init still runs).
set -eu
IMG="$1"; VOL="kit-boot-test-$$"
trap 'docker rm -f "$VOL" >/dev/null 2>&1 || true; docker volume rm -f "$VOL" >/dev/null 2>&1 || true' EXIT
boot() {
  docker run -d --name "$VOL" -e DISCORD_BOT_TOKEN=dummy -v "$VOL:/opt/data" "$IMG" gateway run >/dev/null
  i=0; until docker logs "$VOL" 2>&1 | grep -qE '^\[kit\] (done|kit [0-9]+ already seeded)'; do
    i=$((i+1)); [ $i -lt 60 ] || { echo "boot-test: seed did not finish"; docker logs "$VOL" 2>&1 | tail -30; exit 1; }; sleep 2
  done
  if docker logs "$VOL" 2>&1 | grep -E "cont-init.d/.* exited [^0]|Permission denied"; then echo "boot-test: cont-init failure"; exit 1; fi
  docker rm -f "$VOL" >/dev/null
}
state() {
  docker run --rm -v "$VOL:/opt/data" --entrypoint sh "$IMG" -c '
    cd /opt/data; cat .kit-version; md5sum config.yaml SOUL.md; find skills -name SKILL.md | sort
    ls plugins vaults/*/.obsidian/plugins; stat -c "%U %n" config.yaml SOUL.md vaults/work plugins/rtk-rewrite plugins/kit-setup
    /opt/hermes/.venv/bin/python -c "import yaml;c=yaml.safe_load(open(\"config.yaml\"));assert c[\"agent\"][\"max_turns\"]==20 and \"rtk-rewrite\" in c[\"plugins\"][\"enabled\"];print(\"overlay ok\")"
    test -f plugins/kit-setup/plugin.yaml && test -f plugins/kit-setup/packs.json && echo "kit-setup present"'
}
docker volume create "$VOL" >/dev/null
boot; s1=$(state); boot; s2=$(state)
echo "$s1"
if [ "$s1" = "$s2" ]; then echo "boot-test: seeded and idempotent"; else
  echo "boot-test: 2nd boot changed state"; echo "$s1" > /tmp/bt1.$$; echo "$s2" > /tmp/bt2.$$; diff /tmp/bt1.$$ /tmp/bt2.$$ || true; exit 1; fi
