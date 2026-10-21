# Sample Application

## 목적
(서비스의 목적과 주요 기능을 기록하세요)

## 사용자
(누가 사용하는지)

## 외부 접속 방법
- Traefik 프록시: http://sample.home (내부 DNS/hosts 설정 필요 — 자동으로 동작하지 않습니다)

## 컨테이너 구성
| 컨테이너 | 역할 | 필수 |
|---|---|---|
| frontend | 웹 프런트엔드 | 예 |
| backend | API | 예 |

## 데이터 저장 위치
- 볼륨 `sample-app-data` → 애플리케이션 영속 데이터

## 백업 방법
(백업 주기, 대상, 복구 절차)

## 운영상 주의사항
- (의존성, 업데이트 시 주의점, 포트 충돌 등)

## 개발 및 수정 방법
- compose.yaml 변경 후 `hub service validate .`로 검증
- 배포는 `hub deploy plan .` → 승인 → `hub deploy apply <service-id>`
