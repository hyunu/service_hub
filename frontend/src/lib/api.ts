/**
 * N100 Service Hub — 백엔드 API 클라이언트 (계약: docs/ARCHITECTURE.md §3 "API 계약 v1")
 *
 * - prefix: /api/v1 (Vite dev proxy → http://127.0.0.1:8420)
 * - 오류: HTTP 오류 시 `{"detail": "...", "code": "..."}` → ApiError throw
 * - 시간: 전부 ISO 8601 (로컬 오프셋 포함) — 포맷은 lib/format.ts 사용
 * - CSRF: 세션 응답의 csrf_token을 받아 변경 메서드에 X-CSRF-Token 헤더로 전송
 * - 개발용 목(mock): VITE_API_MOCK=true 이면 lib/mock.ts 어댑터로 응답
 */

import { mockRequest } from "./mock";

export const API_PREFIX = "/api/v1";

/* ------------------------------------------------------------------ */
/* 오류                                                                */
/* ------------------------------------------------------------------ */

export class ApiError extends Error {
  readonly status: number;
  readonly code: string | null;
  readonly payload: unknown;

  constructor(detail: string, status: number, code?: string | null, payload?: unknown) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.code = code ?? null;
    this.payload = payload ?? null;
  }

  /** 입력 검증 오류 등에서 서버가 돌려준 필드별 메시지 */
  get fieldErrors(): Record<string, string> | null {
    const p = this.payload;
    if (p && typeof p === "object" && "errors" in p) {
      const errs = (p as { errors: unknown }).errors;
      if (errs && typeof errs === "object" && !Array.isArray(errs)) {
        const out: Record<string, string> = {};
        for (const [k, v] of Object.entries(errs as Record<string, unknown>)) {
          out[k] = Array.isArray(v) ? v.map(String).join(", ") : String(v);
        }
        return out;
      }
    }
    return null;
  }
}

export function isApiError(e: unknown): e is ApiError {
  return e instanceof ApiError;
}

/** 인증 세션 만료/미로그인 감지 리스너 */
type UnauthorizedListener = () => void;
const unauthorizedListeners = new Set<UnauthorizedListener>();

export function onUnauthorized(fn: UnauthorizedListener): () => void {
  unauthorizedListeners.add(fn);
  return () => unauthorizedListeners.delete(fn);
}

/* ------------------------------------------------------------------ */
/* CSRF                                                                */
/* ------------------------------------------------------------------ */

let csrfToken: string | null = null;

export function setCsrfToken(token: string | null): void {
  csrfToken = token;
}

export function getCsrfToken(): string | null {
  return csrfToken;
}

/* ------------------------------------------------------------------ */
/* 타입                                                                */
/* ------------------------------------------------------------------ */

export type ServiceStatus = "ok" | "warn" | "critical" | "unknown";
export type ManagementState =
  | "managed"
  | "unmanaged"
  | "mismatch"
  | "missing"
  | "unknown";
export type ContainerStateKind = "running" | "stopped" | "all";
export type Exposure = "public" | "proxy" | "direct" | "internal" | "host";
export type Protocol = "tcp" | "udp";

/** 포트 레지스트리 상태 (사양 §11.6) */
export type PortState =
  | "reserved"
  | "in_use"
  | "available"
  | "conflict"
  | "unmanaged"
  | "proxy"
  | "internal";

export type Severity = "info" | "warning" | "error" | "critical";

export type DeploymentStatus =
  | "queued"
  | "validating"
  | "running"
  | "verifying"
  | "succeeded"
  | "failed"
  | "cancelled";

/* ---------------------------- 시스템 ------------------------------ */

export interface SystemOverview {
  server: {
    hostname: string;
    os: string;
    kernel: string;
    uptime_seconds: number | null;
    booted_at: string | null;
  };
  docker: { connected: boolean; server_version: string | null };
  resources: {
    cpu: { percent: number | null; cores: number | null; per_core?: number[] | null };
    memory: {
      total_mb: number | null;
      used_mb: number | null;
      available_mb: number | null;
      percent: number | null;
    };
    disk: { total_gb: number | null; used_gb: number | null; percent: number | null };
  };
  counts: {
    services: number;
    containers_running: number;
    containers_stopped: number;
    orphans: number;
  };
  last_monitor_ok_at: string | null;
  recent_events: HubEvent[];
}

export interface SystemStatus {
  monitor?: {
    running?: boolean;
    interval_seconds?: number;
    last_ok_at?: string | null;
    last_error?: string | null;
    consecutive_errors?: number;
  };
  docker?: { connected?: boolean; server_version?: string | null };
  hub?: { name?: string; version?: string; deploy_enabled?: boolean };
  last_monitor_ok_at?: string | null;
  /** 데이터 수집이 오래되었는지 여부(서버 판정 우선, 없으면 클라이언트 계산) */
  stale?: boolean;
}

export interface ThresholdSettings {
  memory_warn_percent?: number;
  memory_critical_percent?: number;
  disk_warn_percent?: number;
  disk_critical_percent?: number;
  cpu_warn_percent?: number;
  cpu_critical_percent?: number;
  cpu_sustained_seconds?: number;
}

