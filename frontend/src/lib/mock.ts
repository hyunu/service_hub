/**
 * 개발용 로컬 목 어댑터 — 백엔드(127.0.0.1:8420)가 아직 없을 때
 * `VITE_API_MOCK=true` (npm run dev:mock)로 활성화된다.
 * 계약(docs/ARCHITECTURE.md §3)과 동일한 경로/응답 모양을 제공한다.
 * 테스트는 주로 모듈(mock)을 직접 지정하므로 이 어댑터는 개발/미리보기용이다.
 */

import type {
  AuditLog,
  ContainerDetail,
  ContainerListItem,
  ContainerResourceRow,
  Deployment,
  HubEvent,
  HubSettings,
  HostResources,
  OrphanItem,
  PortEntry,
  ResourceWarning,
  ServiceDetail,
  ServiceListItem,
  ServiceResourceRow,
  SessionInfo,
  SystemOverview,
  SystemStatus,
} from "./api";

const now = Date.now();
const iso = (offsetMs: number) => new Date(now + offsetMs).toISOString();

/* ------------------------------ 데이터 ------------------------------ */

const session = (): SessionInfo => ({
  authenticated: true,
  setup_required: false,
  user: { username: "admin", role: "admin" },
  csrf_token: "mock-csrf-token",
});

const settings: HubSettings = {
  hub_name: "N100 Service Hub",
  monitor_interval_seconds: 15,
  thresholds: {
    memory_warn_percent: 80,
    memory_critical_percent: 90,
    disk_warn_percent: 80,
    disk_critical_percent: 90,
    cpu_warn_percent: 80,
    cpu_critical_percent: 95,
    cpu_sustained_seconds: 60,
  },
  bind: { host: "0.0.0.0", port: 8420, internal_only: true },
};

const endpoints = {
  "ai-platform": [
    { name: "frontend", type: "http", exposure: "proxy", hostname: "ai.home", container: "ai-frontend", container_port: 3000, enabled: true },
    { name: "backend", type: "http", exposure: "internal", hostname: null, container: "ai-backend", container_port: 8000, enabled: true },
  ],
  "media-server": [
    { name: "web", type: "http", exposure: "proxy", hostname: "media.home", container: "media-web", container_port: 8096, enabled: true },
  ],
  "home-assistant": [
    { name: "ui", type: "http", exposure: "proxy", hostname: "ha.home", container: "home-assistant", container_port: 8123, enabled: true },
  ],
  "sample-app": [],
} as const;

const services: ServiceListItem[] = [
  {
    id: "ai-platform",
    name: "AI Platform",
    description: "개인 AI 추론 및 대화 플랫폼 (frontend, backend, worker, postgres)",
    category: "ai",
    status: "ok",
    containers: { total: 4, running: 4 },
    endpoints: [...(endpoints["ai-platform"] ?? [])],
    cpu_percent: 18.4,
    memory_mb: 3120,
    last_deployed_at: iso(-3 * 86400_000),
    deployment_type: "docker-compose",
    deployment_path: "/srv/services/ai-platform",
    compose_file: "compose.yaml",
    repository_url: "git@home:ai-platform.git",
    repository_branch: "main",
    version: "1.4.2",
    documentation: "/srv/services/ai-platform/README.md",
    tags: ["ai", "핵심"],
    created_at: iso(-120 * 86400_000),
    updated_at: iso(-3 * 86400_000),
    last_healthcheck_at: iso(-120_000),
  },
  {
    id: "media-server",
    name: "Media Server",
    description: "가정 미디어 스트리밍 (영상/음악 라이브러리)",
    category: "media",
    status: "warn",
    containers: { total: 2, running: 1 },
    endpoints: [...(endpoints["media-server"] ?? [])],
    cpu_percent: 6.2,
    memory_mb: 1450,
    last_deployed_at: iso(-14 * 86400_000),
    deployment_type: "docker-compose",
    deployment_path: "/srv/services/media-server",
    compose_file: "compose.yaml",
    version: "10.9.1",
    tags: ["미디어"],
    created_at: iso(-200 * 86400_000),
    updated_at: iso(-14 * 86400_000),
    last_healthcheck_at: iso(-130_000),
  },
  {
    id: "home-assistant",
    name: "Home Assistant",
    description: "스마트홈 자동화 허브",
    category: "automation",
    status: "ok",
    containers: { total: 1, running: 1 },
    endpoints: [...(endpoints["home-assistant"] ?? [])],
    cpu_percent: 3.1,
    memory_mb: 620,
    last_deployed_at: iso(-45 * 86400_000),
    deployment_type: "docker-compose",
    deployment_path: "/srv/services/home-assistant",
    compose_file: "compose.yaml",
    version: "2026.10",
    tags: ["자동화"],
    created_at: iso(-300 * 86400_000),
    updated_at: iso(-45 * 86400_000),
    last_healthcheck_at: iso(-90_000),
  },
  {
    id: "dev-playground",
    name: "Dev Playground",
    description: "개발/테스트 환경 (임시 컨테이너 포함)",
    category: "dev",
    status: "critical",
    containers: { total: 2, running: 0 },
    endpoints: [],
    cpu_percent: null,
    memory_mb: null,
    last_deployed_at: iso(-7 * 86400_000),
    deployment_type: "docker-compose",
    deployment_path: "/srv/services/dev-playground",
    compose_file: "compose.yaml",
    tags: ["개발"],
    created_at: iso(-60 * 86400_000),
    updated_at: iso(-7 * 86400_000),
    last_healthcheck_at: null,
  },
  {
    id: "sample-app",
    name: "샘플 애플리케이션",
    description: "service.yaml 등록 검증용 샘플 서비스 (컨테이너 없음)",
    category: "web",
    status: "unknown",
    containers: { total: 0, running: 0 },
    endpoints: [],
    cpu_percent: null,
    memory_mb: null,
    last_deployed_at: null,
    deployment_type: "docker-compose",
    deployment_path: "/srv/services/sample-app",
    compose_file: "compose.yaml",
    tags: [],
    created_at: iso(-2 * 86400_000),
    updated_at: iso(-2 * 86400_000),
    last_healthcheck_at: null,
  },
];

