"""Docker 접근 래퍼 (docs/ARCHITECTURE.md §2 — 모든 Docker 접근은 여기서만).

원칙:
  * 호출부에 예외를 전파하지 않는다. 연결 실패/오류는 구조화된 값으로 반환한다.
  * 이 모듈에는 실행/삭제/재시작 함수가 존재하지 않는다 (Phase 1 읽기 전용).
    컨테이너 변경 경로는 Phase 3의 배포 실행기에서만 추가된다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

HUB_SELF_LABEL = "com.hub.managed"
HUB_SELF_PROJECT = "service-hub"


@dataclass
class DockerStatus:
    connected: bool
    server_version: str | None = None
    error: str | None = None


@dataclass
class ContainerSnapshot:
    container_id: str
    name: str
    image: str | None
    state: str                     # running | exited | created | paused | unknown
    status_text: str
    health: str | None
    restart_count: int
    compose_project: str | None
    compose_service: str | None
    config_files: str | None
    ports: list[dict] = field(default_factory=list)     # [{proto, host_port, bind_addr, container_port}]
    networks: list[str] = field(default_factory=list)
    mounts: list[dict] = field(default_factory=list)    # [{type, source, destination}]
    labels: dict = field(default_factory=dict)
    container_created_at: str | None = None
    started_at: str | None = None
    is_hub_self: bool = False


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    try:
        return datetime.fromtimestamp(value, tz=datetime.now().astimezone().tzinfo).isoformat()
    except Exception:
        return None


class DockerGateway:
    """실제 Docker SDK 클라이언트를 감싼 게이트웨이."""

    def __init__(self, socket_path: str | None = None,
                 allow_mutations: bool = False) -> None:
        self._socket_path = socket_path
        self._client = None
        self._allow_mutations = allow_mutations
        self.mutation_log: list[dict] = []

    def _require_mutation(self) -> None:
        if not self._allow_mutations:
            raise PermissionError(
                "이 게이트웨이는 변경 작업이 허용되지 않았습니다 (allow_mutations=False)")

    def _get_client(self):
        if self._client is not None:
            return self._client
        import docker  # 지연 임포트 — 데몬 없이도 앱이 기동해야 한다

        self._client = docker.DockerClient(
            base_url=self._socket_path or "unix://var/run/docker.sock", timeout=5)
        return self._client

    def status(self) -> DockerStatus:
        try:
            client = self._get_client()
            client.ping()
            version = client.version().get("Version")
            return DockerStatus(connected=True, server_version=version)
        except Exception as exc:  # 데몬 미실행/권한 없음 등
            self._client = None
            return DockerStatus(connected=False, error=type(exc).__name__)

    def list_containers(self) -> list[ContainerSnapshot] | None:
        """모든 컨테이너(중지 포함) 스냅샷. Docker 불가 시 None."""
        try:
            client = self._get_client()
            client.ping()
            out: list[ContainerSnapshot] = []
            for c in client.containers.list(all=True):
                out.append(self._snapshot(c))
            return out
        except Exception:
            return None

    def container_logs(self, container_id: str, tail: int = 200) -> str | None:
        try:
            client = self._get_client()
            c = client.containers.get(container_id)
            return c.logs(tail=tail).decode("utf-8", errors="replace")
        except Exception:
            return None

    def stats(self, container_id: str) -> dict | None:
        try:
            client = self._get_client()
            c = client.containers.get(container_id)
            s = c.stats(stream=False)
            mem = s.get("memory_stats", {}) or {}
            cpu = s.get("cpu_stats", {}) or {}
            net = s.get("networks", {}) or {}
            usage = mem.get("usage")
            limit = mem.get("limit")
            rx = sum(v.get("rx_bytes", 0) for v in net.values()) or None
            tx = sum(v.get("tx_bytes", 0) for v in net.values()) or None
            cpu_pct = None
            cpu_delta = (cpu.get("cpu_usage", {}) or {}).get("total_usage")
            precpu = s.get("precpu_stats", {}) or {}
            precpu_delta = (precpu.get("cpu_usage", {}) or {}).get("total_usage")
            system_delta = cpu.get("system_cpu_usage") - precpu.get("system_cpu_usage") \
                if cpu.get("system_cpu_usage") and precpu.get("system_cpu_usage") else None
            online = (cpu.get("online_cpus")
                      or len((cpu.get("cpu_usage", {}) or {}).get("percpu_usage", []) or [])
                      or 1)
            if cpu_delta is not None and precpu_delta is not None and system_delta and system_delta > 0:
                cpu_pct = round((cpu_delta - precpu_delta) / system_delta * online * 100.0, 2)
            return {
                "cpu_percent": cpu_pct,
                "mem_used_mb": round(usage / 1048576, 1) if usage else None,
                "mem_limit_mb": round(limit / 1048576, 1) if limit else None,
                "net_rx_bytes": rx,
                "net_tx_bytes": tx,
                "blk_read_bytes": _blk(s.get("blkio_stats")),
                "blk_write_bytes": _blk(s.get("blkio_stats"), write=True),
            }
        except Exception:
            return None

    # ------------------------------------------------------------------

    def compose_config(self, project_dir: str, project_name: str) -> dict:
        """`docker compose config` 상당의 검증. 읽기 전용 (게이트 불필요)."""
        try:
            import subprocess
            proc = subprocess.run(
                ["docker", "compose", "-f", f"{project_dir}/compose.yaml",
                 "-p", project_name, "config", "--quiet"],
                capture_output=True, text=True, timeout=30, check=False)
            return {"ok": proc.returncode == 0, "stderr": proc.stderr.strip()[:500]}
        except Exception as exc:
            return {"ok": False, "stderr": type(exc).__name__}

    def compose_up(self, project_dir: str, project_name: str,
                   timeout: int = 600) -> dict:
        """Compose 프로젝트 배포. 임의 셸/커맨드 파라미터는 받지 않는다."""
        self._require_mutation()
        return self._compose(["up", "-d", "--remove-orphans"], project_dir,
                             project_name, timeout)

    def compose_down(self, project_dir: str, project_name: str,
                     timeout: int = 300) -> dict:
        self._require_mutation()
        return self._compose(["down"], project_dir, project_name, timeout)

    def _compose(self, args: list[str], project_dir: str, project_name: str,
                 timeout: int) -> dict:
        import subprocess
        cmd = ["docker", "compose", "-f", f"{project_dir}/compose.yaml",
               "-p", project_name, *args]
        self.mutation_log.append({"action": f"compose_{args[0]}", "project": project_name})
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=timeout, check=False)
            return {"ok": proc.returncode == 0,
                    "stdout": proc.stdout[-2000:], "stderr": proc.stderr[-2000:]}
        except subprocess.TimeoutExpired:
            return {"ok": False, "stderr": "timeout"}
        except Exception as exc:
            return {"ok": False, "stderr": type(exc).__name__}

    # ------------------------------------------------------------------

    def _snapshot(self, c) -> ContainerSnapshot:
        attrs = c.attrs or {}
        labels = dict(attrs.get("Config", {}).get("Labels") or {})
        network_settings = attrs.get("NetworkSettings", {}) or {}
        host_cfg = attrs.get("HostConfig", {}) or {}

        ports: list[dict] = []
        for port_spec, bindings in (network_settings.get("Ports") or {}).items():
            try:
                container_port, proto = port_spec.split("/")
            except ValueError:
                continue
            if bindings:
                for b in bindings:
                    ports.append({
                        "proto": proto or "tcp",
                        "host_port": int(b.get("HostPort") or 0) or None,
                        "bind_addr": b.get("HostIp") or "0.0.0.0",
                        "container_port": int(container_port),
                    })
            else:
                ports.append({"proto": proto or "tcp", "host_port": None,
                              "bind_addr": None, "container_port": int(container_port)})

        mounts = [{"type": m.get("Type"), "source": m.get("Source"), "destination": m.get("Destination")}
                  for m in attrs.get("Mounts") or []]

        health = None
        state = (attrs.get("State", {}) or {}).get("Status", c.status.split()[0].lower()
                 if c.status else "unknown")
        try:
            health = (attrs.get("State", {}) or {}).get("Health", {}).get("Status")
        except AttributeError:
            health = None

        restart_count = host_cfg.get("RestartCount") or attrs.get("RestartCount") or 0
        started = (attrs.get("State", {}) or {}).get("StartedAt")
        created = attrs.get("Created")

        return ContainerSnapshot(
            container_id=c.id,
            name=(c.name or "").lstrip("/"),
            image=attrs.get("Config", {}).get("Image") or c.image,
            state=state or "unknown",
            status_text=c.status or "",
            health=health,
            restart_count=int(restart_count or 0),
            compose_project=labels.get("com.docker.compose.project"),
            compose_service=labels.get("com.docker.compose.service"),
            config_files=labels.get("com.docker.compose.project.config_files"),
            ports=ports,
            networks=sorted((network_settings.get("Networks") or {}).keys()),
            mounts=mounts,
            labels=labels,
            container_created_at=_iso(created),
            started_at=_iso(started) if started and not started.startswith("0001") else None,
            is_hub_self=bool(labels.get(HUB_SELF_LABEL)) or labels.get(
                "com.docker.compose.project") == HUB_SELF_PROJECT,
        )


def _blk(blkio_stats: dict | None, write: bool = False) -> int | None:
    if not blkio_stats:
        return None
    key = "io_service_bytes_recursive" if "io_service_bytes_recursive" in blkio_stats else "io_service_bytes"
    total = 0
    found = False
    for entry in blkio_stats.get(key) or []:
        op = (entry.get("op") or "").lower()
        if op == ("write" if write else "read"):
            total += entry.get("value", 0)
            found = True
    return total if found else None


# ------------------------------------------------------------- fake (테스트)

@dataclass
class FakeContainer:
    """docker SDK의 containers.list() 결과를 흉내 내는 테스트용 오브젝트."""
    id: str
    name: str
    image: str = "img:latest"
    status: str = "Up 2 hours"
    attrs: dict = field(default_factory=dict)

    def logs(self, tail: int = 200) -> bytes:
        return b"fake log line 1\nfake log line 2\n"

    def stats(self, stream: bool = False) -> dict:
        return {
            "memory_stats": {"usage": 100 * 1048576, "limit": 512 * 1048576},
            "cpu_stats": {"cpu_usage": {"total_usage": 2000}, "system_cpu_usage": 10000,
                          "online_cpus": 4},
            "precpu_stats": {"cpu_usage": {"total_usage": 1000}, "system_cpu_usage": 8000},
            "networks": {"eth0": {"rx_bytes": 1000, "tx_bytes": 2000}},
        }


class FakeDockerGateway(DockerGateway):
    """테스트 전용: 데몬 없이 스냅샷을 공급한다."""

    def __init__(self, containers: list[FakeContainer] | None = None,
                 connected: bool = True, allow_mutations: bool = False) -> None:
        super().__init__(allow_mutations=allow_mutations)
        self.containers = containers or []
        self.connected = connected

    def compose_config(self, project_dir: str, project_name: str) -> dict:
        return {"ok": True, "stderr": ""}

    def compose_up(self, project_dir: str, project_name: str, timeout: int = 600) -> dict:
        self._require_mutation()
        self.mutation_log.append({"action": "compose_up", "project": project_name,
                                  "dir": project_dir})
        return {"ok": True, "stdout": f"fake compose up {project_name}", "stderr": ""}

    def compose_down(self, project_dir: str, project_name: str, timeout: int = 300) -> dict:
        self._require_mutation()
        self.mutation_log.append({"action": "compose_down", "project": project_name})
        return {"ok": True, "stdout": "", "stderr": ""}

    def status(self) -> DockerStatus:
        if self.connected:
            return DockerStatus(connected=True, server_version="27.0-fake")
        return DockerStatus(connected=False, error="FakeDockerUnavailable")

    def list_containers(self) -> list[ContainerSnapshot] | None:
        if not self.connected:
            return None
        gw = DockerGateway.__new__(DockerGateway)
        return [gw._snapshot(c) for c in self.containers]

    def container_logs(self, container_id: str, tail: int = 200) -> str | None:
        for c in self.containers:
            if c.id == container_id:
                return c.logs(tail=tail).decode()
        return None

    def stats(self, container_id: str) -> dict | None:
        for c in self.containers:
            if c.id == container_id:
                return FakeContainer.stats(c)
        return None
