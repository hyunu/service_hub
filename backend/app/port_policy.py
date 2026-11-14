"""N100 서비스 호스트 포트 정책.

공유기(라우터)가 **50000번대를 N100으로 포워딩**하도록 설정되어 있으므로,
호스트에 직접 게시하는 서비스는 이 대역의 **미할당 포트**만 사용한다.
프록시(`exposure: proxy`)와 내부(`internal`) 엔드포인트는 영향받지 않는다.

이 값은 배포 환경의 물리적 제약이므로 설정으로 바꾸지 않는다.
"""
from __future__ import annotations

HOST_PORT_MIN = 50000
HOST_PORT_MAX = 59999


def range_label() -> str:
    return f"{HOST_PORT_MIN}-{HOST_PORT_MAX}"


def is_allowed_host_port(port: int | None) -> bool:
    return port is not None and HOST_PORT_MIN <= port <= HOST_PORT_MAX