const containers: ContainerListItem[] = [
  {
    id: "c-frontend", name: "ai-frontend", image: "ai-platform/frontend:1.4.2",
    state: "running", status: "Up 3 days (healthy)", management_state: "managed",
    service_id: "ai-platform", component_name: "frontend",
    compose_project: "ai-platform", compose_service: "frontend",
    ports: [{ host_ip: "127.0.0.1", host_port: 3000, container_port: 3000, protocol: "tcp" }],
    networks: [{ name: "proxy", ip_address: "172.20.0.4" }],
    started_at: iso(-3 * 86400_000), created_at: iso(-120 * 86400_000),
    restart_count: 0, health: "healthy", observed_at: iso(-14_000),
    cpu_percent: 1.2, memory_mb: 210,
  },
  {
    id: "c-backend", name: "ai-backend", image: "ai-platform/backend:1.4.2",
    state: "running", status: "Up 3 days (healthy)", management_state: "managed",
    service_id: "ai-platform", component_name: "backend",
    compose_project: "ai-platform", compose_service: "backend",
    ports: [{ host_ip: null, host_port: null, container_port: 8000, protocol: "tcp" }],
    networks: [{ name: "proxy", ip_address: "172.20.0.5" }, { name: "ai-net", ip_address: "172.21.0.3" }],
    started_at: iso(-3 * 86400_000), created_at: iso(-120 * 86400_000),
    restart_count: 1, health: "healthy", observed_at: iso(-14_000),
    cpu_percent: 12.6, memory_mb: 1840,
  },
  {
    id: "c-worker", name: "ai-worker", image: "ai-platform/worker:1.4.2",
    state: "running", status: "Up 3 days", management_state: "managed",
    service_id: "ai-platform", component_name: "worker",
    compose_project: "ai-platform", compose_service: "worker",
    ports: [], networks: [{ name: "ai-net", ip_address: "172.21.0.4" }],
    started_at: iso(-3 * 86400_000), created_at: iso(-120 * 86400_000),
    restart_count: 0, health: null, observed_at: iso(-14_000),
    cpu_percent: 4.4, memory_mb: 940,
  },
  {
    id: "c-postgres", name: "ai-postgres", image: "postgres:16-alpine",
    state: "running", status: "Up 3 days (healthy)", management_state: "managed",
    service_id: "ai-platform", component_name: "postgres",
    compose_project: "ai-platform", compose_service: "postgres",
    ports: [{ host_ip: null, host_port: null, container_port: 5432, protocol: "tcp" }],
    networks: [{ name: "ai-net", ip_address: "172.21.0.2" }],
    started_at: iso(-3 * 86400_000), created_at: iso(-120 * 86400_000),
    restart_count: 0, health: "healthy", observed_at: iso(-14_000),
    cpu_percent: 0.8, memory_mb: 130,
  },
  {
    id: "c-media-web", name: "media-web", image: "lscr.io/linuxserver/plex:latest",
    state: "running", status: "Up 6 hours", management_state: "managed",
    service_id: "media-server", component_name: "web",
    compose_project: "media-server", compose_service: "web",
    ports: [{ host_ip: "0.0.0.0", host_port: 32400, container_port: 32400, protocol: "tcp" }],
    networks: [{ name: "media-net", ip_address: "172.22.0.2" }],
    started_at: iso(-6 * 3600_000), created_at: iso(-200 * 86400_000),
    restart_count: 3, health: null, observed_at: iso(-14_000),
    cpu_percent: 5.7, memory_mb: 1450,
  },
  {
    id: "c-media-idx", name: "media-indexer", image: "media-server/indexer:1.2",
    state: "exited", status: "Exited (1) 4 hours ago", management_state: "managed",
    service_id: "media-server", component_name: "indexer",
    compose_project: "media-server", compose_service: "indexer",
    ports: [], networks: [{ name: "media-net", ip_address: "172.22.0.3" }],
    started_at: iso(-10 * 3600_000), created_at: iso(-200 * 86400_000),
    restart_count: 5, health: "unhealthy", observed_at: iso(-14_000),
    cpu_percent: null, memory_mb: null,
  },
  {
    id: "c-ha", name: "home-assistant", image: "ghcr.io/home-assistant/home-assistant:2026.10",
    state: "running", status: "Up 12 days", management_state: "managed",
    service_id: "home-assistant", component_name: "ui",
    compose_project: "home-assistant", compose_service: "home-assistant",
    ports: [{ host_ip: "0.0.0.0", host_port: 8123, container_port: 8123, protocol: "tcp" }],
    networks: [{ name: "host-net", ip_address: null }],
    started_at: iso(-12 * 86400_000), created_at: iso(-300 * 86400_000),
    restart_count: 0, health: null, observed_at: iso(-14_000),
    cpu_percent: 3.1, memory_mb: 620,
  },
  {
    id: "c-orphan-1", name: "old-nginx", image: "nginx:1.25",
    state: "running", status: "Up 40 days", management_state: "unmanaged",
    service_id: null, component_name: null,
    compose_project: null, compose_service: null,
    ports: [{ host_ip: "0.0.0.0", host_port: 8081, container_port: 80, protocol: "tcp" }],
    networks: [{ name: "bridge", ip_address: "172.17.0.2" }],
    started_at: iso(-40 * 86400_000), created_at: iso(-45 * 86400_000),
    restart_count: 2, health: null, observed_at: iso(-14_000),
    cpu_percent: 0.4, memory_mb: 42,
  },
  {
    id: "c-orphan-2", name: "tmp-redis", image: "redis:7",
    state: "running", status: "Up 2 days", management_state: "unmanaged",
    service_id: null, component_name: null,
    compose_project: "dev", compose_service: "redis",
    ports: [{ host_ip: "127.0.0.1", host_port: 6379, container_port: 6379, protocol: "tcp" }],
    networks: [{ name: "dev_default", ip_address: "172.23.0.2" }],
    started_at: iso(-2 * 86400_000), created_at: iso(-30 * 86400_000),
    restart_count: 0, health: null, observed_at: iso(-14_000),
    cpu_percent: 0.9, memory_mb: 88,
  },
  {
    id: "c-mismatch", name: "playground-web", image: "dev/playground:2.0",
    state: "running", status: "Up 5 hours", management_state: "mismatch",
    service_id: "dev-playground", component_name: "web",
    compose_project: "dev-playground", compose_service: "web",
    ports: [{ host_ip: "0.0.0.0", host_port: 5001, container_port: 5000, protocol: "tcp" }],
    networks: [{ name: "dev_default", ip_address: "172.23.0.5" }],
    started_at: iso(-5 * 3600_000), created_at: iso(-10 * 86400_000),
    restart_count: 1, health: null, observed_at: iso(-14_000),
    cpu_percent: 2.2, memory_mb: 260,
  },
  {
    id: "c-missing", name: "playground-worker", image: "dev/playground-worker:2.0",
    state: "stopped", status: "없음 (컨테이너 미확인)", management_state: "missing",
    service_id: "dev-playground", component_name: "worker",
    compose_project: "dev-playground", compose_service: "worker",
    ports: [], networks: [],
    started_at: null, created_at: iso(-10 * 86400_000),
    restart_count: 0, health: null, observed_at: iso(-14_000),
    cpu_percent: null, memory_mb: null,
  },
  {
    id: "c-unknown", name: "mystery-app", image: "(확인되지 않은 정보)",
    state: "unknown", status: "확인되지 않은 상태", management_state: "unknown",
    service_id: null, component_name: null,
    compose_project: null, compose_service: null,
    ports: [], networks: [],
    started_at: null, created_at: null,
    restart_count: 0, health: null, observed_at: null,
    cpu_percent: null, memory_mb: null,
  },
];