export interface HubSettings {
  hub_name: string;
  monitor_interval_seconds: number;
  thresholds: ThresholdSettings;
  bind?: {
    host?: string;
    port?: number;
    internal_only?: boolean;
    [k: string]: unknown;
  };
  [key: string]: unknown;
}

/* --------------------------- 서비스 ------------------------------- */

export interface ServiceEndpoint {
  name: string;
  type: string;
  exposure: Exposure;
  hostname: string | null;
  container: string | null;
  container_port: number | null;
  enabled?: boolean;
}

export interface ServiceListItem {
  id: string;
  name: string;
  description: string;
  category: string;
  status: ServiceStatus;
  containers: { total: number; running: number };
  endpoints: ServiceEndpoint[];
  cpu_percent: number | null;
  memory_mb: number | null;
  last_deployed_at: string | null;
  deployment_type?: string;
  deployment_path?: string | null;
  compose_file?: string | null;
  repository_url?: string | null;
  repository_branch?: string | null;
  version?: string | null;
  documentation?: string | null;
  tags?: string[];
  created_at?: string | null;
  updated_at?: string | null;
  last_healthcheck_at?: string | null;
}

export interface ServiceComponent {
  name: string;
  role: string;
  required: boolean;
  description?: string | null;
  container_match?: string[];
}

export interface ServiceWarning {
  level?: Severity | string;
  message: string;
}

export interface ServiceDetail extends ServiceListItem {
  components: ServiceComponent[];
  warnings?: ServiceWarning[];
  notes?: string | null;
}

export interface ServiceListQuery {
  search?: string;
  status?: string;
  category?: string;
}

/** POST /services — 등록 폼 또는 service.yaml 내용(JSON 문자열) */
export interface ServiceCreatePayload {
  yaml?: string;
  service?: {
    id: string;
    name: string;
    description: string;
    category: string;
    version?: string;
  };
  deployment?: {
    type?: string;
    deployment_path?: string;
    compose_file?: string;
  };
  repository_url?: string;
  repository_branch?: string;
  documentation?: string;
  tags?: string[];
  [key: string]: unknown;
}

export interface ServiceUpdatePayload {
  description?: string;
  documentation?: string | null;
  tags?: string[];
  notes?: string | null;
  [key: string]: unknown;
}

export interface DeleteResult {
  runtime_unchanged?: boolean;
  deleted?: boolean;
  id?: string;
}

/* -------------------------- 컨테이너 ------------------------------ */

export interface PortMapping {
  host_ip: string | null;
  host_port: number | null;
  container_port: number;
  protocol: string;
}

export type NetworkRef = string | { name: string; ip_address?: string | null };

export interface ContainerListItem {
  id: string;
  name: string;
  image: string;
  state: string;
  status: string;
  management_state: ManagementState;
  service_id: string | null;
  component_name: string | null;
  compose_project: string | null;
  compose_service: string | null;
  ports: PortMapping[];
  networks: NetworkRef[];
  started_at: string | null;
  created_at: string | null;
  restart_count: number;
  health: string | null;
  observed_at: string | null;
  cpu_percent?: number | null;
  memory_mb?: number | null;
  /** 수동 그룹핑(container_assignments)으로 연결되었는가 */
  manual?: boolean;
}

export interface ContainerMount {
  type: string;
  source: string;
  target: string;
  mode?: string;
}

export interface ContainerStats {
  cpu_percent?: number | null;
  mem_used_mb?: number | null;
  mem_limit_mb?: number | null;
  net_rx_bytes?: number | null;
  net_tx_bytes?: number | null;
  block_read_bytes?: number | null;
  block_write_bytes?: number | null;
}

export interface ContainerDetail extends ContainerListItem {
  mounts: ContainerMount[];
  labels: Record<string, string>;
  stats: ContainerStats | null;
}

export interface ContainerQuery {
  state?: ContainerStateKind;
  management?: ManagementState;
}

/* --------------------------- 미관리 ------------------------------- */

export interface OrphanItem {
  id: string;
  name: string;
  image: string;
  state: string;
  ports?: PortMapping[];
  networks?: NetworkRef[];
  mounts?: ContainerMount[];
  created_at?: string | null;
  compose_project?: string | null;
  suspected_service_id?: string | null;
  suspected_service_name?: string | null;
  reason?: string | null;
  review_state?: string | null;
  service_id?: string | null;
}

export interface AttachPayload {
  service_id: string;
  component_name: string;
}

export interface ReviewPayload {
  review_state: string;
}

/* ---------------------------- 포트 --------------------------------- */

export interface PortEntry {
  /** 예약 레코드 id (삭제/수정용). 미예약 점유는 null */
  reservation_id?: string | null;
  service_id: string | null;
  service_name?: string | null;
  component?: string | null;
  protocol: Protocol | string;
  host_port: number;
  bind_addr: string;
  container_port?: number | null;
  exposure?: Exposure | string;
  state: PortState | string;
  occupied?: boolean;
  occupied_by?: string | null;
  hostname?: string | null;
  proxy_connected?: boolean;
  last_checked_at?: string | null;
}

export interface AvailablePortsQuery {
  count?: number;
  range?: string;
  protocol?: Protocol;
}

export interface AvailablePortsResult {
  ports: number[];
  count?: number;
  range?: string;
  protocol?: string;
}

