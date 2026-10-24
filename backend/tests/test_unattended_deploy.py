"""무인 배포 운영 기능 테스트 — 허용 목록 / 자동 롤백 / 웹훅 / 비밀파일 권한."""
from __future__ import annotations

import io
import json
import tarfile

import pytest

from app.config import Settings
from conftest import mutate

SPEC = {
    "schema_version": 1,
    "service": {"id": "auto-app", "name": "Auto", "description": "무인 배포",
                "category": "web"},
    "deployment": {"type": "docker-compose", "compose_file": "compose.yaml"},
    "containers": [{"name": "app", "role": "backend", "required": True}],
}


def _client(app_factory, settings, **overrides):
    s = Settings(db_path=settings.db_path, status_cache=settings.status_cache,
                 monitor_enabled=False, enable_deploy=True, _env_file=None, **overrides)
    return app_factory(s=s, admin=True, gateway_allow_mutations=True)


# ------------------------------------------------------------ 허용 목록 --

def test_allowlist_blocks_other_services(client, settings):
    """HUB_DEPLOY_ALLOWED_SERVICES 가 있으면 목록 밖 서비스는 403."""
    from app.config import set_settings
    set_settings(Settings(db_path=settings.db_path, status_cache=settings.status_cache,
                          monitor_enabled=False, enable_deploy=True,
                          deploy_allowed_services="other-app", _env_file=None))
    r = mutate(client, "POST", "/api/v1/deployments", json={"spec": SPEC})
    assert r.status_code == 403
    assert r.json()["code"] == "service_not_allowed"


def test_allowlist_blocks_plan_too(client, settings):
    from app.config import set_settings
    set_settings(Settings(db_path=settings.db_path, status_cache=settings.status_cache,
                          monitor_enabled=False, enable_deploy=True,
                          deploy_allowed_services="other-app", _env_file=None))
    r = mutate(client, "POST", "/api/v1/deployments/plan", json=SPEC)
    assert r.status_code == 403


def test_allowlist_allows_listed_service(app_factory, settings, tmp_path):
    (tmp_path / "auto-app").mkdir()
    (tmp_path / "auto-app" / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
    client = _client(app_factory, settings, deploy_allowed_services="auto-app")
    try:
        import os
        os.environ["HUB_DEPLOY_WORKDIR"] = str(tmp_path)
        from conftest import make_fake_container
        from app.dependencies import get_gateway
        get_gateway().containers.append(
            make_fake_container("a1", "auto-app-app", project="auto-app", service="app"))
        r = mutate(client, "POST", "/api/v1/deployments", json={"spec": SPEC})
        assert r.status_code == 202, r.text
    finally:
        client.__exit__(None, None, None)


# ------------------------------------------------------------ 웹훅 --

def test_webhook_payload_and_signature(monkeypatch):
    from app.config import Settings, set_settings
    from app.services import deploy_notify

    captured: dict = {}

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=0):
        captured["url"] = req.full_url
        captured["data"] = req.data
        captured["sig"] = req.headers.get("X-hub-signature")
        return FakeResp()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    set_settings(Settings(monitor_enabled=False, _env_file=None,
                          deploy_webhook_url="https://example.test/hook",
                          deploy_webhook_secret="s3cret"))

    class Dep:
        id = "dep-1"
        service_id = "auto-app"
        status = "succeeded"
        error = None
        requested_by = "ai"
        started_at = "2026-10-24T00:00:00+00:00"
        finished_at = "2026-10-24T00:00:05+00:00"

    deploy_notify.notify_deployment(Dep(), extra={"rollback_of": None})
    # 스레드 완료 대기
    import time
    for _ in range(50):
        if "data" in captured:
            break
        time.sleep(0.02)

    assert captured["url"] == "https://example.test/hook"
    body = json.loads(captured["data"])
    assert body["deployment_id"] == "dep-1"
    assert body["status"] == "succeeded"
    assert captured["sig"].startswith("sha256=")


def test_webhook_disabled_by_default(monkeypatch):
    from app.config import Settings, set_settings
    from app.services import deploy_notify

    called = []
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: called.append(1))
    set_settings(Settings(monitor_enabled=False, _env_file=None))
    deploy_notify.notify_deployment(object())
    assert called == []


# ------------------------------------------------------------ 자동 롤백 --

def test_latest_successful_excludes_given_deployment(client):
    from app.db import get_session_factory
    from app.models import Deployment
    from app.services.deploy_rollback import latest_successful

    with get_session_factory()() as s:
        s.add(Deployment(id="dep-old", service_id="auto-app", status="succeeded",
                         requested_by="t", plan={}, finished_at="2026-10-20T00:00:00+00:00"))
        s.add(Deployment(id="dep-new", service_id="auto-app", status="succeeded",
                         requested_by="t", plan={}, finished_at="2026-10-21T00:00:00+00:00"))
        s.add(Deployment(id="dep-fail", service_id="auto-app", status="failed",
                         requested_by="t", plan={}, finished_at="2026-10-22T00:00:00+00:00"))
        s.commit()

    with get_session_factory()() as s:
        dep = latest_successful(s, "auto-app")
        assert dep is not None and dep.id == "dep-new"
        dep2 = latest_successful(s, "auto-app", exclude="dep-new")
        assert dep2 is not None and dep2.id == "dep-old"


# --------------------------------------------------- 비밀 파일 권한 --

def _tar_gz(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def test_uploaded_env_file_is_0600(app_factory, settings, tmp_path):
    from app.config import Settings as S
    workdir = tmp_path / "services"
    workdir.mkdir()
    s = S(db_path=settings.db_path, status_cache=settings.status_cache,
          monitor_enabled=False, enable_source_upload=True, _env_file=None)
    client = app_factory(s=s, admin=True)
    client.__enter__()
    import os
    os.environ["HUB_DEPLOY_WORKDIR"] = str(workdir)
    try:
        r = mutate(client, "POST", "/api/v1/services", json={
            "id": "src-svc", "name": "src", "description": "", "category": "web"})
        assert r.status_code == 201, r.text
        r = mutate(client, "POST", "/api/v1/services/src-svc/source",
                   content=_tar_gz({".env": b"SECRET=1", ".env.example": b"SECRET="}),
                   headers={"Content-Type": "application/gzip"})
        assert r.status_code == 200, r.text
        assert (workdir / "src-svc" / ".env").stat().st_mode & 0o777 == 0o600
        assert (workdir / "src-svc" / ".env.example").stat().st_mode & 0o777 == 0o664
    finally:
        client.__exit__(None, None, None)
