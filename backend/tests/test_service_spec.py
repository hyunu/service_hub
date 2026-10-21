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