const containerDetails: Record<string, ContainerDetail> = Object.fromEntries(
  containers.map((c) => [
    c.id,
    {
      ...c,
      mounts:
        c.service_id === "ai-platform" && c.component_name === "postgres"
          ? [{ type: "volume", source: "ai-platform_pgdata", target: "/var/lib/postgresql/data", mode: "rw" }]
          : [{ type: "bind", source: `/srv/services/${c.service_id ?? "unknown"}/config`, target: "/config", mode: "ro" }],
      labels: {
        "hub.managed": c.management_state === "managed" ? "true" : "false",
        "com.docker.compose.project": c.compose_project ?? "",
        "com.docker.compose.service": c.compose_service ?? "",
      },
      stats: {
        cpu_percent: c.cpu_percent ?? null,
        mem_used_mb: c.memory_mb ?? null,
        mem_limit_mb: c.memory_mb != null ? c.memory_mb * 2 : null,
        net_rx_bytes: 128_400_000,
        net_tx_bytes: 44_100_000,
        block_read_bytes: 8_400_000,
        block_write_bytes: 3_200_000,
      },
    },
  ]),
);

const orphans: OrphanItem[] = containers
  .filter((c) => c.management_state === "unmanaged")
  .map((c) => ({
    id: c.id,
    name: c.name,
    image: c.image,
    state: c.state,
    ports: c.ports,
    networks: c.networks,
    created_at: c.created_at,
    compose_project: c.compose_project,
    suspected_service_id: c.name.includes("redis") ? "dev-playground" : null,
    suspected_service_name: c.name.includes("redis") ? "Dev Playground" : null,
    reason: c.compose_project
      ? "Compose 프로젝트는 감지되었으나 서비스 레지스트리에 등록되지 않음"
      : "서비스 컴포넌트/Compose 라벨 매칭 없음",
    review_state: "pending",
    service_id: null,
  }));

