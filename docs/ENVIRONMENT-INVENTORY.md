# ENVIRONMENT-INVENTORY (Phase 0)

조사 시각: 2026-10-21 (개발 환경)
조사 원칙: **읽기 전용**. 어떤 컨테이너/네트워크/볼륨/포트도 변경하지 않았다.

## 1. 개발 환경 (현재 작업 위치)

| 항목 | 값 |
|---|---|
| OS | macOS 27.0 (Build 26A428), arm64 |
| CPU | 8 논리 코어 |
| RAM | 약 24 GiB |
| 디스크 | 1.8 TiB 볼륨, 사용 694 GiB / 가용 1.1 TiB |
| Python | 3.14.8 (/opt/homebrew/bin/python3), uv 사용 가능 |
| Node | v26.10.0, npm 11.19.1 |
| Docker Engine | 29.4.3 (Docker Desktop, linux/arm64 VM) |
| Docker Compose | v5.1.3 |

주의: 개발 환경은 macOS이고 **배포 대상 N100은 Linux**다. `/proc` 기반 자원 수집은 Linux 전용이므로, macOS에서는 `psutil` 폴백을 사용하고 Linux에서는 `/proc` 우선 경로를 사용한다. 해당 차이는 Resource Monitor에 플랫폼 분리로 구현한다(추정 아님 — 명확한 플랫폼 차이).

## 2. 개발 머신의 기존 Docker 환경 (읽기 전용 조사 결과)

변경 금지 대상으로 확인된 기존 구성. **이 구성은 수정/삭제/재시작하지 않는다.**

### Compose 프로젝트 (4개)
| 프로젝트 | 컨테이너 | 비고 |
|---|---|---|
| sentinel | sentinel-backend(:5050), sentinel-dashboard(:5173), sentinel-mongodb(:27017) | 실행 중 |
| docker (assetnest) | assetnest-server(127.0.0.1:20001, healthy), assetnest-dashboard(127.0.0.1:80), assetnest-collector, assetnest-mongo(27017 미노출), assetnest-trade-api(:20101), assetnest-trade-rule-server | 실행 중 |
| sentinel-dashboard | 3개 (mongo 포함) | 3개월 전 중지 |
| exodus_website | wikijs, nextjs, minio, postgres | 중지 |
| nexio | web, server, mysql(:3306 공개) | 중지 |

실행 중 9 / 중지 10 / 전체 19. 네트워크: bridge, docker_default, exodus_website_exodus, infra_default, nexio_default, sentinel-dashboard_default, sentinel_default. 볼륨: 이름 있는 볼륨 약 15개 + 해시 이름 볼륨 약 27개.

### 인벤토리 관찰 사항 (설계에 반영)
1. `assetnest-mongo`, `assetnest-trade-rule-server`는 포트 매핑이 없다 (내부 전용) — Port Registry는 "호스트 포트 없음"을 정상 상태로 지원해야 한다.
2. `assetnest-dashboard`는 `127.0.0.1:80`으로 loopback 전용 바인딩 — 바인딩 주소 필드가 필수다.
3. `nexio-mysql`은 `0.0.0.0:3306` 외부 공개 — 정책 위반 감지(데이터베이스 외부 공개) 예시로 사용한다.
4. `sentinel-dashboard` 프로젝트와 `sentinel` 프로젝트가 유사 이름 — 프로젝트명이 아니라 compose project label + 서비스명으로 식별해야 한다.
5. 중지된 컨테이너도 포트 매핑 정보를 보유 — "예약됨 vs 실제 점유" 구분의 실사례.
6. 해시 이름 볼륨 다수 — orphan 볼륨 개념은 Phase 4 이후로 미룬다(현재 범위 밖).

## 3. 배포 대상 (N100 서버)

**현재 접근 불가.** 추정하지 않고 아래를 "확인 필요"로 기록한다.

| 항목 | 상태 |
|---|---|
| OS / 커널 | 확인 필요 (Ubuntu 계열 Linux 가정 — 설치 스크립트에서 검증하도록 설계) |
| Docker / Compose 버전 | 확인 필요 (install 스크립트가 사전 점검) |
| CPU 코어 수 / RAM | 확인 필요 (N100 = Intel N100, 4코어/16GB가 일반적이나 미검증) |
| 디스크 용량 | 확인 필요 |
| 기존 컨테이너/포트 | 확인 필요 (설치 스크립트가 최초 read-only 스캔 수행) |
| 기존 리버스 프록시 (Traefik 등) | 확인 필요 — **있다고 가정하지 않음.** Traefik은 서비스 허브 compose에 포함하되 기존 프록시와 충돌하는 포트(80/443)는 사전 점검 |
| 기존 MOTD 설정 | 확인 필요 — 설치 스크립트가 /etc/update-motd.d/ 및 /etc/motd 백업 후 조작 |
| 관리 포트 | 기본값 8420 (충돌 시 설치 스크립트가 경고, 변경 가능) |

## 4. 충돌/누락 식별

1. **macOS/Linux 차이** → 자원 수집에 플랫폼 분리 필요 (위 1항).
2. **Docker 데몬 미실행** → Docker 연결 실패 시 `unknown` 상태로 정상 표시하고 관리 UI는 살아있어야 함 (§8.2 요구와 일치). 백그라운드 모니터가 연결 오류를 격리 처리해야 한다.
3. **관리 시스템 자기 자신도 Docker 컨테이너** → 자기 자신 컨테이너를 "미관리"로 표시하지 않도록 compose label로 제외 처리 필요.
4. **포트 기본값** → 관리 UI 8420, Traefik 8080(내부), 80/443은 Traefik 노출 포트로 사용 가능. 기존 머신에 80이 이미 쓰이고 있어(127.0.0.1:80) install 스크립트가 충돌 검사를 수행해야 함.
5. **SQLite 동시성** → FastAPI(스레드) + 백그라운드 모니터 동시 쓰기 → WAL 모드 + 연결 풀 1connection + 락 정책으로 해결.
6. **요구사항 미명확 항목과 안전 기본값 결정 (문서화)**:
   - 인증: Phase 1에서는 read-only 기능 위주이므로 세션 쿠키 + 관리자 계정(최초 실행 시 설정 마법사에서 생성, 하드코딩 없음)을 Phase 4로 미루지 않고 간이 형태로 조기 적용. 초기 설정이 안 된 상태에서는 UI가 "설정 필요" 화면만 노출한다.
   - 서비스 삭제 API: 관리 정보(DB 레코드)만 삭제하며 컨테이너/볼륨은 건드리지 않는다 (요구사항 명시).
   - 자원 샘플 보존: raw 샘플은 7일, 5분 간격 롤업은 30일 보존.
