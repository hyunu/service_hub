"""소스 아카이브(tar.gz) 안전 추출 — MCP/AI 소스 업로드용.

안전 원칙 (AGENTS.md 규칙 #1, #4, #7):
  - 대상은 ``<HUB_DEPLOY_WORKDIR>/<service_id>`` 로 한정한다.
  - 아카이브 멤버는 **상대 경로 + 일반 파일/디렉터리**만 허용한다
    (절대 경로, ``..``, 심볼릭/하드 링크, 장치 파일 거부).
  - 크기/파일 수 상한을 두고, 압축 해제는 임시 디렉터리에서 검증 후 복사한다.
  - 기존 파일은 덮어쓰되 **삭제하지 않는다**(prune 없음).
  - 임의 셸/명령은 실행하지 않는다 (tarfile 파이썬 표준 라이브러리만 사용).
"""
from __future__ import annotations

import os
import shutil
import tarfile
import tempfile
from pathlib import Path


class SourceArchiveError(Exception):
    def __init__(self, message: str, code: str = "source_archive_invalid") -> None:
        super().__init__(message)
        self.code = code


def _validate_member(member: tarfile.TarInfo) -> None:
    name = member.name.replace("\\", "/")
    parts = [p for p in name.split("/") if p not in ("", ".")]
    if name.startswith("/") or any(p == ".." for p in parts):
        raise SourceArchiveError(f"안전하지 않은 경로입니다: {member.name}",
                                 "source_path_traversal")
    if member.isdir():
        return
    if not member.isfile():
        # 심볼릭 링크/하드 링크/장치/파이프 금지
        raise SourceArchiveError(
            f"일반 파일/디렉터리만 허용됩니다: {member.name}", "source_member_type")


def extract_source(archive: Path, target: Path, *,
                   max_files: int = 20000,
                   max_extract_mb: int = 1024,
                   max_file_mb: int = 200) -> dict:
    """tar.gz 를 검증 후 target 디렉터리에 덮어쓴다 (삭제는 하지 않음)."""
    target = target.resolve()
    target.mkdir(parents=True, exist_ok=True)

    files = 0
    dirs = 0
    total_bytes = 0
    max_total = max_extract_mb * 1024 * 1024
    max_file = max_file_mb * 1024 * 1024

    tmpdir = Path(tempfile.mkdtemp(prefix="hub-src-"))
    try:
        try:
            with tarfile.open(archive, "r:gz") as tf:
                members = tf.getmembers()
                if len(members) > max_files:
                    raise SourceArchiveError(
                        f"파일 수가 너무 많습니다 ({len(members)} > {max_files})",
                        "source_too_many_files")
                for member in members:
                    _validate_member(member)
                    if member.isfile():
                        if member.size > max_file:
                            raise SourceArchiveError(
                                f"파일이 너무 큽니다: {member.name}", "source_file_too_large")
                        total_bytes += member.size
                        if total_bytes > max_total:
                            raise SourceArchiveError(
                                f"압축 해제 크기가 너무 큽니다 (> {max_extract_mb}MB)",
                                "source_too_large")
                # 검증을 통과한 아카이브만 추출한다 (2차 방어: data 필터).
                tf.extractall(tmpdir, filter="data")
        except tarfile.TarError as exc:
            raise SourceArchiveError(f"아카이브를 읽을 수 없습니다: {exc}",
                                     "source_archive_invalid") from exc

        for root, dirnames, filenames in os.walk(tmpdir):
            rel = Path(root).relative_to(tmpdir)
            dest_dir = target / rel
            dest_dir.mkdir(parents=True, exist_ok=True)
            _chmod(dest_dir, 0o775)
            dirs += 1
            for fn in filenames:
                src = Path(root) / fn
                dst = dest_dir / fn
                try:
                    shutil.copyfile(src, dst)
                    executable = os.access(src, os.X_OK)
                    if _is_secret_file(fn):
                        _chmod(dst, 0o600)
                    else:
                        _chmod(dst, 0o775 if executable else 0o664)
                except PermissionError as exc:
                    raise SourceArchiveError(
                        f"배포 디렉터리에 쓸 수 없습니다: {dst}. "
                        f"`sudo chmod -R g+rwX {target}` 로 그룹 쓰기 권한을 준 뒤 "
                        f"다시 시도하세요.", "source_write_forbidden") from exc
                files += 1
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    return {"files": files, "dirs": dirs, "bytes": total_bytes, "target": str(target)}


def _is_secret_file(name: str) -> bool:
    """`.env` 계열/키 파일은 600 으로 저장한다 (예시 파일 제외)."""
    lowered = name.lower()
    if lowered in (".env.example", ".env.sample", ".env.template"):
        return False
    return (lowered == ".env" or lowered.startswith(".env.")
            or lowered.endswith((".pem", ".key")))


def _chmod(path: Path, mode: int) -> None:
    try:
        os.chmod(path, mode)
    except OSError:
        pass
