"""소스 업로드(MCP 소스 동기화) 테스트.

목표:
  - SSH 없이 tar.gz 업로드로 /srv/services/<id> 를 갱신할 수 있다.
  - 기본은 잠금(503) — 명시적으로 켜야 동작한다.
  - 경로 조작(../, 절대 경로, 심볼릭 링크)은 거부한다.
  - 컨테이너/이미지는 건드리지 않는다(runtime_changed=false).
"""
from __future__ import annotations

import io
import tarfile
from pathlib import Path

import pytest

from app.config import Settings
from conftest import mutate


def _tar_gz(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o644
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _client(app_factory, settings, workdir: Path, enabled: bool = True):
    s = Settings(db_path=settings.db_path, status_cache=settings.status_cache,
                 monitor_enabled=False, enable_source_upload=enabled,
                 _env_file=None)
    client = app_factory(s=s, admin=True)
    client.__enter__()
    import os
    os.environ["HUB_DEPLOY_WORKDIR"] = str(workdir)
    return client


def _service(client, sid: str = "src-svc") -> None:
    r = mutate(client, "POST", "/api/v1/services", json={
        "id": sid, "name": sid, "description": "", "category": "web",
        "deployment_type": "docker-compose", "deployment_path": f"/srv/services/{sid}",
    })
    assert r.status_code == 201, r.text


def _upload(client, sid: str, data: bytes):
    return mutate(client, "POST", f"/api/v1/services/{sid}/source", content=data,
                  headers={"Content-Type": "application/gzip"})


def test_upload_requires_gate(client, tmp_path):
    _service(client)
    r = _upload(client, "src-svc", _tar_gz({"app.py": b"print(1)"}))
    assert r.status_code == 503
    assert r.json()["code"] == "source_upload_disabled"


def test_upload_writes_files(app_factory, settings, tmp_path):
    workdir = tmp_path / "services"
    workdir.mkdir()
    client = _client(app_factory, settings, workdir)
    try:
        _service(client)
        r = _upload(client, "src-svc", _tar_gz({
            "app.py": b"print('hi')",
            "sub/data.txt": b"hello",
            "run.sh": b"#!/bin/sh\necho ok\n",
        }))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["files"] == 3
        assert body["runtime_changed"] is False

        target = workdir / "src-svc"
        assert (target / "app.py").read_bytes() == b"print('hi')"
        assert (target / "sub" / "data.txt").read_bytes() == b"hello"
        # 그룹 쓰기 권한(허브 사용자 외 사용자가 편집 가능하도록)
        assert (target / "app.py").stat().st_mode & 0o060
    finally:
        client.__exit__(None, None, None)


def test_upload_overwrites_but_does_not_delete(app_factory, settings, tmp_path):
    workdir = tmp_path / "services"
    (workdir / "src-svc").mkdir(parents=True)
    (workdir / "src-svc" / "keep.txt").write_text("keep")
    (workdir / "src-svc" / "change.txt").write_text("old")
    client = _client(app_factory, settings, workdir)
    try:
        _service(client)
        r = _upload(client, "src-svc", _tar_gz({"change.txt": b"new"}))
        assert r.status_code == 200, r.text
        assert (workdir / "src-svc" / "keep.txt").read_text() == "keep"
        assert (workdir / "src-svc" / "change.txt").read_text() == "new"
    finally:
        client.__exit__(None, None, None)


def test_upload_rejects_path_traversal(app_factory, settings, tmp_path):
    workdir = tmp_path / "services"
    workdir.mkdir()
    client = _client(app_factory, settings, workdir)
    try:
        _service(client)
        r = _upload(client, "src-svc", _tar_gz({"../escape.txt": b"x"}))
        assert r.status_code == 422
        assert r.json()["code"] == "source_path_traversal"
        assert not (workdir / "escape.txt").exists()
    finally:
        client.__exit__(None, None, None)


def test_upload_rejects_symlink(app_factory, settings, tmp_path):
    workdir = tmp_path / "services"
    workdir.mkdir()
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        info = tarfile.TarInfo("link")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        tf.addfile(info)
    client = _client(app_factory, settings, workdir)
    try:
        _service(client)
        r = _upload(client, "src-svc", buf.getvalue())
        assert r.status_code == 422
        assert r.json()["code"] == "source_member_type"
    finally:
        client.__exit__(None, None, None)


def test_upload_unknown_service(app_factory, settings, tmp_path):
    client = _client(app_factory, settings, tmp_path)
    try:
        r = _upload(client, "nope", _tar_gz({"a.txt": b"x"}))
        assert r.status_code == 404
    finally:
        client.__exit__(None, None, None)


def test_upload_rejects_wrong_content_type(app_factory, settings, tmp_path):
    client = _client(app_factory, settings, tmp_path)
    try:
        _service(client)
        r = mutate(client, "POST", "/api/v1/services/src-svc/source",
                   content=b"x", headers={"Content-Type": "text/plain"})
        assert r.status_code == 415
    finally:
        client.__exit__(None, None, None)


def test_upload_permission_error_is_actionable(app_factory, settings, tmp_path, monkeypatch):
    """쓰기 권한이 없으면 500이 아니라 409 + 해결 방법을 알려준다."""
    workdir = tmp_path / "services"
    workdir.mkdir()
    client = _client(app_factory, settings, workdir)
    try:
        _service(client)

        def _deny(*a, **k):
            raise PermissionError("denied")

        monkeypatch.setattr("shutil.copyfile", _deny)
        r = _upload(client, "src-svc", _tar_gz({"app.py": b"x"}))
        assert r.status_code == 409
        assert r.json()["code"] == "source_write_forbidden"
        assert "chmod" in r.json()["detail"]
    finally:
        client.__exit__(None, None, None)
