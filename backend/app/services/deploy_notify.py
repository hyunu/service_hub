"""배포 결과 알림(웹훅) — 무인 배포에서 사람이 지켜보지 않아도 되도록.

- `HUB_DEPLOY_WEBHOOK_URL` 이 설정된 경우에만 동작한다.
- 전송은 **백그라운드 스레드**에서 이루어지며, 실패해도 배포에는 영향을 주지 않는다.
- `HUB_DEPLOY_WEBHOOK_SECRET` 이 있으면 `X-Hub-Signature` 헤더로 HMAC-SHA256 서명을 보낸다.
- 임의 셸을 사용하지 않는다 (urllib 표준 라이브러리만).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import threading
import urllib.request
from typing import Any

from ..config import get_settings


def notify_deployment(dep: Any, *, extra: dict | None = None) -> None:
    """배포 종료 결과를 웹훅으로 전송한다 (fire-and-forget)."""
    settings = get_settings()
    url = (settings.deploy_webhook_url or "").strip()
    if not url:
        return

    payload = {
        "event": "deployment.finished",
        "deployment_id": getattr(dep, "id", None),
        "service_id": getattr(dep, "service_id", None),
        "status": getattr(dep, "status", None),
        "error": getattr(dep, "error", None),
        "requested_by": getattr(dep, "requested_by", None),
        "started_at": getattr(dep, "started_at", None),
        "finished_at": getattr(dep, "finished_at", None),
    }
    if extra:
        payload.update(extra)

    secret = settings.deploy_webhook_secret or ""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json", "User-Agent": "n100-service-hub"}
    if secret:
        headers["X-Hub-Signature"] = "sha256=" + hmac.new(
            secret.encode("utf-8"), body, hashlib.sha256).hexdigest()

    threading.Thread(target=_post, args=(url, body, headers), daemon=True).start()


def _post(url: str, body: bytes, headers: dict[str, str]) -> None:
    try:
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=5):
            pass
    except Exception:
        # 알림 실패는 조용히 무시한다 (배포 결과에 영향 없음)
        pass
