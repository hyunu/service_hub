"""Service Hub REST API 클라이언트 (MCP 서버 전용).

기존 백엔드 API만 호출한다 — 임의 셸 실행 경로는 없다.
"""
from __future__ import annotations

import os
from typing import Any

import httpx

DEFAULT_URL = "http://127.0.0.1:8420/api/v1"


class HubApiError(Exception):
    """백엔드가 오류를 반환했거나 연결할 수 없을 때."""

    def __init__(self, message: str, status: int = 0, code: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code


def normalize_base(url: str) -> str:
    """`HUB_URL`을 `/api/v1`까지 포함한 형태로 정규화한다."""
    base = (url or DEFAULT_URL).rstrip("/")
    if not base.endswith("/api/v1"):
        base = f"{base}/api/v1"
    return base


class HubClient:
    def __init__(self, base_url: str | None = None, api_key: str | None = None,
                 timeout: float = 60.0) -> None:
        self.base_url = normalize_base(base_url or os.environ.get("HUB_URL", DEFAULT_URL))
        self.api_key = api_key if api_key is not None else os.environ.get("HUB_API_KEY")
        self.timeout = timeout

    # ---------------------------------------------------------------- core --

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        return headers

    def request(self, method: str, path: str, json: Any | None = None,
                params: dict[str, Any] | None = None,
                timeout: float | None = None) -> Any:
        url = f"{self.base_url}{path}"
        try:
            resp = httpx.request(method, url, json=json, params=params,
                                 headers=self._headers(),
                                 timeout=timeout or self.timeout)
        except httpx.HTTPError as exc:
            raise HubApiError(
                f"Service Hub에 연결할 수 없습니다: {url} ({exc}). "
                f"HUB_URL 과 백엔드 실행 상태를 확인하세요.",
                status=0, code="unreachable") from exc

        if resp.status_code >= 400:
            detail, code = _error_body(resp)
            raise HubApiError(detail, status=resp.status_code, code=code)
        if not resp.content:
            return None
        try:
            return resp.json()
        except ValueError:
            return resp.text

    # ------------------------------------------------------------- shortcuts --

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return self.request("GET", path, params=params)

    def post(self, path: str, payload: Any, timeout: float | None = None) -> Any:
        return self.request("POST", path, json=payload, timeout=timeout)

    def post_raw(self, path: str, body: bytes, content_type: str,
                 timeout: float | None = None) -> Any:
        """원시 본문 업로드 (tar.gz 등)."""
        url = f"{self.base_url}{path}"
        headers = {**self._headers(), "Content-Type": content_type}
        try:
            resp = httpx.request("POST", url, content=body, headers=headers,
                                 timeout=timeout or self.timeout)
        except httpx.HTTPError as exc:
            raise HubApiError(
                f"Service Hub에 연결할 수 없습니다: {url} ({exc}).",
                status=0, code="unreachable") from exc

        if resp.status_code >= 400:
            detail, code = _error_body(resp)
            raise HubApiError(detail, status=resp.status_code, code=code)
        if not resp.content:
            return None
        try:
            return resp.json()
        except ValueError:
            return resp.text

    def delete(self, path: str) -> Any:
        return self.request("DELETE", path)

    # --------------------------------------------------------------- domain --

    def validate_spec(self, spec: dict) -> dict:
        return self.post("/services/validate", spec)

    def create_service(self, payload: dict) -> dict:
        return self.post("/services", payload)


def _error_body(resp: httpx.Response) -> tuple[str, str | None]:
    """오류 응답에서 사람이 읽을 메시지와 code를 뽑는다."""
    try:
        body = resp.json()
    except ValueError:
        return f"HTTP {resp.status_code}: {resp.text[:300]}", None
    if isinstance(body, dict):
        detail = body.get("detail")
        code = body.get("code")
        if isinstance(detail, str) and detail:
            return detail, code if isinstance(code, str) else None
        if isinstance(detail, list) and detail:
            # FastAPI 검증 오류: 필드별 메시지를 합친다
            parts = []
            for item in detail[:8]:
                if isinstance(item, dict):
                    loc = ".".join(str(x) for x in (item.get("loc") or []))
                    parts.append(f"{loc}: {item.get('msg')}")
            if parts:
                return "요청 형식이 올바르지 않습니다 — " + "; ".join(parts), code
    return f"HTTP {resp.status_code}: {resp.text[:300]}", None