const ports: PortEntry[] = [
  { reservation_id: "r-1", service_id: "ai-platform", service_name: "AI Platform", component: "frontend", protocol: "tcp", host_port: 3000, bind_addr: "127.0.0.1", container_port: 3000, exposure: "proxy", state: "in_use", occupied: true, occupied_by: "ai-frontend", hostname: "ai.home", proxy_connected: true, last_checked_at: iso(-14_000) },
  { reservation_id: "r-2", service_id: "media-server", service_name: "Media Server", component: "web", protocol: "tcp", host_port: 32400, bind_addr: "0.0.0.0", container_port: 32400, exposure: "public", state: "in_use", occupied: true, occupied_by: "media-web", hostname: null, proxy_connected: false, last_checked_at: iso(-14_000) },
  { reservation_id: "r-3", service_id: "home-assistant", service_name: "Home Assistant", component: "ui", protocol: "tcp", host_port: 8123, bind_addr: "0.0.0.0", container_port: 8123, exposure: "proxy", state: "in_use", occupied: true, occupied_by: "home-assistant", hostname: "ha.home", proxy_connected: true, last_checked_at: iso(-14_000) },
  { reservation_id: "r-4", service_id: "dev-playground", service_name: "Dev Playground", component: "web", protocol: "tcp", host_port: 5001, bind_addr: "0.0.0.0", container_port: 5000, exposure: "public", state: "conflict", occupied: true, occupied_by: "playground-web (등록과 실제 매핑 불일치: 5000→5001)", hostname: null, proxy_connected: false, last_checked_at: iso(-14_000) },
  { reservation_id: "r-5", service_id: "sample-app", service_name: "샘플 애플리케이션", component: "backend", protocol: "tcp", host_port: 8010, bind_addr: "127.0.0.1", container_port: 8000, exposure: "internal", state: "reserved", occupied: false, occupied_by: null, hostname: null, proxy_connected: false, last_checked_at: iso(-14_000) },
  { reservation_id: null, service_id: null, service_name: null, component: null, protocol: "tcp", host_port: 8081, bind_addr: "0.0.0.0", container_port: 80, exposure: "public", state: "unmanaged", occupied: true, occupied_by: "old-nginx", hostname: null, proxy_connected: false, last_checked_at: iso(-14_000) },
  { reservation_id: null, service_id: null, service_name: null, component: null, protocol: "tcp", host_port: 6379, bind_addr: "127.0.0.1", container_port: 6379, exposure: "internal", state: "unmanaged", occupied: true, occupied_by: "tmp-redis", hostname: null, proxy_connected: false, last_checked_at: iso(-14_000) },
  { reservation_id: null, service_id: null, service_name: null, component: null, protocol: "tcp", host_port: 8420, bind_addr: "0.0.0.0", container_port: 8420, exposure: "internal", state: "proxy", occupied: true, occupied_by: "service-hub (자기 자신)", hostname: null, proxy_connected: false, last_checked_at: iso(-14_000) },
];

const events: HubEvent[] = [
  { id: "e-1", ts: iso(-4 * 60_000), severity: "critical", kind: "container.mismatch", service_id: "dev-playground", container_id: "c-mismatch", message: "포트 매핑 불일치: 등록 5000 → 실제 5001", detail: { container: "playground-web" } },
  { id: "e-2", ts: iso(-9 * 60_000), severity: "warning", kind: "resource.memory", service_id: null, container_id: null, message: "메모리 사용률 82% — 주의 임계값(80%) 초과" },
  { id: "e-3", ts: iso(-22 * 60_000), severity: "warning", kind: "orphan.detected", service_id: null, container_id: "c-orphan-1", message: "미관리 컨테이너 발견: old-nginx (nginx:1.25)" },
  { id: "e-4", ts: iso(-65 * 60_000), severity: "info", kind: "container.restarted", service_id: "media-server", container_id: "c-media-web", message: "컨테이너 재시작됨: media-web" },
  { id: "e-5", ts: iso(-4 * 3600_000), severity: "error", kind: "container.exited", service_id: "media-server", container_id: "c-media-idx", message: "컨테이너 종료됨: media-indexer (exit code 1)" },
  { id: "e-6", ts: iso(-26 * 3600_000), severity: "info", kind: "deployment.succeeded", service_id: "ai-platform", container_id: null, message: "배포 성공: ai-platform (v1.4.2)" },
  { id: "e-7", ts: iso(-3 * 86400_000), severity: "info", kind: "service.updated", service_id: "home-assistant", container_id: null, message: "서비스 설명 수정됨" },
  { id: "e-8", ts: iso(-5 * 86400_000), severity: "warning", kind: "port.conflict", service_id: "dev-playground", container_id: null, message: "포트 충돌 감지: 5001/tcp" },
];

const resourceWarnings: ResourceWarning[] = [
  { level: "warning", scope: "memory", message: "호스트 메모리 사용률 82% — 주의 임계값 80%", value: 82, threshold: 80 },
  { level: "warning", scope: "disk", message: "/var/lib/docker 디렉터리 증가 추세: 주 4.2GB", value: 4.2, threshold: null },
  { level: "critical", scope: "cpu", message: "cpu 부하가 95%를 120초 이상 지속 (임계 60초)", value: 120, threshold: 60 },
];

