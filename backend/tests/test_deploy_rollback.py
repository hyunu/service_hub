"""배포 파일 스냅샷/롤백 테스트 (REQUIREMENTS §13.4).

롤백은 "그 배포 시점의 정의 파일로 되돌려 재배포"한다.
- 스냅샷은 .env(시크릿)를 복사하지 않는다.
- 성공한 배포만 롤백할 수 있고, 스냅샷이 없으면 409.
- 게이트가 닫혀 있으면 503 (DB 조회 전에 차단).
"""
from __future__ import annotations

from conftest import make_fake_container, mutate

SERVICE_YAML = """\
schema_version: 1
service:
  id: rb-app
  name: RB App
  description: 롤백 테스트용 서비스
  category: dev
deployment:
  type: docker-compose
  compose_file: compose.yaml
containers:
  - name: app
    role: other
    required: true
"""

COMPOSE_V1 = "services:\n  app:\n    image: alpine:latest\n    command: [\"echo\", \"v1\"]\n"
COMPOSE_V2 = "services:\n  app:\n    image: alpine:latest\n    command: [\"echo\", \"v2\"]\n"


def _make_workdir(tmp_path):
    workdir = tmp_path / "rb-app"
    workdir.mkdir()
    (workdir / "service.yaml").write_text(SERVICE_YAML, encoding="utf-8")
    (workdir / "compose.yaml").write_text(COMPOSE_V1, encoding="utf-8")
    (workdir / ".env").write_text("SECRET_VALUE=do-not-copy\n", encoding="utf-8")
    return workdir


def _add_running_container():
    from app.dependencies import get_gateway

    get_gateway().containers.append(
        make_fake_container("c1", "rb-app-app", project="rb-app", service="app",
                            running=True))


def test_snapshot_excludes_secrets_and_non_yaml(tmp_path):
    from app.services.deploy_snapshot import take_snapshot

    workdir = _make_workdir(tmp_path)
    (workdir / "README.md").write_text("docs", encoding="utf-8")

    snap = take_snapshot(workdir, tmp_path / "snaps", "rb-app", "dep-1", "tester")
    assert snap is not None
    assert set(snap["files"]) == {"service.yaml", "compose.yaml"}
    d = tmp_path / "snaps" / "rb-app" / "dep-1"
    assert d.is_dir() and (d / "service.yaml").is_file()
    assert not (d / ".env").exists()
    assert not (d / "README.md").exists()


def test_snapshot_failure_does_not_block_deploy(tmp_path):
    """스냅샷 경로를 만들 수 없어도 None만 반환하고 예외를 올리지 않는다."""
    from app.services.deploy_snapshot import take_snapshot

    workdir = _make_workdir(tmp_path)
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    assert take_snapshot(workdir, blocker, "rb-app", "dep-1", "tester") is None


def test_rollback_restores_previous_files(app_factory, tmp_path, monkeypatch):
    workdir = _make_workdir(tmp_path)
    monkeypatch.setenv("HUB_DEPLOY_SNAPSHOT_DIR", str(tmp_path / "snaps"))
    client = app_factory(admin=True, enable_deploy=True, deploy_workdir=str(tmp_path),
                         gateway_allow_mutations=True)
    try:
        _add_running_container()

        # v1 배포
        r1 = mutate(client, "POST", "/api/v1/deployments", json={"service_id": "rb-app"})
        assert r1.status_code == 202, r1.text
        dep1 = r1.json()
        assert dep1["status"] == "succeeded", dep1
        assert "v1" in (workdir / "compose.yaml").read_text(encoding="utf-8")

        # v2로 수정 후 재배포
        (workdir / "compose.yaml").write_text(COMPOSE_V2, encoding="utf-8")
        r2 = mutate(client, "POST", "/api/v1/deployments", json={"service_id": "rb-app"})
        assert r2.status_code == 202, r2.text
        assert r2.json()["status"] == "succeeded"

        # v1 배포 시점으로 롤백
        r3 = mutate(client, "POST",
                    f"/api/v1/deployments/{dep1['deployment_id']}/rollback",
                    json={"confirmed": True})
        assert r3.status_code == 202, r3.text
        body = r3.json()
        assert body["status"] == "succeeded", body
        assert body["rollback_of"] == dep1["deployment_id"]
        assert set(body["restored_files"]) == {"service.yaml", "compose.yaml"}
        # 파일이 v1으로 되돌아갔다
        assert "v1" in (workdir / "compose.yaml").read_text(encoding="utf-8")
        assert (workdir / "service.yaml").is_file()

        # 롤백도 새 배포 레코드로 남는다
        items = client.get("/api/v1/deployments?service_id=rb-app").json()["items"]
        assert len(items) == 3
        assert body["deployment_id"] in [i["deployment_id"] for i in items]

        # 감사 로그
        logs = client.get("/api/v1/audit-logs").json()["items"]
        assert any(a["action"] == "deploy.rollback" for a in logs)
    finally:
        client.__exit__(None, None, None)


