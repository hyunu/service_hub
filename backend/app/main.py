"""FastAPI 앱 팩토리 — 라우터 등록, 라이프사이클(모니터 시작/중지)."""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import Settings, get_settings, set_settings
from .db import init_db
from .dependencies import get_gateway, set_gateway
from .docker_client import DockerGateway
from .monitor import Monitor
from .routers import auth as auth_router
from .routers import containers as containers_router
from .routers import events as events_router
from .routers import ports as ports_router
from .routers import resources as resources_router
from .routers import system as system_router
from .routers.services import router as services_router
from .security import HubError

API_PREFIX = "/api/v1"


def create_app(settings: Settings | None = None,
               gateway: DockerGateway | None = None) -> FastAPI:
    settings = settings or get_settings()
    set_settings(settings)
    monitor = Monitor(gateway or DockerGateway(socket_path=_socket_url(settings)),
                      settings=settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        init_db()
        set_gateway(monitor.gateway)
        if settings.monitor_enabled:
            monitor.start()
        app.state.monitor = monitor
        yield
        monitor.stop()

    app = FastAPI(title=settings.name, version="0.1.0", lifespan=lifespan)
    app.state.monitor = monitor

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_id(request: Request, call_next):
        rid = request.headers.get("X-Request-Id") or uuid.uuid4().hex[:12]
        response = await call_next(request)
        response.headers["X-Request-Id"] = rid
        return response

    @app.exception_handler(HubError)
    async def hub_error(request: Request, exc: HubError):
        # {"detail": ..., "code": ...} 형태로 기계 판독 가능한 오류를 반환한다.
        return JSONResponse(status_code=exc.status_code,
                            content={"detail": exc.detail, "code": exc.code},
                            headers=exc.headers)

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        # 내부 경로/소켓 정보를 오류 응답에 노출하지 않는다 (docs/SECURITY.md)
        return JSONResponse(status_code=500, content={
            "detail": "내부 오류가 발생했습니다. 서버 로그를 확인하세요.",
            "code": "internal_error"})

    p = API_PREFIX
    app.include_router(auth_router.router, prefix=f"{p}")
    app.include_router(system_router.router, prefix=f"{p}")
    app.include_router(services_router, prefix=f"{p}")
    app.include_router(containers_router.router, prefix=f"{p}")
    app.include_router(ports_router.router, prefix=f"{p}")
    app.include_router(resources_router.router, prefix=f"{p}")
    app.include_router(events_router.router, prefix=f"{p}")
    app.include_router(events_router.deploy_router, prefix=f"{p}")

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    return app


def _socket_url(settings: Settings) -> str:
    sock = settings.docker_socket
    return sock if sock.startswith("unix://") else f"unix://{sock}"


app = create_app()