const deployments: Deployment[] = [
  {
    id: "dep-20261018-001", service_id: "ai-platform", status: "succeeded",
    requested_by: "admin (CLI hub deploy apply)", error: null,
    started_at: iso(-3 * 86400_000), finished_at: iso(-3 * 86400_000 + 140_000),
    steps: [
      { seq: 1, name: "service.yaml 스키마 검증", status: "succeeded", at: iso(-3 * 86400_000) },
      { seq: 2, name: "포트 충돌 확인", status: "succeeded", at: iso(-3 * 86400_000 + 4_000) },
      { seq: 3, name: "Compose 구성 검증", status: "succeeded", at: iso(-3 * 86400_000 + 9_000) },
      { seq: 4, name: "이미지 빌드/다운로드", status: "succeeded", detail: "4개 이미지 최신 확인", at: iso(-3 * 86400_000 + 60_000) },
      { seq: 5, name: "Compose 프로젝트 배포", status: "succeeded", at: iso(-3 * 86400_000 + 120_000) },
      { seq: 6, name: "헬스체크", status: "succeeded", detail: "frontend/backend healthy", at: iso(-3 * 86400_000 + 135_000) },
      { seq: 7, name: "포트/라우팅 검증", status: "succeeded", at: iso(-3 * 86400_000 + 138_000) },
      { seq: 8, name: "배포 이력 기록", status: "succeeded", at: iso(-3 * 86400_000 + 140_000) },
    ],
  },
  {
    id: "dep-20261017-003", service_id: "media-server", status: "failed",
    requested_by: "admin (웹 대시보드)", error: "헬스체크 실패: media-indexer가 30초 내 응답하지 않음",
    started_at: iso(-4 * 86400_000), finished_at: iso(-4 * 86400_000 + 95_000),
    steps: [
      { seq: 1, name: "service.yaml 스키마 검증", status: "succeeded", at: iso(-4 * 86400_000) },
      { seq: 2, name: "포트 충돌 확인", status: "succeeded", at: iso(-4 * 86400_000 + 3_000) },
      { seq: 3, name: "Compose 구성 검증", status: "succeeded", at: iso(-4 * 86400_000 + 7_000) },
      { seq: 4, name: "Compose 프로젝트 배포", status: "succeeded", at: iso(-4 * 86400_000 + 70_000) },
      { seq: 5, name: "헬스체크", status: "failed", detail: "media-indexer unhealthy (exit 1)", at: iso(-4 * 86400_000 + 95_000) },
    ],
  },
  {
    id: "dep-20261021-002", service_id: "sample-app", status: "queued",
    requested_by: "ai-agent (API)", error: null,
    started_at: iso(-30_000), finished_at: null,
    steps: [{ seq: 1, name: "대기 중", status: "pending", at: iso(-30_000) }],
  },
];

const auditLogs: AuditLog[] = [
  { id: "a-1", ts: iso(-2 * 3600_000), actor: "admin", action: "service.update", target: "home-assistant", detail: { fields: ["description"] } },
  { id: "a-2", ts: iso(-26 * 3600_000), actor: "admin", action: "deployment.apply", target: "ai-platform", detail: { deployment_id: "dep-20261018-001" } },
  { id: "a-3", ts: iso(-30 * 3600_000), actor: "ai-agent", action: "port.reserve", target: "8010/tcp", detail: { service_id: "sample-app" } },
  { id: "a-4", ts: iso(-3 * 86400_000), actor: "admin", action: "settings.update", target: "thresholds", detail: { memory_warn_percent: 80 } },
  { id: "a-5", ts: iso(-6 * 86400_000), actor: "admin", action: "orphan.attach", target: "c-orphan-2", detail: { service_id: "dev-playground" } },
];

function samples(): HostResources["samples"] {
  const pts = 60;
  return Array.from({ length: pts }, (_, i) => {
    const t = now - (pts - i) * 60_000;
    const wobble = Math.sin(i / 4) * 6;
    return {
      ts: new Date(t).toISOString(),
      cpu_percent: Math.max(3, Math.min(97, 24 + wobble + (i % 7))),
      mem_used_mb: Math.round(9600 + i * 6 + Math.sin(i / 5) * 120),
      mem_limit_mb: 16384,
      net_rx_bytes: Math.round(1_400_000 + i * 8_000 + Math.sin(i / 3) * 40_000),
      net_tx_bytes: Math.round(600_000 + i * 3_000 + Math.cos(i / 3) * 20_000),
      disk_used_gb: Number((312 + i * 0.08).toFixed(1)),
    };
  });
}