def test_rollback_requires_enabled_gate(client):
    """게이트가 닫혀 있으면 DB 조회 전에 503."""
    r = mutate(client, "POST", "/api/v1/deployments/dep-x/rollback", json={})
    assert r.status_code == 503
    assert r.json()["code"] == "deploy_disabled"


def test_rollback_rejects_non_succeeded(app_factory, tmp_path, monkeypatch):
    _make_workdir(tmp_path)
    monkeypatch.setenv("HUB_DEPLOY_SNAPSHOT_DIR", str(tmp_path / "snaps"))
    client = app_factory(admin=True, enable_deploy=True, deploy_workdir=str(tmp_path),
                         gateway_allow_mutations=True)
    try:
        from app.db import get_session_factory
        from app.models import Deployment

        with get_session_factory()() as s:
            s.add(Deployment(id="dep-failed", service_id="rb-app", status="failed",
                             requested_by="tester", plan={}))
            s.commit()
        r = mutate(client, "POST", "/api/v1/deployments/dep-failed/rollback", json={})
        assert r.status_code == 409
        assert r.json()["code"] == "rollback_not_allowed"
    finally:
        client.__exit__(None, None, None)


def test_rollback_missing_snapshot(app_factory, tmp_path, monkeypatch):
    _make_workdir(tmp_path)
    monkeypatch.setenv("HUB_DEPLOY_SNAPSHOT_DIR", str(tmp_path / "snaps"))
    client = app_factory(admin=True, enable_deploy=True, deploy_workdir=str(tmp_path),
                         gateway_allow_mutations=True)
    try:
        from app.db import get_session_factory
        from app.models import Deployment

        with get_session_factory()() as s:
            s.add(Deployment(id="dep-nosnap", service_id="rb-app", status="succeeded",
                             requested_by="tester", plan={}))
            s.commit()
        r = mutate(client, "POST", "/api/v1/deployments/dep-nosnap/rollback", json={})
        assert r.status_code == 409
        assert r.json()["code"] == "snapshot_missing"
    finally:
        client.__exit__(None, None, None)


def test_rollback_requires_csrf(app_factory, tmp_path, monkeypatch):
    _make_workdir(tmp_path)
    monkeypatch.setenv("HUB_DEPLOY_SNAPSHOT_DIR", str(tmp_path / "snaps"))
    client = app_factory(admin=True, enable_deploy=True, deploy_workdir=str(tmp_path),
                         gateway_allow_mutations=True)
    try:
        r = client.post("/api/v1/deployments/dep-x/rollback", json={},
                        headers={"X-CSRF-Token": "forged"})
        assert r.status_code == 403
        assert r.json()["code"] == "csrf"
    finally:
        client.__exit__(None, None, None)


def test_rollback_permission_error_is_actionable(app_factory, tmp_path, monkeypatch):
    """서비스 디렉터리가 root 소유라 쓸 수 없으면 chown 안내를 포함한 409."""
    _make_workdir(tmp_path)
    monkeypatch.setenv("HUB_DEPLOY_SNAPSHOT_DIR", str(tmp_path / "snaps"))
    client = app_factory(admin=True, enable_deploy=True, deploy_workdir=str(tmp_path),
                         gateway_allow_mutations=True)
    try:
        from app.db import get_session_factory
        from app.models import Deployment

        with get_session_factory()() as s:
            s.add(Deployment(id="dep-perm", service_id="rb-app", status="succeeded",
                             requested_by="tester", plan={}))
            s.commit()

        import app.services.deploy_snapshot as snap_mod

        def _deny(*_a, **_k):
            raise PermissionError(
                "배포 디렉터리에 쓸 수 없습니다: /srv/services/rb-app. "
                "`sudo chown -R 10001:10001 /srv/services/rb-app` 후 다시 시도하세요.")

        monkeypatch.setattr(snap_mod, "restore_snapshot", _deny)
        r = mutate(client, "POST", "/api/v1/deployments/dep-perm/rollback", json={})
        assert r.status_code == 409
        assert r.json()["code"] == "snapshot_restore_forbidden"
        assert "chown" in r.json()["detail"]
    finally:
        client.__exit__(None, None, None)