export interface ReservationPayload {
  service_id: string;
  component: string;
  host_port: number;
  protocol: Protocol;
  bind_addr: string;
  container_port?: number | null;
  exposure: Exposure;
}

/* --------------------------- 자원 -------------------------------- */

export interface ResourceSample {
  ts: string;
  cpu_percent?: number | null;
  mem_used_mb?: number | null;
  mem_limit_mb?: number | null;
  net_rx_bytes?: number | null;
  net_tx_bytes?: number | null;
  disk_used_gb?: number | null;
}

export interface HostResources {
  cpu: {
    percent: number | null;
    cores: number | null;
    per_core?: number[] | null;
    load_avg?: number[] | null;
  };
  memory: {
    total_mb: number | null;
    used_mb: number | null;
    available_mb: number | null;
    cached_mb?: number | null;
    percent?: number | null;
    swap_total_mb?: number | null;
    swap_used_mb?: number | null;
  };
  disk: {
    total_gb: number | null;
    used_gb: number | null;
    percent?: number | null;
    filesystems?: Array<{
      mount: string;
      total_gb: number | null;
      used_gb: number | null;
      percent: number | null;
    }>;
    docker_data_gb?: number | null;
  };
  network?: {
    interfaces?: Array<{
      name: string;
      rx_bps?: number | null;
      tx_bps?: number | null;
      rx_total_bytes?: number | null;
      tx_total_bytes?: number | null;
      errors?: number | null;
    }>;
  };
  system?: {
    hostname?: string;
    os?: string;
    kernel?: string;
    booted_at?: string | null;
    uptime_seconds?: number | null;
    cpu_temp_c?: number | null;
  };
  samples?: ResourceSample[];
  collected_at?: string | null;
}

export interface ContainerResourceRow {
  container_id: string;
  name: string;
  service_id: string | null;
  service_name?: string | null;
  state: string;
  health?: string | null;
  cpu_percent: number | null;
  mem_used_mb: number | null;
  mem_limit_mb: number | null;
  net_rx_bytes?: number | null;
  net_tx_bytes?: number | null;
  restart_count?: number;
}

export interface ServiceResourceRow {
  service_id: string;
  name: string;
  status: ServiceStatus | string;
  cpu_percent: number | null;
  memory_mb: number | null;
  containers_total: number;
  containers_running: number;
  restart_count?: number;
}

export interface ResourceWarning {
  level: "warning" | "critical" | string;
  scope: "cpu" | "memory" | "disk" | "network" | string;
  message: string;
  value?: number | null;
  threshold?: number | null;
}

/* --------------------------- 배포 -------------------------------- */

export interface DeploymentStep {
  seq: number;
  name: string;
  status: string;
  detail?: string | null;
  at?: string | null;
}

export interface Deployment {
  id: string;
  service_id: string;
  status: DeploymentStatus | string;
  requested_by: string;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
  plan?: unknown;
  steps?: DeploymentStep[];
}

export interface DeploymentListQuery {
  service_id?: string;
  limit?: number;
}

/** 배포 계획 (REQUIREMENTS §13.2) — 읽기 전용 산출물 */
export interface DeployPlanChange {
  name: string;
  action: string;
  detail?: string;
}

export interface DeployPlanValidation {
  check: string;
  result: string;
  detail?: unknown;
}

export interface DeployPlan {
  service: string;
  result: "READY" | "BLOCKED";
  changes: DeployPlanChange[];
  ports: { name: string; host_port: number | null; container_port: number; exposure?: string }[];
  data?: { name: string; purpose: string }[];
  validation: DeployPlanValidation[];
  impact: { message: string }[];
  warnings?: { level: string; message: string }[];
  runtime_unchanged: boolean;
  note?: string;
}

export interface DeployApplyResult {
  deployment_id: string;
  service_id: string;
  status: string;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
}

/* --------------------------- 이벤트 ------------------------------- */

export interface HubEvent {
  id: string;
  ts: string;
  severity: Severity | string;
  kind: string;
  service_id: string | null;
  container_id: string | null;
  message: string;
  detail?: unknown;
}

export interface EventQuery {
  severity?: string;
  service_id?: string;
  limit?: number;
}

export interface AuditLog {
  id: string;
  ts: string;
  actor: string;
  action: string;
  target: string;
  detail?: unknown;
}

/* --------------------------- 로그 -------------------------------- */

export interface LogLine {
  ts?: string | null;
  stream?: string | null;
  message: string;
}

export interface ServiceLogs {
  lines: LogLine[];
}

/* --------------------------- 검색 -------------------------------- */

export interface SearchItem {
  id: string;
  label: string;
  detail?: string;
  route?: string;
  kind: "service" | "container" | "port" | "domain" | "image";
}

export interface SearchGroup {
  key: string;
  title: string;
  items: SearchItem[];
}

export interface SearchResults {
  query: string;
  groups: SearchGroup[];
  total: number;
}

/* --------------------------- 인증 -------------------------------- */

export interface SessionUser {
  username: string;
  role: string;
}

export interface SessionInfo {
  authenticated: boolean;
  setup_required: boolean;
  user: SessionUser | null;
  csrf_token: string | null;
  expires_at?: string | null;
}

