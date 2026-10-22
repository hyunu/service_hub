"""service.yaml 작성 안내(UI/문서 공용) 테스트.

문서와 코드가 어긋나면 사용자가 잘못된 예시를 복사하게 된다.
안내에 실린 예시가 실제 스키마 검증을 통과하는지 고정한다.
"""
from __future__ import annotations

import yaml

from app.services.service_spec import validate_spec_dict


def test_spec_guide_examples_are_valid(client):
    body = client.get("/api/v1/services/spec/guide").json()
    assert body["schema_version"] == 1
    assert body["fields"] and body["rules"]
    assert body["file_location"].startswith("/srv/services/")
    # 필수 예시/전체 예시 모두 실제 검증을 통과해야 한다
    for key in ("minimal_example", "full_example"):
        spec = validate_spec_dict(yaml.safe_load(body[key]))
        assert spec.service.id == "my-app"
    # 시크릿 값 금지 안내가 포함되어야 한다
    assert any("시크릿" in r for r in body["rules"])


def test_spec_guide_is_not_shadowed_by_service_id_route(client):
    """`/services/spec/guide`가 `/{service_id}` 라우트에 가려지지 않는다."""
    r = client.get("/api/v1/services/spec/guide")
    assert r.status_code == 200, r.text
    assert "fields" in r.json()


def test_spec_guide_enums_match_backend(client):
    from app.services.spec_guide import CATEGORIES, CONTAINER_ROLES, EXPOSURES

    body = client.get("/api/v1/services/spec/guide").json()
    assert body["enums"]["category"] == CATEGORIES
    assert body["enums"]["container_role"] == CONTAINER_ROLES
    assert body["enums"]["exposure"] == EXPOSURES
