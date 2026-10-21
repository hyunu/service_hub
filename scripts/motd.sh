#!/usr/bin/env bash
# hub-motd — SSH 로그인 시 서버 현황 표시 (N100 Service Hub)
#
# 원칙 (요구사항 §12):
#   * 이 스크립트는 Docker를 호출하지 않는다. 백그라운드 모니터가 캐시한
#     status.json만 읽는다. Service Hub가 중단되어 있어도 SSH 로그인이
#     지연되지 않아야 한다.
#   * 캐시가 오래되었으면(기본 60초) STALE 및 마지막 갱신 시각을 표시한다.
#
# 설치: install.sh가 /etc/update-motd.d/90-n100-service-hub(또는 대체 경로)에
#       복사/링크한다. 기존 MOTD는 백업 후 수정하며 제거 시 복원된다.
#
# 환경변수:
#   HUB_STATUS_CACHE  캐시 파일 경로 (기본: /var/run/hub/status.json)
#   HUB_STALE_SECONDS 이 값보다 오래된 캐시는 STALE로 표시 (기본: 60)
set -u

CACHE="${HUB_STATUS_CACHE:-/var/run/hub/status.json}"
STALE_SECONDS="${HUB_STALE_SECONDS:-60}"

[ -r "$CACHE" ] || exit 0   # 캐시가 없으면 아무것도 출력하지 않는다 (로그인 지연 방지)

python3 - "$CACHE" "$STALE_SECONDS" <<'PY'
import json, sys, time
from datetime import datetime

cache_path, stale_seconds = sys.argv[1], int(sys.argv[2])
try:
    with open(cache_path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
except Exception:
    sys.exit(0)

LINE = "=" * 60


def h(v, default="-"):
    return default if v is None else str(v)


def pct(v):
    return "-" if v is None else f"{v:.0f}%"


def gb(megabytes):
    if megabytes is None:
        return "-"
    return f"{megabytes / 1024:.1f}"


def ts(value):
    if not value:
        return "-"
    try:
        dt = datetime.fromisoformat(value)
        delta = time.time() - dt.timestamp()
        if delta < 90:
            return f"{value} ({int(delta)}초 전)"
        if delta < 5400:
            return f"{value} ({int(delta // 60)}분 전)"
        return f"{value} ({int(delta // 3600)}시간 전)"
    except Exception:
        return str(value)


gen = data.get("generated_at_epoch")
stale = gen is None or (time.time() - gen) > stale_seconds

server = data.get("server", {})
docker = data.get("docker", {})
resources = data.get("resources", {})
services = data.get("services", [])
events = data.get("recent_events", [])
mgmt = data.get("management", {})

out = []
out.append(LINE)
out.append(data.get("hub_name", "SERVICE HUB").center(60))
out.append(LINE)
out.append("SYSTEM")
out.append(f"  Hostname       : {h(server.get('hostname'))}")
out.append(f"  Uptime         : {h(server.get('uptime_human'))}")
out.append(f"  CPU            : {pct(resources.get('cpu_percent'))}")
out.append(f"  Memory         : {gb(resources.get('memory_used_mb'))} / "
           f"{gb(resources.get('memory_total_mb'))} GB")
if resources.get("disk_used_gb") is not None:
    out.append(f"  Disk           : {resources['disk_used_gb']:.0f} / "
               f"{resources.get('disk_total_gb', 0):.0f} GB")
else:
    out.append("  Disk           : -")
out.append("DOCKER")
if docker.get("connected"):
    out.append("  Status         : connected")
else:
    out.append("  Status         : DISCONNECTED (상태 확인 불가)")
out.append(f"  Running        : {h(docker.get('running'))}")
out.append(f"  Stopped        : {h(docker.get('stopped'))}")
out.append(f"  Unmanaged      : {h(docker.get('orphans'))}")
if services:
    out.append("SERVICES")
    shown = services[:8]
    width = max(len(str(s.get("name", "?"))) for s in shown) + 2
    for s in shown:
        badge = {"healthy": "[OK]", "warning": "[WARN]", "critical": "[!!]"}.get(
            str(s.get("status", "")).lower(), "[??]")
        out.append(f"  {badge} {str(s.get('name', '?')):<{width}} "
                   f"{h(s.get('containers_running'))} containers")
    if len(services) > 8:
        out.append(f"  ... 외 {len(services) - 8}개 (hub service list)")
out.append("MANAGEMENT")
if mgmt.get("dashboard"):
    out.append(f"  Dashboard      : {mgmt['dashboard']}")
out.append("  CLI            : hub status")
if events:
    out.append("RECENT EVENTS")
    for e in events[:3]:
        out.append(f"  - {e.get('message', '')}")
out.append(LINE)
if stale:
    out.append("  (경고: 상태 정보가 오래되었습니다. 마지막 갱신: "
               f"{ts(data.get('last_monitor_ok_at') or data.get('generated_at'))})")
    out.append(LINE)

print("\n".join(out))
PY
