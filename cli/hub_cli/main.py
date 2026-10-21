"""hub — N100 Service Hub CLI.

Exit codes:
  0 success
  1 generic error
  2 usage error (bad arguments)
  3 backend unreachable
  4 request rejected by backend (validation/conflict)
  5 resource not found
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx

PROG = "hub"
DEFAULT_BASE = "http://127.0.0.1:8420/api/v1"
SCHEMA_URL_PATH = "/../schemas/service.schema.v1.json"

EXIT_OK = 0
EXIT_ERR = 1
EXIT_USAGE = 2
EXIT_UNREACHABLE = 3
EXIT_REJECTED = 4
EXIT_NOTFOUND = 5


class CliError(Exception):
    def __init__(self, message: str, exit_code: int = EXIT_ERR) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def base_url() -> str:
    return os.environ.get("HUB_URL", DEFAULT_BASE).rstrip("/")


def api(path: str, method: str = "GET", payload: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None) -> Any:
    url = f"{base_url()}{path}"
    try:
        resp = httpx.request(method, url, json=payload, headers=headers, timeout=10.0)
    except httpx.HTTPError as exc:
        raise CliError(
            f"Service Hub에 연결할 수 없습니다: {url}\n"
            f"  원인: {exc}\n"
            f"  확인: 백엔드 실행 여부와 HUB_URL 환경변수를 확인하세요.",
            EXIT_UNREACHABLE,
        ) from exc
    if resp.status_code == 404:
        raise CliError(_detail(resp), EXIT_NOTFOUND)
    if resp.status_code >= 400:
        raise CliError(_detail(resp), EXIT_REJECTED)
    if not resp.content:
        return None
    return resp.json()


def _detail(resp: httpx.Response) -> str:
    try:
        body = resp.json()
        if isinstance(body, dict) and "detail" in body:
            code = body.get("code")
            prefix = f"[{code}] " if code else ""
            return f"{prefix}{body['detail']} (HTTP {resp.status_code})"
    except ValueError:
        pass
    return f"HTTP {resp.status_code}: {resp.text[:300]}"


# ---------------------------------------------------------------- output ----

def emit(data: Any, as_json: bool, render) -> None:
    if as_json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        render(data)


def fmt_ts(value: str | None) -> str:
    return value if value else "-"


# ---------------------------------------------------------------- commands --

def cmd_status(args: argparse.Namespace) -> None:
    data = api("/system/status")

    def render(d: dict[str, Any]) -> None:
        docker = d.get("docker", {})
        mon = d.get("monitor", {})
        srv = d.get("server", {})
        print(f"Hub          : {d.get('hub_name', 'N100 Service Hub')}")
        print(f"Server       : {srv.get('hostname', '?')} ({srv.get('os', '?')})")
        print(f"Uptime       : {srv.get('uptime_human', '?')}")
        if docker.get("connected"):
            print(f"Docker       : connected ({docker.get('server_version', '?')})")
        else:
            print("Docker       : DISCONNECTED (상태를 확인할 수 없음)")
        print(f"Running      : {d.get('counts', {}).get('containers_running', '?')}")
        print(f"Stopped      : {d.get('counts', {}).get('containers_stopped', '?')}")
        print(f"Unmanaged    : {d.get('counts', {}).get('orphans', '?')}")
        print(f"Monitor      : {mon.get('state', '?')}")
        print(f"Last update  : {fmt_ts(mon.get('last_ok_at'))}")
        warnings = d.get("warnings", [])
        for w in warnings:
            print(f"  [{w.get('level', '?')}] {w.get('message', '')}")

    emit(data, args.json, render)


def cmd_service_list(args: argparse.Namespace) -> None:
    params: list[tuple[str, str]] = []
    if args.search:
        params.append(("search", args.search))
    if args.status:
        params.append(("status", args.status))
    if args.category:
        params.append(("category", args.category))
    qs = ("?" + "&".join(f"{k}={v}" for k, v in params)) if params else ""
    data = api(f"/services{qs}")

    def render(d: Any) -> None:
        items = d.get("items", d) if isinstance(d, dict) else d
        if not items:
            print("등록된 서비스가 없습니다.")
            return
        print(f"{'ID':<24} {'상태':<10} {'컨테이너':<10} {'CPU%':>6} {'MEM MB':>8}  이름")
        for s in items:
            c = s.get("containers", {})
            print(
                f"{s['id']:<24} {s.get('status', '?'):<10} "
                f"{str(c.get('running', 0)) + '/' + str(c.get('total', 0)):<10} "
                f"{_num(s.get('cpu_percent')):>6} {_num(s.get('memory_mb')):>8}  {s.get('name', '')}"
            )

    emit(data, args.json, render)


def _num(v: Any) -> str:
    if v is None:
        return "N/A"
    if isinstance(v, float):
        return f"{v:.1f}"
    return str(v)


def cmd_service_show(args: argparse.Namespace) -> None:
    data = api(f"/services/{args.service_id}")

    def render(d: dict[str, Any]) -> None:
        print(f"서비스       : {d.get('name')} ({d.get('id')})")
        print(f"설명         : {d.get('description', '')}")
        print(f"분류         : {d.get('category', '?')}   상태: {d.get('status', '?')}")
        print(f"배포         : {d.get('deployment_type', '?')} @ {d.get('deployment_path', '?')}")
        print(f"Compose      : {d.get('compose_file', '?')}")
        print(f"마지막 배포  : {fmt_ts(d.get('last_deployed_at'))}")
        comps = d.get("components", [])
        if comps:
            print("구성요소:")
            for c in comps:
                req = "필수" if c.get("required") else "선택"
                print(f"  - {c.get('name')} ({c.get('role', '?')}, {req})")
        eps = d.get("endpoints", [])
        if eps:
            print("엔드포인트:")
            for e in eps:
                print(f"  - {e.get('name')}: {e.get('type')} {e.get('exposure')} "
                      f"{e.get('hostname') or ''} -> {e.get('container')}:{e.get('container_port')}")
        warns = d.get("warnings", [])
        for w in warns:
            print(f"  [경고] {w}")

    emit(data, args.json, render)


def cmd_service_validate(args: argparse.Namespace) -> None:
    path = Path(args.path)
    if path.is_dir():
        path = path / "service.yaml"
    if not path.exists():
        raise CliError(f"파일을 찾을 수 없습니다: {path}", EXIT_NOTFOUND)
    doc = _load_yaml(path)
    schema_path = _schema_path()
    if schema_path is None or not schema_path.exists():
        raise CliError("스키마 파일을 찾을 수 없습니다: service.schema.v1.json", EXIT_ERR)
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    try:
        import jsonschema
    except ImportError as exc:  # pragma: no cover
        raise CliError("jsonschema 패키지가 필요합니다: pip install jsonschema", EXIT_ERR) from exc
    validator = jsonschema.Draft7Validator(schema)
    errors = sorted(validator.iter_errors(doc), key=lambda e: list(e.absolute_path))
    if errors:
        if args.json:
            print(json.dumps({
                "valid": False,
                "errors": [
                    {"path": "/".join(str(p) for p in e.absolute_path) or "(root)",
                     "message": e.message}
                    for e in errors
                ],
            }, ensure_ascii=False, indent=2))
        else:
            print(f"검증 실패: {path}", file=sys.stderr)
            for e in errors:
                loc = "/".join(str(p) for p in e.absolute_path) or "(root)"
                print(f"  - {loc}: {e.message}", file=sys.stderr)
        sys.exit(EXIT_REJECTED)
    result = {"valid": True, "service_id": doc.get("service", {}).get("id")}
    emit(result, args.json,
         lambda d: print(f"검증 통과: {path} (service_id={d['service_id']})"))


def cmd_service_new(args: argparse.Namespace) -> None:
    """표준 서비스 디렉터리 골격을 생성한다 (시크릿 값 없음)."""
    import re
    service_id = args.service_id
    if not re.match(r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$", service_id):
        raise CliError(f"서비스 ID 형식이 올바르지 않습니다: {service_id!r}", EXIT_REJECTED)
    root = Path(args.dir) / service_id
    if root.exists():
        raise CliError(f"이미 존재하는 디렉터리입니다: {root}", EXIT_REJECTED)
    display = args.name or service_id
    for sub in ("config", "data", "logs"):
        (root / sub).mkdir(parents=True, exist_ok=True)
        (root / sub / ".gitkeep").write_text("", encoding="utf-8")
    (root / "service.yaml").write_text(
        "schema_version: 1\n"
        "service:\n"
        f"  id: {service_id}\n"
        f"  name: {display}\n"
        f"  description: {display} 서비스 (설명을 채우세요)\n"
        f"  category: {args.category}\n"
        '  version: "0.1.0"\n'
        "deployment:\n"
        "  type: docker-compose\n"
        "  compose_file: compose.yaml\n", encoding="utf-8")
    (root / "compose.yaml").write_text(
        "services:\n  app:\n    image: " + service_id + ":latest\n"
        "    restart: unless-stopped\n    ports:\n"
        '      - "127.0.0.1:8000:3000"\n', encoding="utf-8")
    (root / ".env.example").write_text(
        f"# {display} 환경 변수 (이름만)\nEXAMPLE_VAR=\n", encoding="utf-8")
    (root / ".gitignore").write_text(".env\ndata/\nlogs/\n", encoding="utf-8")
    result = {"created": str(root), "service_id": service_id}
    emit(result, args.json,
         lambda d: print(f"생성됨: {d['created']}\n"
                         f"  service_id: {d['service_id']}\n"
                         "  다음: service.yaml 설명을 채우고 "
                         "`hub service validate`로 검증하세요."))


def _schema_path() -> Path | None:
    """패키지 내부 스키마를 우선하고, 소스 체크아웃에서는 저장소 루트도 탐색한다."""
    pkg = Path(__file__).resolve().parent / "schemas" / "service.schema.v1.json"
    if pkg.exists():
        return pkg
    repo = Path(__file__).resolve().parent.parent.parent / "schemas" / "service.schema.v1.json"
    return repo if repo.exists() else None


def _load_yaml(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # PyYAML is optional; fall back to a minimal parser message
        return yaml.safe_load(text)
    except ImportError as exc:
        raise CliError(
            "YAML 파싱을 위해 PyYAML이 필요합니다: pip install pyyaml "
            "(또는 uv pip install pyyaml)", EXIT_ERR) from exc


def cmd_port_list(args: argparse.Namespace) -> None:
    data = api("/ports")

    def render(d: Any) -> None:
        items = d.get("items", d) if isinstance(d, dict) else d
        if not items:
            print("등록된 포트 정보가 없습니다.")
            return
        print(f"{'포트':<7} {'프로토콜':<5} {'바인드':<16} {'상태':<12} {'서비스':<22} 비고")
        for p in items:
            print(
                f"{str(p.get('host_port', '-')):<7} {p.get('protocol', 'tcp'):<5} "
                f"{(p.get('bind_addr') or '*'):<16} {p.get('state', '?'):<12} "
                f"{(p.get('service_id') or '-'):<22} {p.get('note', '') or ''}"
            )

    emit(data, args.json, render)


def cmd_port_available(args: argparse.Namespace) -> None:
    params = [f"count={args.count}", f"protocol={args.protocol}"]
    if args.range:
        params.append(f"range={args.range}")
    data = api("/ports/available?" + "&".join(params))

    def render(d: Any) -> None:
        items = d.get("candidates", d.get("items", [])) if isinstance(d, dict) else d
        if not items:
            print("조건에 맞는 가용 포트가 없습니다.")
            return
        print("가용 포트 후보:")
        for p in items:
            print(f"  {p}")

    emit(data, args.json, render)


def cmd_orphan_list(args: argparse.Namespace) -> None:
    data = api("/orphans")

    def render(d: Any) -> None:
        items = d.get("items", d) if isinstance(d, dict) else d
        if not items:
            print("미관리 컨테이너가 없습니다.")
            return
        for o in items:
            print(f"- {o.get('name')} [{o.get('container_id_short', '')}] "
                  f"{o.get('image', '')} ({o.get('state', '?')})")
            print(f"    사유: {o.get('reason', '-')}  추정 서비스: {o.get('guessed_service') or '-'}")
            for port in o.get("ports", []) or []:
                print(f"    포트: {port}")

    emit(data, args.json, render)


def cmd_resource(args: argparse.Namespace) -> None:
    data = api("/resources/host")

    def render(d: dict[str, Any]) -> None:
        cpu = d.get("cpu", {})
        mem = d.get("memory", {})
        disk = d.get("disk", {})
        print(f"CPU    : {_num(cpu.get('percent'))}%  (논리 코어 {cpu.get('cores', '?')})")
        print(f"Memory : {_num(mem.get('used_mb'))} / {_num(mem.get('total_mb'))} MB "
              f"({_num(mem.get('percent'))}%)")
        for fs in disk.get("filesystems", []) or []:
            print(f"Disk   : {fs.get('mount')} {_num(fs.get('used_gb'))}/{_num(fs.get('total_gb'))} GB "
                  f"({_num(fs.get('percent'))}%)")
        sysinfo = d.get("system", {})
        print(f"Host   : {sysinfo.get('hostname', '?')} {sysinfo.get('os', '?')} "
              f"uptime {sysinfo.get('uptime_human', '?')}")
        for w in d.get("warnings", []) or []:
            print(f"  [{w.get('level')}] {w.get('message')}")

    emit(data, args.json, render)


def cmd_logs(args: argparse.Namespace) -> None:
    data = api(f"/services/{args.service_id}/logs?tail={args.tail}")

    def render(d: Any) -> None:
        for line in d.get("lines", []):
            print(line)

    emit(data, args.json, render)


def cmd_deploy_plan(args: argparse.Namespace) -> None:
    path = Path(args.path)
    if not path.exists():
        raise CliError(f"파일을 찾을 수 없습니다: {path}", EXIT_NOTFOUND)
    doc = _load_yaml(path)
    try:
        data = api("/deployments/plan", method="POST", payload={"service_definition": doc})
    except CliError as exc:
        if exc.exit_code == EXIT_REJECTED and "Phase 3" in str(exc):
            raise CliError(
                "배포 기능은 아직 비활성화되어 있습니다 (Phase 3). "
                "현재는 `hub service validate`로 정의 파일 검증만 가능합니다.", EXIT_REJECTED
            ) from exc
        raise
    def render(d: dict[str, Any]) -> None:
        print(f"Service: {d.get('service')}")
        print("Changes:")
        for c in d.get("changes", []):
            print(f"  {c.get('name')}: {c.get('action')} — {c.get('detail', '')}")
        port_changes = [p for p in d.get("ports", []) if p.get("host_port")]
        print("Ports:")
        print("  No host port changes" if not port_changes
              else "\n".join(f"  {p['host_port']} -> {p['name']}" for p in port_changes))
        print("Validation:")
        for v in d.get("validation", []):
            print(f"  {v.get('check')}: {v.get('result')}")
        for i in d.get("impact", []):
            print(f"  IMPACT: {i.get('message')}")
        for w in d.get("warnings", []):
            print(f"  [{w.get('level')}] {w.get('message')}")
        print(f"Result: {d.get('result')}")

    emit(data, args.json, render)


def cmd_deploy_apply(args: argparse.Namespace) -> None:
    # 배포는 컨테이너를 변경한다 — 사전 확인 없이는 실행하지 않는다 (AI-OPERATIONS §1.7).
    if not args.yes:
        raise CliError(
            "배포는 컨테이너를 변경합니다. `hub deploy plan <path>`로 계획을 확인한 뒤 "
            "--yes 를 붙여 다시 실행하세요.", EXIT_REJECTED)
    try:
        data = api("/deployments", method="POST",
                   payload={"service_id": args.service_id, "confirmed": True})
    except CliError as exc:
        if exc.exit_code == EXIT_REJECTED:
            raise CliError(f"배포가 거부되었습니다: {exc}", exc.exit_code) from exc
        raise

    def render(d: dict[str, Any]) -> None:
        print(f"배포 ID : {d.get('deployment_id')}")
        print(f"상태    : {d.get('status')}")
        if d.get("error"):
            print(f"오류    : {d['error']}")
        print("실제 상태는 `hub deploy status <id>` 및 `hub status`로 재확인하세요.")

    emit(data, args.json, render)


def cmd_deploy_status(args: argparse.Namespace) -> None:
    data = api(f"/deployments/{args.deployment_id}")
    emit(data, args.json,
         lambda d: print(f"{d.get('deployment_id')}  {d.get('status')}  "
                         f"service={d.get('service_id')}"))


# ------------------------------------------------------------ admin reset --

def _reset_db_path(args: argparse.Namespace) -> Path:
    raw = args.db or os.environ.get("HUB_DB_PATH") or "./data/hub.db"
    return Path(raw).expanduser()


def _user_handle(username: str) -> str:
    """WebAuthn user_handle — base64url(사용자명), 패딩 제거."""
    import base64
    return base64.urlsafe_b64encode(username.encode("utf-8")).decode("ascii").rstrip("=")


def _backup_db(path: Path) -> Path:
    """DB 파일(및 WAL/SHM)을 백업한다. 되돌리기 위한 사본."""
    import datetime
    import shutil
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    target = path.with_name(f"{path.name}.bak-{stamp}")
    shutil.copy2(path, target)
    for suffix in ("-wal", "-shm"):
        side = path.with_name(path.name + suffix)
        if side.exists():
            shutil.copy2(side, target.with_name(target.name + suffix))
    return target


def _reset_admin_offline(path: Path) -> dict[str, Any]:
    """DB 파일을 직접 열어 관리자 자격 증명만 삭제한다 (오프라인 복구).

    서버 API에 접근할 수 없을 때(컨테이너/DB 볼륨 직접 접근) 사용하는 경로다.
    서비스/포트/컨테이너/이벤트 등 다른 테이블은 건드리지 않는다.
    """
    import sqlite3

    if not path.exists():
        raise CliError(f"DB 파일을 찾을 수 없습니다: {path}", EXIT_NOTFOUND)

    backup = _backup_db(path)
    con = sqlite3.connect(str(path))
    try:
        tables = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if "settings" not in tables:
            raise CliError(f"Service Hub DB가 아닙니다 (settings 테이블 없음): {path}",
                           EXIT_REJECTED)
        row = con.execute("SELECT value FROM settings WHERE key='admin'").fetchone()
        if row is None:
            raise CliError("설정된 관리자가 없습니다 (이미 초기화된 상태).", EXIT_NOTFOUND)
        try:
            admin = json.loads(row[0]) if isinstance(row[0], (str, bytes)) else dict(row[0])
        except ValueError:
            admin = {}
        username = admin.get("username")
        removed_credentials = 0
        if username and "webauthn_credentials" in tables:
            handle = _user_handle(str(username))
            cur = con.execute(
                "DELETE FROM webauthn_credentials WHERE user_handle=?", (handle,))
            removed_credentials = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
        con.execute("DELETE FROM settings WHERE key='admin'")
        con.commit()
    except sqlite3.Error as exc:
        con.rollback()
        raise CliError(f"DB 초기화 실패: {exc}", EXIT_ERR) from exc
    finally:
        con.close()
    return {"ok": True, "reset": True, "mode": "offline", "db": str(path),
            "backup": str(backup), "username": username,
            "webauthn_credentials_removed": removed_credentials,
            "setup_required": True}


def cmd_admin_reset(args: argparse.Namespace) -> None:
    """관리자 비밀번호 분실 복구 — 관리자 자격 증명을 초기화한다.

    초기화하면 로그인 화면 대신 설정 마법사가 다시 나타나며, 새로운
    사용자명/비밀번호를 직접 만들게 된다. 서비스/포트/컨테이너 데이터는
    그대로 유지된다.
    """
    if not args.yes:
        raise CliError(
            "관리자 초기화는 로그인 자격 증명을 삭제합니다. 계속하려면 --yes 를 붙여 "
            "다시 실행하세요.", EXIT_REJECTED)

    if args.db:
        data = _reset_admin_offline(_reset_db_path(args))
    else:
        token = args.token or os.environ.get("HUB_ADMIN_RESET_TOKEN") or ""
        headers = {"X-Hub-Admin-Reset-Token": token} if token else None
        data = api("/auth/reset-admin", method="POST", payload={}, headers=headers)
        data.setdefault("mode", "api")
        data.setdefault("url", base_url())

    def render(d: dict[str, Any]) -> None:
        print("관리자 자격 증명이 초기화되었습니다.")
        if d.get("username"):
            print(f"  삭제된 관리자 : {d['username']}")
        if d.get("db"):
            print(f"  DB            : {d['db']}")
        if d.get("backup"):
            print(f"  백업          : {d['backup']}")
        if d.get("webauthn_credentials_removed"):
            print(f"  삭제된 패스워드 키 : {d['webauthn_credentials_removed']}개")
        print("  다음: 대시보드를 다시 열어 설정 마법사에서 관리자 계정을 생성하세요.")

    emit(data, args.json, render)


# ---------------------------------------------------------------- parser ----

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog=PROG,
        description="N100 Service Hub CLI — 서버 상태 조회 및 표준 배포 인터페이스",
        epilog=(
            "예제:\n"
            "  hub status\n"
            "  hub status --json\n"
            "  hub service list --category web\n"
            "  hub service show ai-platform --json\n"
            "  hub service validate ./my-service/service.yaml\n"
            "  hub port available --count 5 --range 8000-9000\n"
            "  hub orphan list\n"
            "  hub resource\n"
            "  hub logs ai-platform --tail 100\n"
            "  hub deploy plan ./service.yaml --json\n"
            "  hub admin reset --yes            # 관리자 비밀번호 분실 복구\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--url", help=f"Service Hub API 주소 (기본: $HUB_URL 또는 {DEFAULT_BASE})")
    sub = p.add_subparsers(dest="group", required=True)

    sp = sub.add_parser("status", help="서버 및 관리 시스템 전체 상태")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_status)

    svc = sub.add_parser("service", help="서비스 관리").add_subparsers(dest="cmd", required=True)
    sl = svc.add_parser("list", help="서비스 목록")
    sl.add_argument("--search")
    sl.add_argument("--status")
    sl.add_argument("--category")
    sl.add_argument("--json", action="store_true")
    sl.set_defaults(func=cmd_service_list)
    ss = svc.add_parser("show", help="서비스 상세")
    ss.add_argument("service_id")
    ss.add_argument("--json", action="store_true")
    ss.set_defaults(func=cmd_service_show)
    sv = svc.add_parser("validate", help="service.yaml 스키마 검증")
    sv.add_argument("path", help="service.yaml 파일 또는 서비스 디렉터리")
    sv.add_argument("--json", action="store_true")
    sv.set_defaults(func=cmd_service_validate)
    sn = svc.add_parser("new", help="표준 서비스 디렉터리 골격 생성")
    sn.add_argument("service_id")
    sn.add_argument("--dir", default=".", help="생성 위치 (기본 현재 디렉터리)")
    sn.add_argument("--name", default=None)
    sn.add_argument("--category", default="other")
    sn.add_argument("--json", action="store_true")
    sn.set_defaults(func=cmd_service_new)

    prt = sub.add_parser("port", help="포트 관리").add_subparsers(dest="cmd", required=True)
    pl = prt.add_parser("list", help="포트 현황")
    pl.add_argument("--json", action="store_true")
    pl.set_defaults(func=cmd_port_list)
    pa = prt.add_parser("available", help="가용 포트 후보")
    pa.add_argument("--count", type=int, default=5)
    pa.add_argument("--range", dest="range", help="예: 8000-9000")
    pa.add_argument("--protocol", default="tcp", choices=["tcp", "udp"])
    pa.add_argument("--json", action="store_true")
    pa.set_defaults(func=cmd_port_available)

    orp = sub.add_parser("orphan", help="미관리 컨테이너").add_subparsers(dest="cmd", required=True)
    ol = orp.add_parser("list", help="미관리 컨테이너 목록")
    ol.add_argument("--json", action="store_true")
    ol.set_defaults(func=cmd_orphan_list)

    res = sub.add_parser("resource", help="서버 자원 상태")
    res.add_argument("--json", action="store_true")
    res.set_defaults(func=cmd_resource)

    lg = sub.add_parser("logs", help="서비스 로그")
    lg.add_argument("service_id")
    lg.add_argument("--tail", type=int, default=200)
    lg.add_argument("--json", action="store_true")
    lg.set_defaults(func=cmd_logs)

    dep = sub.add_parser("deploy", help="표준 배포").add_subparsers(dest="cmd", required=True)
    dp = dep.add_parser("plan", help="배포 계획 생성")
    dp.add_argument("path")
    dp.add_argument("--json", action="store_true")
    dp.set_defaults(func=cmd_deploy_plan)
    da = dep.add_parser("apply", help="배포 실행")
    da.add_argument("service_id")
    da.add_argument("--yes", action="store_true", help="확인 토큰 자동 승인")
    da.add_argument("--json", action="store_true")
    da.set_defaults(func=cmd_deploy_apply)
    dst = dep.add_parser("status", help="배포 작업 상태")
    dst.add_argument("deployment_id")
    dst.add_argument("--json", action="store_true")
    dst.set_defaults(func=cmd_deploy_status)

    adm = sub.add_parser("admin", help="관리자 계정 복구").add_subparsers(dest="cmd", required=True)
    ar = adm.add_parser("reset", help="관리자 비밀번호 분실 복구 (초기화)")
    ar.add_argument("--db", default=None,
                    help="오프라인 모드: Hub DB 파일 경로 (기본 $HUB_DB_PATH 또는 ./data/hub.db)")
    ar.add_argument("--token", default=None,
                    help="복구 토큰 (기본 $HUB_ADMIN_RESET_TOKEN). 서버가 루프백이 아닐 때 필요")
    ar.add_argument("--yes", action="store_true", help="확인 없이 실행")
    ar.add_argument("--json", action="store_true")
    ar.set_defaults(func=cmd_admin_reset)

    return p


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.url:
        os.environ["HUB_URL"] = args.url
    try:
        args.func(args)
    except CliError as exc:
        print(f"오류: {exc}", file=sys.stderr)
        sys.exit(exc.exit_code)
    except KeyboardInterrupt:
        sys.exit(EXIT_ERR)


if __name__ == "__main__":
    main()
