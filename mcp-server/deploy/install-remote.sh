#!/usr/bin/env bash
# 원격(HTTP) MCP 서비스를 서버에 설치한다. sudo 필요.
#
#   sudo ./mcp-server/deploy/install-remote.sh
#
# 전제:
#   - 저장소가 /home/hyunu/projects/service_hub 에 있음
#   - uv 가 /home/hyunu/.local/bin/uv 에 있음
#   - 허브 백엔드가 100.85.245.79:8420 에 바인드됨
set -euo pipefail
UNIT=/etc/systemd/system/hub-mcp.service
HERE="$(cd "$(dirname "$0")" && pwd)"

/usr/bin/install -m 644 "$HERE/hub-mcp.service" "$UNIT"
systemctl daemon-reload
systemctl enable --now hub-mcp
systemctl restart hub-mcp
sleep 2
systemctl is-active hub-mcp
echo "원격 MCP: http://100.85.245.79:8422/mcp (요청마다 X-API-Key 필요)"
