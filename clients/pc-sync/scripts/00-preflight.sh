#!/usr/bin/env bash
# 0단계(신규): 키트가 실제로 배포·설정됐는지 확인한다.
# 이전 스크립트들은 서버 설정을 직접 덮어썼다. 이제 그 일은 kit(/setup)이 전부 담당한다.
# 이 스킬은 PC 쪽(싱크띵·옵시디언)만 automating한다.
. "$(dirname "$0")/lib.sh"
echo "▶ 대상 서버 확인"
discover
echo "  컨테이너: $CONTAINER"
echo "  SSH 별칭: $SSH_ALIAS"

echo
echo "▶ 1. kit-setup 플러گ인"
# /setup 이 Discord에 등록돼야 이 스킬이 쓸 수 있다. k11 이전엔 조용히 실패했다.
if in_hermes "test -d /opt/data/plugins/kit-setup" ; then
  echo "  ✅ kit-setup 존재"
else
  echo "  ❌ kit-setup이 없습니다 — hermes-kit 이미지로 다시 배포하세요 (k11 이상)." >&2; exit 1
fi

echo
echo "▶ 2. Syncthing 컨테이너"
if in_hermes "test -f /opt/syncthing-config/config.xml" ; then
  echo "  ✅ 설정 파일 마운트됨 (/opt/syncthing-config/config.xml)"
else
  echo "  ❌ Syncthing 설정 볼륨이 없습니다 — docker-compose.yml의 syncthing 볼륨을 확인하세요." >&2; exit 1
fi
if syncthing_ready; then
  echo "  ✅ Syncthing 응답 (http://syncthing:8384)"
else
  echo "  ❌ Syncthing이 응답하지 않습니다 — docker logs로 syncthing 서비스를 확인하세요." >&2; exit 1
fi

echo
echo "▶ 3. 볼트 2개 (sync 대상)"
for v in work personal; do
  if hssh "test -d /opt/data/vaults/$v" || in_hermes "test -d /var/syncthing/vaults/$v"; then
    echo "  ✅ $v 볼트 존재"
  else
    echo "  ⚠️ $v 볼트가 아직 없습니다 — Discord에서 /setup 을 한 번 실행하세요." >&2
  fi
done

echo
echo "✅ 사전 점검 통과. 다음: bash scripts/01-pc-sync.sh"