const hostResources: HostResources = {
  cpu: { percent: 23.5, cores: 4, per_core: [18, 31, 12, 33], load_avg: [1.2, 0.9, 0.8] },
  memory: { total_mb: 16384, used_mb: 13440, available_mb: 2944, cached_mb: 4096, percent: 82, swap_total_mb: 8192, swap_used_mb: 512 },
  disk: {
    total_gb: 500, used_gb: 320, percent: 64,
    filesystems: [
      { mount: "/", total_gb: 500, used_gb: 320, percent: 64 },
      { mount: "/var/lib/docker", total_gb: 500, used_gb: 214, percent: 43 },
    ],
    docker_data_gb: 214,
  },
  network: {
    interfaces: [
      { name: "eth0", rx_bps: 1_400_000, tx_bps: 620_000, rx_total_bytes: 428_000_000_000, tx_total_bytes: 191_000_000_000, errors: 0 },
      { name: "docker0", rx_bps: 320_000, tx_bps: 210_000, rx_total_bytes: 88_000_000_000, tx_total_bytes: 64_000_000_000, errors: 0 },
    ],
  },
  system: { hostname: "n100-server", os: "Debian GNU/Linux 12", kernel: "6.1.0-25-amd64", booted_at: iso(-12 * 86400_000), uptime_seconds: 12 * 86400 + 4 * 3600, cpu_temp_c: 48 },
  samples: samples(),
  collected_at: iso(-10_000),
};

const containerResources: ContainerResourceRow[] = containers
  .filter((c) => c.state === "running")
  .map((c) => ({
    container_id: c.id,
    name: c.name,
    service_id: c.service_id,
    service_name: services.find((s) => s.id === c.service_id)?.name ?? null,
    state: c.state,
    health: c.health,
    cpu_percent: c.cpu_percent ?? null,
    mem_used_mb: c.memory_mb ?? null,
    mem_limit_mb: (c.memory_mb ?? 0) * 2 || null,
    net_rx_bytes: 128_400_000,
    net_tx_bytes: 44_100_000,
    restart_count: c.restart_count,
  }));

const serviceResources: ServiceResourceRow[] = services.map((s) => ({
  service_id: s.id,
  name: s.name,
  status: s.status,
  cpu_percent: s.cpu_percent,
  memory_mb: s.memory_mb,
  containers_total: s.containers.total,
  containers_running: s.containers.running,
  restart_count: containers
    .filter((c) => c.service_id === s.id)
    .reduce((n, c) => n + c.restart_count, 0),
}));

const overview: SystemOverview = {
  server: { hostname: "n100-server", os: "Debian GNU/Linux 12", kernel: "6.1.0-25-amd64", uptime_seconds: 12 * 86400 + 4 * 3600, booted_at: iso(-12 * 86400_000) },
  docker: { connected: true, server_version: "27.3.1" },
  resources: {
    cpu: { percent: 23.5, cores: 4, per_core: [18, 31, 12, 33] },
    memory: { total_mb: 16384, used_mb: 13440, available_mb: 2944, percent: 82 },
    disk: { total_gb: 500, used_gb: 320, percent: 64 },
  },
  counts: {
    services: services.length,
    containers_running: containers.filter((c) => c.state === "running").length,
    containers_stopped: containers.filter((c) => c.state !== "running").length,
    orphans: orphans.length,
  },
  last_monitor_ok_at: iso(-10_000),
  recent_events: events.slice(0, 6),
};

const status: SystemStatus = {
  monitor: { running: true, interval_seconds: 15, last_ok_at: iso(-10_000), last_error: null, consecutive_errors: 0 },
  docker: { connected: true, server_version: "27.3.1" },
  hub: { name: settings.hub_name, version: "0.1.0", deploy_enabled: false },
  last_monitor_ok_at: iso(-10_000),
  stale: false,
};

/* ------------------------------ 라우터 ------------------------------ */

function json(body: unknown, status_ = 200): { status: number; body: unknown } {
  return { status: status_, body };
}

function error(detail: string, code: string, status_ = 400) {
  return { status: status_, body: { detail, code } };
}

const serviceDetail = (id: string): ServiceDetail | null => {
  const s = services.find((x) => x.id === id);
  if (!s) return null;
  return {
    ...s,
    components:
      id === "ai-platform"
        ? [
            { name: "frontend", role: "frontend", required: true, description: "Next.js 웹 UI", container_match: ["ai-frontend"] },
            { name: "backend", role: "backend", required: true, description: "FastAPI 추론 API", container_match: ["ai-backend"] },
            { name: "worker", role: "worker", required: false, description: "비동기 작업 큐", container_match: ["ai-worker"] },
            { name: "postgres", role: "database", required: true, description: "메인 데이터베이스", container_match: ["ai-postgres"] },
          ]
        : containers
            .filter((c) => c.service_id === id)
            .map((c) => ({
              name: c.component_name ?? c.name,
              role: c.component_name ?? "component",
              required: true,
              description: null,
              container_match: [c.name],
            })),
    warnings:
      s.status === "critical"
        ? [{ level: "critical", message: "등록된 컨테이너가 하나도 실행되고 있지 않습니다." }]
        : s.status === "warn"
          ? [{ level: "warning", message: "필수 컨테이너 1개가 중지 상태입니다." }]
          : [],
  };
};

