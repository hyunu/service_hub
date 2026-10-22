"""배포 파일 스냅샷/복원 (REQUIREMENTS §13.4).

배포 시점의 ``service.yaml``/``compose.yaml``을 스냅샷해 두고, 롤백 시 그 시점
파일로 되돌린 뒤 다시 배포한다. ``.env`` 등 숨김 파일은 **복사하지 않는다**
(시크릿 중복 저장 방지). 스냅샷 실패는 배포를 막지 않는다.
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

# 스냅샷/복원 대상 — 배포 정의 파일만. 데이터/로그/설정 디렉터리는 제외한다.
COPY_SUFFIXES = (".yaml", ".yml")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def snapshot_path(root: str | Path, service_id: str, deployment_id: str) -> Path:
    return Path(root) / service_id / deployment_id


def take_snapshot(workdir: str | Path, root: str | Path | None,
                  service_id: str, deployment_id: str, actor: str) -> dict | None:
    """배포 디렉터리의 YAML 파일을 스냅샷한다. 실패하면 None(배포는 계속)."""
    if not root:
        return None
    src = Path(workdir)
    if not src.is_dir():
        return None
    dst = snapshot_path(root, service_id, deployment_id)
    try:
        dst.mkdir(parents=True, exist_ok=True)
        files: list[str] = []
        for p in sorted(src.iterdir()):
            if not p.is_file() or p.name.startswith("."):
                continue
            if p.suffix.lower() not in COPY_SUFFIXES:
                continue
            shutil.copy2(p, dst / p.name)
            files.append(p.name)
        (dst / "meta.json").write_text(json.dumps({
            "service_id": service_id,
            "deployment_id": deployment_id,
            "taken_at": _now(),
            "actor": actor,
            "files": files,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"dir": str(dst), "files": files}
    except OSError:
        return None


def restore_snapshot(root: str | Path | None, service_id: str, deployment_id: str,
                     workdir: str | Path) -> list[str]:
    """스냅샷 파일을 배포 디렉터리로 되돌린다. 없으면 FileNotFoundError."""
    if not root:
        raise FileNotFoundError("스냅샷 디렉터리가 설정되지 않았습니다")
    src = snapshot_path(root, service_id, deployment_id)
    if not src.is_dir():
        raise FileNotFoundError(f"스냅샷이 없습니다: {src}")
    dst = Path(workdir)
    try:
        dst.mkdir(parents=True, exist_ok=True)
        restored: list[str] = []
        for p in sorted(src.iterdir()):
            if p.is_file() and p.name != "meta.json":
                shutil.copy2(p, dst / p.name)
                restored.append(p.name)
    except PermissionError as exc:
        # 서비스 디렉터리가 root 소유면 백엔드(uid 10001)가 쓸 수 없다.
        raise PermissionError(
            f"배포 디렉터리에 쓸 수 없습니다: {dst}. "
            f"`sudo chown -R 10001:10001 {dst}` 후 다시 시도하세요."
        ) from exc
    except OSError as exc:
        raise FileNotFoundError(f"스냅샷 복원에 실패했습니다: {exc}") from exc
    if not restored:
        raise FileNotFoundError(f"스냅샷에 복원할 파일이 없습니다: {src}")
    return restored
