import pytest
from app.services.service_spec import SpecError, parse_spec, validate_spec_dict

VALID = {
    "schema_version": 1,
    "service": {"id": "sample-app", "name": "Sample", "description": "샘플", "category": "web"},
    "deployment": {"type": "docker-compose", "compose_file": "compose.yaml"},
}


def test_valid_spec_parses():
    spec = validate_spec_dict(VALID)
    assert spec.service.id == "sample-app"


def test_unknown_schema_version_rejected():
    bad = {**VALID, "schema_version": 2}
    with pytest.raises(SpecError) as e:
        validate_spec_dict(bad)
    assert e.value.code == "unsupported_schema_version"


def test_bad_service_id_rejected():
    bad = {**VALID, "service": {**VALID["service"], "id": "Bad_ID"}}
    with pytest.raises(SpecError) as e:
        validate_spec_dict(bad)
    assert e.value.code == "invalid_service_id"


def test_proxy_endpoint_requires_hostname():
    bad = {**VALID, "endpoints": [{"name": "f", "type": "http", "exposure": "proxy",
                                   "container": "frontend", "container_port": 3000}]}
    with pytest.raises(SpecError) as e:
        validate_spec_dict(bad)
    assert e.value.code == "spec_validation_failed"


def test_secret_values_in_security_rejected():
    bad = {**VALID, "security": {"required_env": {"PASSWORD": "hunter2"}}}
    with pytest.raises(SpecError):
        validate_spec_dict(bad)


def _spec_with_auth(auth):
    return {
        **VALID,
        "endpoints": [{
            "name": "web", "type": "http", "exposure": "host", "host_port": 50100,
            "container": "web", "container_port": 80, "auth": auth,
        }],
    }


def test_endpoint_auth_reference_is_valid():
    spec = validate_spec_dict(_spec_with_auth({
        "type": "basic",
        "credentials_ref": "1password://n100/sample-app/basic",
        "hint": "운영자에게 요청",
    }))
    assert spec.endpoints[0].auth.type == "basic"
    assert spec.endpoints[0].auth.credentials_ref.startswith("1password://")


def test_endpoint_auth_requires_reference_when_enabled():
    with pytest.raises(SpecError):
        validate_spec_dict(_spec_with_auth({"type": "basic"}))


def test_endpoint_auth_rejects_raw_secret_value():
    """credentials_ref에는 값이 아니라 scheme:// 참조만 허용한다."""
    with pytest.raises(SpecError):
        validate_spec_dict(_spec_with_auth({
            "type": "basic", "credentials_ref": "hunter2",
        }))


def test_endpoint_auth_none_rejects_reference():
    with pytest.raises(SpecError):
        validate_spec_dict(_spec_with_auth({
            "type": "none", "credentials_ref": "1password://n100/app/basic",
        }))


def test_host_port_outside_policy_rejected():
    """공유기가 포워딩하는 50000번대 밖의 호스트 포트는 거부한다."""
    spec = _spec_with_auth({"type": "none"})
    # auth.type=none은 hint/ref가 없어야 하므로 auth를 제거한다.
    spec["endpoints"][0].pop("auth")
    spec["endpoints"][0]["host_port"] = 18080
    with pytest.raises(SpecError) as e:
        validate_spec_dict(spec)
    assert e.value.code == "host_port_out_of_range"
    assert "50000-59999" in str(e.value)


def test_custom_auth_header_and_paths_are_valid():
    spec = validate_spec_dict(_spec_with_auth({
        "type": "custom", "header": "X-User-Id",
        "credentials_ref": "operator://app/demo-user", "hint": "데모 인증",
    }) | {"endpoints": [{
        **_spec_with_auth({"type": "none"})["endpoints"][0],
        "auth": {"type": "custom", "header": "X-User-Id",
                 "credentials_ref": "operator://app/demo-user"},
        "api_base_path": "/api/v1", "health_path": "/healthz",
        "docs_url": "https://example.com/docs", "bind_addr": "100.85.245.79",
    }]})
    ep = spec.endpoints[0]
    assert ep.auth.header == "X-User-Id"
    assert ep.health_path == "/healthz"


def test_basic_auth_header_rejected():
    with pytest.raises(SpecError):
        validate_spec_dict(_spec_with_auth({
            "type": "basic", "header": "X-User-Id",
            "credentials_ref": "operator://app/basic",
        }))


def test_internal_endpoint_ignores_host_port_policy():
    spec = {**VALID, "endpoints": [{
        "name": "db", "type": "tcp", "exposure": "internal",
        "container": "db", "container_port": 5432,
    }]}
    assert validate_spec_dict(spec).endpoints[0].host_port is None


def test_parse_spec_from_yaml(tmp_path):
    import yaml
    p = tmp_path / "service.yaml"
    p.write_text(yaml.safe_dump(VALID), encoding="utf-8")
    spec = parse_spec(p)
    assert spec.service.category == "web"


def test_parse_spec_missing_file(tmp_path):
    with pytest.raises(SpecError) as e:
        parse_spec(tmp_path / "nope.yaml")
    assert e.value.code == "spec_file_not_found"