export async function mockRequest(
  pathWithQuery: string,
  init: RequestInit,
): Promise<{ status: number; body: unknown }> {
  const [rawPath, qs] = pathWithQuery.split("?");
  const path = rawPath ?? pathWithQuery;
  const query = new URLSearchParams(qs ?? "");
  const method = (init.method ?? "GET").toUpperCase();
  const body = init.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : {};

  // 인증
  if (path === "/auth/session") return json(session());
  if (path === "/auth/login" && method === "POST") {
    if (!body.username || !body.password) return error("아이디와 비밀번호를 입력하세요.", "invalid_credentials", 401);
    return json(session());
  }
  if (path === "/auth/logout" && method === "POST") return json({ ok: true });
  if (path === "/setup/admin" && method === "POST") {
    if (typeof body.password !== "string" || body.password.length < 8) {
      return error("비밀번호는 8자 이상이어야 합니다.", "weak_password", 422);
    }
    return json({ ...session(), user: { username: String(body.username ?? "admin"), role: "admin" } }, 201);
  }

  // 시스템
  if (path === "/system/overview") return json(overview);
  if (path === "/system/status") return json(status);
  if (path === "/system/settings" && method === "GET") return json(settings);
  if (path === "/system/settings" && method === "PUT") {
    Object.assign(settings, body);
    return json(settings);
  }

  // 서비스
  if (path === "/services" && method === "GET") {
    const search = (query.get("search") ?? "").toLowerCase();
    const st = query.get("status") ?? "";
    const cat = query.get("category") ?? "";
    const list = services.filter(
      (s) =>
        (!search ||
          s.name.toLowerCase().includes(search) ||
          s.id.includes(search) ||
          s.description.toLowerCase().includes(search)) &&
        (!st || s.status === st) &&
        (!cat || s.category === cat),
    );
    return json(list);
  }
  if (path === "/services" && method === "POST") {
    const svc = (body.service ?? {}) as Record<string, unknown>;
    const id = String(svc.id ?? "");
    if (!id) return error("서비스 id는 필수입니다.", "missing_service_id", 422);
    if (services.some((s) => s.id === id)) return error(`이미 존재하는 서비스 id입니다: ${id}`, "duplicate_service_id", 409);
    const created: ServiceListItem = {
      id,
      name: String(svc.name ?? id),
      description: String(svc.description ?? ""),
      category: String(svc.category ?? "web"),
      status: "unknown",
      containers: { total: 0, running: 0 },
      endpoints: [],
      cpu_percent: null,
      memory_mb: null,
      last_deployed_at: null,
      deployment_type: String((body.deployment as Record<string, unknown>)?.type ?? "docker-compose"),
      deployment_path: String((body.deployment as Record<string, unknown>)?.deployment_path ?? `/srv/services/${id}`),
      compose_file: String((body.deployment as Record<string, unknown>)?.compose_file ?? "compose.yaml"),
      tags: (body.tags as string[]) ?? [],
      created_at: iso(0),
      updated_at: iso(0),
    };
    services.push(created);
    return json(created, 201);
  }

  const svcMatch = path.match(/^\/services\/([^/]+)(?:\/(containers|endpoints|logs|events))?$/);
  if (svcMatch) {
    const id = decodeURIComponent(svcMatch[1]);
    const sub = svcMatch[2];
    if (!sub) {
      const detail = serviceDetail(id);
      if (!detail) return error(`서비스를 찾을 수 없습니다: ${id}`, "not_found", 404);
      if (method === "PATCH") {
        Object.assign(detail, body);
        const base = services.find((s) => s.id === id);
        if (base) Object.assign(base, body);
        return json(detail);
      }
      if (method === "DELETE") {
        const idx = services.findIndex((s) => s.id === id);
        if (idx >= 0) services.splice(idx, 1);
        return json({ deleted: true, id, runtime_unchanged: true });
      }
      return json(detail);
    }
    if (sub === "containers") return json(containers.filter((c) => c.service_id === id));
    if (sub === "endpoints") {
      const d = serviceDetail(id);
      return json(d?.endpoints ?? []);
    }
    if (sub === "logs") {
      const tail = Number(query.get("tail") ?? 200);
      const lines = Array.from({ length: Math.min(tail, 40) }, (_, i) => ({
        ts: iso(-(40 - i) * 60_000),
        stream: i % 5 === 0 ? "stderr" : "stdout",
        message: `[${id}] 요청 처리 완료 (${i + 1}/${40})`,
      }));
      return json({ lines });
    }
    if (sub === "events") return json(events.filter((e) => e.service_id === id));
  }

  // 컨테이너
  if (path === "/containers" && method === "GET") {
    const st = query.get("state");
    const mg = query.get("management");
    const list = containers.filter((c) => {
      if (st === "running" && c.state !== "running") return false;
      if (st === "stopped" && c.state === "running") return false;
      if (mg && c.management_state !== mg) return false;
      return true;
    });
    return json(list);
  }
  const cMatch = path.match(/^\/containers\/([^/]+)$/);
  if (cMatch) {
    const d = containerDetails[decodeURIComponent(cMatch[1])];
    if (!d) return error("컨테이너를 찾을 수 없습니다.", "not_found", 404);
    return json(d);
  }

  // 미관리
  if (path === "/orphans" && method === "GET") return json(orphans);
  const oMatch = path.match(/^\/orphans\/([^/]+)\/(attach|review)$/);
  if (oMatch && method === "POST") {
    return json({ ok: true, id: decodeURIComponent(oMatch[1]), ...body });
  }

  // 포트
  if (path === "/ports" && method === "GET") return json(ports);
  if (path === "/ports/available") {
    const count = Number(query.get("count") ?? 5);
    const range = query.get("range") ?? "8000-9000";
    const proto = query.get("protocol") ?? "tcp";
    const [lo, hi] = range.split("-").map(Number);
    const used = new Set(
      ports.filter((p) => p.protocol === proto).map((p) => p.host_port),
    );
    const out: number[] = [];
    for (let p = lo || 8000; p <= (hi || 9000) && out.length < count; p++) {
      if (!used.has(p)) out.push(p);
    }
    return json({ ports: out, count, range, protocol: proto });
  }
  if (path === "/ports/reservations" && method === "POST") {
    const hp = Number(body.host_port);
    if (!Number.isInteger(hp) || hp < 1 || hp > 65535) {
      return error("포트는 1~65535 사이여야 합니다.", "invalid_port", 422);
    }
    const dup = ports.find(
      (p) => p.protocol === String(body.protocol) && p.host_port === hp && p.bind_addr === String(body.bind_addr),
    );
    if (dup) {
      return error(
        `충돌: ${dup.bind_addr}:${hp}/${body.protocol}은(는) 이미 사용 중입니다.`,
        "port_conflict",
        409,
      );
    }
    const entry: PortEntry = {
      reservation_id: `r-${Date.now()}`,
      service_id: String(body.service_id ?? ""),
      service_name: services.find((s) => s.id === body.service_id)?.name ?? null,
      component: String(body.component ?? ""),
      protocol: String(body.protocol ?? "tcp"),
      host_port: hp,
      bind_addr: String(body.bind_addr ?? "0.0.0.0"),
      container_port: body.container_port != null ? Number(body.container_port) : null,
      exposure: (body.exposure as string) ?? "internal",
      state: "reserved",
      occupied: false,
      occupied_by: null,
      hostname: null,
      proxy_connected: false,
      last_checked_at: iso(0),
    };
    ports.push(entry);
    return json(entry, 201);
  }
  const rMatch = path.match(/^\/ports\/reservations\/([^/]+)$/);
  if (rMatch && method === "DELETE") {
    const id = decodeURIComponent(rMatch[1]);
    const idx = ports.findIndex((p) => p.reservation_id === id);
    if (idx < 0) return error("예약을 찾을 수 없습니다.", "not_found", 404);
    ports.splice(idx, 1);
    return json({ deleted: true, id });
  }

  // 자원
  if (path === "/resources/host") return json(hostResources);
  if (path === "/resources/containers") return json(containerResources);
  if (path === "/resources/services") return json(serviceResources);
  if (path === "/resources/warnings") return json(resourceWarnings);

  // 배포
  if (path === "/deployments" && method === "GET") {
    const sid = query.get("service_id");
    return json(sid ? deployments.filter((d) => d.service_id === sid) : deployments);
  }
  const dMatch = path.match(/^\/deployments\/([^/]+)(?:\/logs)?$/);
  if (dMatch) {
    const id = decodeURIComponent(dMatch[1]);
    const d = deployments.find((x) => x.id === id);
    if (!d) return error("배포 기록을 찾을 수 없습니다.", "not_found", 404);
    if (path.endsWith("/logs")) {
      return json({
        lines: (d.steps ?? []).map((s) => ({
          ts: s.at ?? null,
          message: `[${s.status}] ${s.name}${s.detail ? ` — ${s.detail}` : ""}`,
        })),
      });
    }
    return json(d);
  }

  // 이벤트/감사/검색
  if (path === "/events" && method === "GET") {
    const sev = query.get("severity");
    const sid = query.get("service_id");
    const limit = Number(query.get("limit") ?? 100);
    return json(
      events
        .filter((e) => (!sev || e.severity === sev) && (!sid || e.service_id === sid))
        .slice(0, limit),
    );
  }
  if (path === "/audit-logs") {
    return json(auditLogs.slice(0, Number(query.get("limit") ?? 100)));
  }
  if (path === "/search") {
    const q = (query.get("q") ?? "").toLowerCase();
    if (!q) return json({ services: [], containers: [], ports: [], domains: [], images: [] });
    return json({
      services: services
        .filter((s) => s.name.toLowerCase().includes(q) || s.id.includes(q))
        .map((s) => ({ id: s.id, name: s.name, description: s.description, status: s.status })),
      containers: containers
        .filter((c) => c.name.includes(q) || c.id.includes(q))
        .map((c) => ({ id: c.id, name: c.name, image: c.image, state: c.state, service_id: c.service_id })),
      ports: ports
        .filter((p) => String(p.host_port).includes(q))
        .map((p) => ({ id: `${p.protocol}-${p.host_port}`, label: `${p.host_port}/${p.protocol}`, service_id: p.service_id, protocol: p.protocol })),
      domains: ports
        .filter((p) => p.hostname?.toLowerCase().includes(q))
        .map((p) => ({ id: p.hostname, hostname: p.hostname, service_id: p.service_id, exposure: p.exposure })),
      images: [...new Set(containers.map((c) => c.image))].filter((i) => i.toLowerCase().includes(q)),
    });
  }

  return error(`목 어댑터에 정의되지 않은 경로입니다: ${method} ${path}`, "mock_unhandled", 404);
}
