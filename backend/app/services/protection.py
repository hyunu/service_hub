"""컨테이너 조작 보호 규칙 (REQUIREMENTS §8.6, AGENTS.md 규칙 #1).

백엔드 조작 라우터와 조회 API가 **같은 규칙**을 공유하도록 분리했다.
(UI가 버튼을 미리 비활성화하고 사유를 표시할 수 있게 하기 위함)
"""
from __future__ import annotations

from ..models import Container

HUB_SELF_PROJECT = "service-hub"
HUB_IMAGE_PREFIX = "n100-service-hub-"


def patterns(value: str | None) -> list[str]:
    return [p.strip().lower() for p in (value or "").split(",") if p.strip()]


def protection_reason(row: Container, settings) -> str | None:
    """조작이 금지된 컨테이너면 사유 문자열, 아니면 None."""
    labels = row.labels or {}
    if (row.component_name == "hub-self"
            or str(labels.get("com.hub.self")).lower() == "true"
            or (row.compose_project or "") == HUB_SELF_PROJECT):
        return "허브 자신의 컨테이너는 조작할 수 없습니다"
    name = (row.name or "").lower()
    for pat in patterns(settings.protected_containers):
        if name == pat or name.startswith(pat):
            return f"보호된 컨테이너입니다 (HUB_PROTECTED_CONTAINERS: {pat})"
    project = (row.compose_project or "").lower()
    for pat in patterns(settings.protected_projects):
        if project == pat:
            return f"보호된 compose 프로젝트입니다 (HUB_PROTECTED_PROJECTS: {pat})"
    return None