export interface LoginPayload {
  username: string;
  password: string;
}

export interface SetupPayload {
  username: string;
  password: string;
}

/* ------------------------------------------------------------------ */
/* 요청 실행                                                           */
/* ------------------------------------------------------------------ */

export interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  query?: Record<string, string | number | boolean | null | undefined>;
  body?: unknown;
  signal?: AbortSignal;
  /** csrf_token을 받은 적이 없으면 요청 전에 세션을 다시 조회한다 (기본 true) */
  refreshCsrf?: boolean;
}

function isMockMode(): boolean {
  try {
    return import.meta.env?.VITE_API_MOCK === "true";
  } catch {
    return false;
  }
}

function buildQuery(query?: RequestOptions["query"]): string {
  if (!query) return "";
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v === undefined || v === null || v === "") continue;
    params.set(k, String(v));
  }
  const s = params.toString();
  return s ? `?${s}` : "";
}

function newRequestId(): string {
  try {
    if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
      return crypto.randomUUID();
    }
  } catch {
    /* noop */
  }
  return `req-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

function parseBody(text: string): unknown {
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

const MUTATING = new Set(["POST", "PUT", "PATCH", "DELETE"]);

/**
 * 백엔드는 목록형 응답을 `{"items": [...]}` 봉투로 감싸는 경우가 많고
 * (일부는 `{"warnings": [...]}`), 개발용 mock 은 맨 배열을 돌려준다.
 * 두 형태를 모두 허용해 항상 배열로 정규화한다.
 *
 * 이 정규화가 없으면 실제 백엔드 응답에서 `items.slice is not a function`
 * 처럼 렌더가 깨진다 (mock 테스트로는 드러나지 않는다).
 */
function unwrapList<T>(raw: unknown, keys: string[] = ["items"]): T[] {
  if (Array.isArray(raw)) return raw as T[];
  if (raw && typeof raw === "object") {
    for (const k of keys) {
      const v = (raw as Record<string, unknown>)[k];
      if (Array.isArray(v)) return v as T[];
    }
  }
  return [];
}

async function refreshCsrfFromSession(): Promise<void> {
  try {
    const res = await fetch(`${API_PREFIX}/auth/session`, {
      headers: { Accept: "application/json" },
    });
    if (res.ok) {
      const data = (await res.json()) as Partial<SessionInfo>;
      if (data && typeof data.csrf_token === "string") {
        csrfToken = data.csrf_token;
      }
    }
  } catch {
    /* 세션 조회 실패는 원래 요청의 오류 처리로 넘긴다 */
  }
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const method = options.method ?? "GET";
  const url = `${API_PREFIX}${path}${buildQuery(options.query)}`;
  const mutating = MUTATING.has(method);

  if (mutating && !csrfToken && options.refreshCsrf !== false) {
    await refreshCsrfFromSession();
  }

  const headers: Record<string, string> = {
    Accept: "application/json",
    "X-Request-Id": newRequestId(),
  };
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  if (mutating && csrfToken) headers["X-CSRF-Token"] = csrfToken;

  const init: RequestInit = {
    method,
    headers,
    credentials: "same-origin",
    signal: options.signal,
  };
  if (options.body !== undefined) init.body = JSON.stringify(options.body);

  let status: number;
  let payload: unknown;

  if (isMockMode()) {
    const res = await mockRequest(path + buildQuery(options.query), init);
    status = res.status;
    payload = res.body;
  } else {
    let res: Response;
    try {
      res = await fetch(url, init);
    } catch (e) {
      if ((e as Error)?.name === "AbortError") throw e;
      throw new ApiError(
        "백엔드 서버에 연결할 수 없습니다 (127.0.0.1:8420).",
        0,
        "network_error",
      );
    }
    status = res.status;
    const text = await res.text();
    payload = parseBody(text);
    // 204 등 빈 본문
    if (payload === "" || payload === undefined) payload = null;
  }

  if (status >= 400) {
    let detail = `요청 실패 (HTTP ${status})`;
    let code: string | null = null;
    if (payload && typeof payload === "object") {
      const p = payload as { detail?: unknown; code?: unknown };
      if (typeof p.detail === "string" && p.detail) detail = p.detail;
      else if (Array.isArray(p.detail) && p.detail.length > 0) {
        // FastAPI 검증 오류(detail 배열)를 읽을 수 있는 문장으로 만든다.
        const parts = (p.detail as unknown[]).slice(0, 5).map((item) => {
          if (item && typeof item === "object") {
            const e = item as { loc?: unknown; msg?: unknown };
            const loc = Array.isArray(e.loc)
              ? e.loc.filter((x) => x !== "body").map(String).join(".")
              : "";
            const msg = typeof e.msg === "string" ? e.msg : String(e.msg ?? "");
            return loc ? `${loc}: ${msg}` : msg;
          }
          return String(item);
        });
        detail = `입력값이 올바르지 않습니다 — ${parts.filter(Boolean).join("; ")}`;
      }
      if (typeof p.code === "string") code = p.code;
    } else if (typeof payload === "string" && payload) {
      detail = payload;
    }
    const err = new ApiError(detail, status, code, payload);
    if (status === 401 || status === 403) {
      for (const fn of unauthorizedListeners) fn();
    }
    throw err;
  }

  return payload as T;
}

function get<T>(path: string, query?: RequestOptions["query"], signal?: AbortSignal) {
  return request<T>(path, { method: "GET", query, signal });
}

function send<T>(
  path: string,
  method: "POST" | "PUT" | "PATCH" | "DELETE",
  body?: unknown,
  query?: RequestOptions["query"],
) {
  return request<T>(path, { method, body, query });
}

/* ------------------------------------------------------------------ */
/* 인증 / 초기 설정                                                    */
/* ------------------------------------------------------------------ */

export async function fetchSession(signal?: AbortSignal): Promise<SessionInfo> {
  const data = await get<Partial<SessionInfo>>("/auth/session", undefined, signal);
  const session: SessionInfo = {
    authenticated: data?.authenticated ?? false,
    setup_required: data?.setup_required ?? false,
    user: data?.user ?? null,
    csrf_token: data?.csrf_token ?? null,
    expires_at: data?.expires_at ?? null,
  };
  if (session.csrf_token) setCsrfToken(session.csrf_token);
  return session;
}

export async function login(payload: LoginPayload): Promise<SessionInfo> {
  const data = await send<Partial<SessionInfo>>("/auth/login", "POST", payload);
  const session: SessionInfo = {
    authenticated: data?.authenticated ?? true,
    setup_required: data?.setup_required ?? false,
    user: data?.user ?? { username: payload.username, role: "admin" },
    csrf_token: data?.csrf_token ?? null,
  };
  if (session.csrf_token) setCsrfToken(session.csrf_token);
  else setCsrfToken(null);
  return session;
}

export async function logout(): Promise<void> {
  try {
    await send<unknown>("/auth/logout", "POST", undefined, undefined);
  } finally {
    setCsrfToken(null);
  }
}

/** 최초 1회 관리자 생성 */
export async function setupAdmin(payload: SetupPayload): Promise<SessionInfo | null> {
  const data = await send<Partial<SessionInfo> | null>("/setup/admin", "POST", payload);
  if (data && typeof data === "object") {
    const session: SessionInfo = {
      authenticated: data.authenticated ?? true,
      setup_required: data.setup_required ?? false,
      user: data.user ?? { username: payload.username, role: "admin" },
      csrf_token: data.csrf_token ?? null,
    };
    if (session.csrf_token) setCsrfToken(session.csrf_token);
    return session;
  }
  return null;
}

export interface ChangePasswordPayload {
  current_password: string;
  new_password: string;
}

/** 관리자 비밀번호 변경 — 현 비밀번호 확인 후 변경 (인증 + CSRF 필요). */
export function changePassword(payload: ChangePasswordPayload): Promise<{ ok: boolean }> {
  return send<{ ok: boolean }>("/auth/change-password", "POST", payload);
}

/* ------------------------------------------------------------------ */
/* 시스템                                                              */
/* ------------------------------------------------------------------ */

export function fetchOverview(signal?: AbortSignal): Promise<SystemOverview> {
  return get<SystemOverview>("/system/overview", undefined, signal);
}

export function fetchStatus(signal?: AbortSignal): Promise<SystemStatus> {
  return get<SystemStatus>("/system/status", undefined, signal);
}

export function fetchSettings(signal?: AbortSignal): Promise<HubSettings> {
  return get<HubSettings>("/system/settings", undefined, signal);
}

export function updateSettings(body: HubSettings): Promise<HubSettings> {
  return send<HubSettings>("/system/settings", "PUT", body);
}

/* ------------------------------------------------------------------ */
/* API 키 (MCP/AI 클라이언트)                                          */
/* ------------------------------------------------------------------ */

export interface ApiKeyInfo {
  id: string;
  name: string;
  username: string;
  scopes: string[];
  created_at: string;
  created_by: string;
  last_used_at: string | null;
  expires_at: string | null;
  revoked_at: string | null;
  active: boolean;
}

export interface ApiKeyCreated extends ApiKeyInfo {
  key: string;
  note?: string;
}

export interface ApiKeyCreatePayload {
  name: string;
  scopes?: string[];
  expires_in_days?: number | null;
}

export function fetchApiKeys(signal?: AbortSignal): Promise<ApiKeyInfo[]> {
  return get<unknown>("/apikeys", undefined, signal).then((r) => unwrapList<ApiKeyInfo>(r));
}

export function createApiKey(body: ApiKeyCreatePayload): Promise<ApiKeyCreated> {
  return send<ApiKeyCreated>("/apikeys", "POST", body);
}

export function revokeApiKey(id: string): Promise<ApiKeyInfo & { revoked: boolean }> {
  return send<ApiKeyInfo & { revoked: boolean }>(
    `/apikeys/${encodeURIComponent(id)}`,
    "DELETE",
  );
}

/* ------------------------------------------------------------------ */
/* 서비스                                                              */
/* ------------------------------------------------------------------ */

export interface SpecGuideField {
  path: string;
  required: boolean;
  type: string;
  description: string;
  allowed: string | null;
}

export interface SpecGuide {
  schema_version: number;
  file_location: string;
  create_command: string;
  validate_command: string;
  plan_command: string;
  apply_command: string;
  minimal_example: string;
  full_example: string;
  fields: SpecGuideField[];
  rules: string[];
  enums: Record<string, string[]>;
  docs: string;
}

/** service.yaml 작성 안내 — UI와 문서가 같은 내용을 쓴다. */
export function fetchSpecGuide(signal?: AbortSignal): Promise<SpecGuide> {
  return get<SpecGuide>("/services/spec/guide", undefined, signal);
}

export function fetchServices(
  query?: ServiceListQuery,
  signal?: AbortSignal,
): Promise<ServiceListItem[]> {
  return get<unknown>("/services", { ...query }, signal).then((r) =>
    unwrapList<ServiceListItem>(r),
  );
}

export function createService(body: ServiceCreatePayload): Promise<ServiceListItem> {
  return send<ServiceListItem>("/services", "POST", body);
}

export function fetchService(id: string, signal?: AbortSignal): Promise<ServiceDetail> {
  return get<ServiceDetail>(`/services/${encodeURIComponent(id)}`, undefined, signal);
}

export function updateService(
  id: string,
  body: ServiceUpdatePayload,
): Promise<ServiceDetail> {
  return send<ServiceDetail>(`/services/${encodeURIComponent(id)}`, "PATCH", body);
}

export function deleteService(id: string): Promise<DeleteResult> {
  return send<DeleteResult>(`/services/${encodeURIComponent(id)}`, "DELETE", undefined, {
    confirm: id,
  });
}

export function fetchServiceContainers(
  id: string,
  signal?: AbortSignal,
): Promise<ContainerListItem[]> {
  return get<unknown>(`/services/${encodeURIComponent(id)}/containers`, undefined, signal)
    .then((r) => unwrapList<Record<string, unknown>>(r))
    .then((rows) => rows.map(normalizeContainer));
}

export function fetchServiceEndpoints(
  id: string,
  signal?: AbortSignal,
): Promise<ServiceEndpoint[]> {
  return get<unknown>(`/services/${encodeURIComponent(id)}/endpoints`, undefined, signal).then(
    (r) => unwrapList<ServiceEndpoint>(r),
  );
}

export function fetchServiceLogs(
  id: string,
  tail = 200,
  signal?: AbortSignal,
): Promise<ServiceLogs> {
  return get<ServiceLogs>(`/services/${encodeURIComponent(id)}/logs`, { tail }, signal);
}

export function fetchServiceEvents(
  id: string,
  limit = 100,
  signal?: AbortSignal,
): Promise<HubEvent[]> {
  return get<unknown>(`/services/${encodeURIComponent(id)}/events`, { limit }, signal).then((r) =>
    unwrapList<HubEvent>(r),
  );
}

/* ------------------------------------------------------------------ */
/* 컨테이너                                                            */
/* ------------------------------------------------------------------ */

export function fetchContainers(
  query?: ContainerQuery,
  signal?: AbortSignal,
): Promise<ContainerListItem[]> {
  return get<unknown>("/containers", { ...query }, signal)
    .then((r) => unwrapList<Record<string, unknown>>(r))
    .then((rows) => rows.map(normalizeContainer));
}

export function fetchContainer(id: string, signal?: AbortSignal): Promise<ContainerDetail> {
  return get<Record<string, unknown>>(
    `/containers/${encodeURIComponent(id)}`,
    undefined,
    signal,
  ).then((r) => normalizeContainer(r) as unknown as ContainerDetail);
}

/* ------------------------------------------------------------------ */
/* 미관리(오렌) 컨테이너                                                */
/* ------------------------------------------------------------------ */

export function fetchOrphans(signal?: AbortSignal): Promise<OrphanItem[]> {
  return get<unknown>("/orphans", undefined, signal).then((r) => unwrapList<OrphanItem>(r));
}

export function attachOrphan(cid: string, body: AttachPayload): Promise<unknown> {
  return send<unknown>(`/orphans/${encodeURIComponent(cid)}/attach`, "POST", body);
}

export interface BulkAttachPayload {
  service_id: string;
  container_ids: string[];
  /** 지정하면 선택한 컨테이너를 이 컴포넌트 하나로 묶는다. */
  component_name?: string | null;
}

export interface AttachResultRow {
  container_id: string;
  name?: string;
  ok: boolean;
  reason?: string;
  service_id?: string;
  component?: string;
}

export interface BulkAttachResult {
  service_id: string;
  attached: number;
  skipped: number;
  results: AttachResultRow[];
  runtime_unchanged?: boolean;
  note?: string;
}

/**
 * 여러 미관리 컨테이너를 한 서비스로 **수동 그룹핑**한다.
 * DB 연결만 수행하며 컨테이너 런타임은 변경하지 않는다.
 */
export function attachOrphans(payload: BulkAttachPayload): Promise<BulkAttachResult> {
  return send<BulkAttachResult>("/orphans/attach", "POST", payload);
}

/** 수동 그룹핑 해제 (DB 연결만 제거, 컨테이너는 그대로). */
export function detachContainer(
  containerId: string,
): Promise<{ detached: boolean; previous_service?: string | null; note?: string }> {
  return send(`/containers/${encodeURIComponent(containerId)}/detach`, "POST", undefined);
}

/** compose 프로젝트 단위로 컨테이너를 한 번에 그룹핑한다. */
export function autoAttachService(
  serviceId: string,
  composeProject?: string | null,
): Promise<BulkAttachResult & { compose_project: string }> {
  return send(`/services/${encodeURIComponent(serviceId)}/auto-attach`, "POST", {
    compose_project: composeProject ?? null,
  });
}

export function reviewOrphan(cid: string, body: ReviewPayload): Promise<unknown> {
  return send<unknown>(`/orphans/${encodeURIComponent(cid)}/review`, "POST", body);
}

/* ------------------------------------------------------------------ */
/* 포트                                                                */
/* ------------------------------------------------------------------ */

export function fetchPorts(signal?: AbortSignal): Promise<PortEntry[]> {
  return get<unknown>("/ports", undefined, signal).then((r) => unwrapList<PortEntry>(r));
}

export async function fetchAvailablePorts(
  query: AvailablePortsQuery = {},
  signal?: AbortSignal,
): Promise<AvailablePortsResult> {
  const raw = await get<Partial<AvailablePortsResult> & { available?: number[]; candidates?: number[] }>(
    "/ports/available",
    {
      count: query.count ?? 5,
      range: query.range,
      protocol: query.protocol ?? "tcp",
    },
    signal,
  );
  const list = raw?.ports ?? raw?.available ?? raw?.candidates ?? [];
  return {
    ports: Array.isArray(list) ? list.map(Number).filter((n) => Number.isFinite(n)) : [],
    count: raw?.count,
    range: raw?.range,
    protocol: raw?.protocol ?? query.protocol ?? "tcp",
  };
}

export function createReservation(body: ReservationPayload): Promise<PortEntry> {
  return send<PortEntry>("/ports/reservations", "POST", body);
}

export function deleteReservation(id: string): Promise<unknown> {
  return send<unknown>(`/ports/reservations/${encodeURIComponent(id)}`, "DELETE");
}

/* ------------------------------------------------------------------ */
/* 자원                                                                */
/* ------------------------------------------------------------------ */

export function fetchHostResources(signal?: AbortSignal): Promise<HostResources> {
  return get<HostResources>("/resources/host", undefined, signal);
}

export function fetchContainerResources(
  signal?: AbortSignal,
): Promise<ContainerResourceRow[]> {
  return get<unknown>("/resources/containers", undefined, signal).then((r) =>
    unwrapList<ContainerResourceRow>(r),
  );
}

export function fetchServiceResources(signal?: AbortSignal): Promise<ServiceResourceRow[]> {
  return get<unknown>("/resources/services", undefined, signal).then((r) =>
    unwrapList<ServiceResourceRow>(r),
  );
}

export function fetchResourceWarnings(signal?: AbortSignal): Promise<ResourceWarning[]> {
  // 백엔드는 {"warnings": [...], "thresholds": {...}} 형태로 돌려준다.
  return get<unknown>("/resources/warnings", undefined, signal).then((r) =>
    unwrapList<ResourceWarning>(r, ["warnings", "items"]),
  );
}

/* ------------------------------------------------------------------ */
/* 배포 (Phase 3 — 계획 조회 + 승인 실행)                               */
/* ------------------------------------------------------------------ */

/** 배포 시점 스냅샷으로 되돌려 재배포한다 (성공한 배포만 가능). */
export function rollbackDeployment(
  deploymentId: string,
): Promise<{
  deployment_id: string;
  service_id: string;
  status: string;
  error: string | null;
  rollback_of: string;
  restored_files: string[];
}> {
  return send(`/deployments/${encodeURIComponent(deploymentId)}/rollback`, "POST", {
    confirmed: true,
  });
}

export function fetchDeployments(
  query?: DeploymentListQuery,
  signal?: AbortSignal,
): Promise<Deployment[]> {
  return get<unknown>("/deployments", { ...query }, signal)
    .then((r) => unwrapList<Deployment>(r))
    .then((rows) => rows.map(normalizeDeployment));
}

export function fetchDeployment(id: string, signal?: AbortSignal): Promise<Deployment> {
  return get<Deployment>(`/deployments/${encodeURIComponent(id)}`, undefined, signal)
    .then(normalizeDeployment);
}

/** 백엔드는 `deployment_id`, UI는 `id`를 쓴다 — 한 곳에서 정규화한다. */
function normalizeDeployment(d: Deployment): Deployment {
  const raw = d as Deployment & { deployment_id?: string };
  return { ...d, id: d.id ?? raw.deployment_id ?? "" };
}

/**
 * 백엔드 컨테이너 응답 → 프런트엔드 `ContainerListItem`.
 *
 * 백엔드는 `container_id` / `status_text` / `component` / `ports[].proto`·
 * `bind_addr` 로 내려주는데, 프런트 타입은 `id` / `status` / `component_name` /
 * `ports[].protocol`·`host_ip` 를 쓴다. 이름이 다르면 `c.id.slice()` 같은 코드가
 * `undefined` 로 깨지므로 여기서 한 번에 맞춰준다.
 */
function normalizeContainer(c: Record<string, unknown>): ContainerListItem {
  const portsRaw = Array.isArray(c.ports) ? (c.ports as Record<string, unknown>[]) : [];
  const networksRaw = Array.isArray(c.networks) ? (c.networks as NetworkRef[]) : [];
  const ports: PortMapping[] = portsRaw.map((p) => ({
    host_ip: (p.bind_addr as string | null) ?? (p.host_ip as string | null) ?? null,
    host_port: (p.host_port as number | null) ?? null,
    container_port: (p.container_port as number) ?? 0,
    protocol: (p.protocol as string) ?? (p.proto as string) ?? "tcp",
  }));
  return {
    ...(c as unknown as ContainerListItem),
    id: (c.id as string) ?? (c.container_id as string) ?? "",
    status: (c.status as string) ?? (c.status_text as string) ?? (c.state as string) ?? "",
    component_name: (c.component_name as string | null) ?? (c.component as string | null) ?? null,
    ports,
    networks: networksRaw,
    started_at: (c.started_at as string | null) ?? null,
    created_at: (c.created_at as string | null) ?? null,
  };
}

/** 배포 계획 생성 — 컨테이너를 변경하지 않는다 (읽기 전용). */
export function getDeployPlan(spec: unknown, signal?: AbortSignal): Promise<DeployPlan> {
  return request<DeployPlan>("/deployments/plan", {
    method: "POST",
    body: { service_definition: spec },
    signal,
  });
}

/**
 * 배포 실행 — 서버가 `HUB_ENABLE_DEPLOY=true` 로 열려 있을 때만 동작한다.
 * 잠겨 있으면 `deploy_disabled`(503) 오류가 발생한다.
 */
export function applyDeploy(spec: unknown): Promise<DeployApplyResult> {
  return send<DeployApplyResult>("/deployments", "POST", { spec, confirmed: true });
}

export function fetchDeploymentLogs(
  id: string,
  signal?: AbortSignal,
): Promise<ServiceLogs> {
  return get<ServiceLogs>(`/deployments/${encodeURIComponent(id)}/logs`, undefined, signal);
}

/* ------------------------------------------------------------------ */
/* 이벤트 / 감사 / 검색                                                 */
/* ------------------------------------------------------------------ */

export function fetchEvents(query?: EventQuery, signal?: AbortSignal): Promise<HubEvent[]> {
  return get<unknown>("/events", { ...query }, signal).then((r) => unwrapList<HubEvent>(r));
}

export function fetchAuditLogs(limit = 100, signal?: AbortSignal): Promise<AuditLog[]> {
  return get<unknown>("/audit-logs", { limit }, signal).then((r) => unwrapList<AuditLog>(r));
}

/** 원시 검색 응답 → 그룹화 결과 (문자열/�터 모두 허용) */
type RawSearchEntry = Record<string, unknown> | string;

interface RawSearchPayload {
  services?: RawSearchEntry[];
  containers?: RawSearchEntry[];
  ports?: RawSearchEntry[];
  domains?: RawSearchEntry[];
  images?: RawSearchEntry[];
  results?: RawSearchEntry[];
}

function entryLabel(e: RawSearchEntry): string {
  return typeof e === "string" ? e : String(e.name ?? e.label ?? e.id ?? e.value ?? "");
}

function entryDetail(e: RawSearchEntry): string | undefined {
  if (typeof e === "string") return undefined;
  const parts = [
    e.description,
    e.image,
    e.state,
    e.service_id,
    e.hostname,
    e.protocol,
    e.exposure,
  ].filter((x): x is string => typeof x === "string" && x.length > 0);
  return parts.length ? parts.slice(0, 2).join(" · ") : undefined;
}

function entryRoute(e: RawSearchEntry, kind: SearchItem["kind"]): string | undefined {
  if (typeof e === "string") return undefined;
  const sid = typeof e.service_id === "string" ? e.service_id : null;
  const cid = typeof e.id === "string" ? e.id : null;
  switch (kind) {
    case "service":
      return sid ? `/services/${sid}` : cid ? `/services/${cid}` : "/services";
    case "container":
      return `/containers?focus=${encodeURIComponent(cid ?? "")}`;
    case "port":
      return "/ports";
    case "domain":
      return sid ? `/services/${sid}` : "/ports";
    case "image":
      return "/containers";
  }
}

function toItems(list: RawSearchEntry[] | undefined, kind: SearchItem["kind"]): SearchItem[] {
  if (!Array.isArray(list)) return [];
  return list.slice(0, 8).map((e, i) => ({
    id: `${kind}-${i}-${entryLabel(e)}`,
    label: entryLabel(e),
    detail: entryDetail(e),
    route: entryRoute(e, kind),
    kind,
  }));
}

export async function search(q: string, signal?: AbortSignal): Promise<SearchResults> {
  const raw = await get<RawSearchPayload>("/search", { q }, signal);
  const groups: SearchGroup[] = [
    { key: "services", title: "서비스", items: toItems(raw?.services, "service") },
    { key: "containers", title: "컨테이너", items: toItems(raw?.containers, "container") },
    { key: "ports", title: "포트", items: toItems(raw?.ports, "port") },
    { key: "domains", title: "도메인", items: toItems(raw?.domains, "domain") },
    { key: "images", title: "이미지", items: toItems(raw?.images, "image") },
  ].filter((g) => g.items.length > 0);
  const total = groups.reduce((n, g) => n + g.items.length, 0);
  return { query: q, groups, total };
}
