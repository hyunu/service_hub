from app.services.deploy_plan import build_plan
from app.services.service_spec import validate_spec_dict

SPEC = {
    "schema_version": 1,
    "service": {"id": "sample-app", "name": "Sample", "description": "샘플",
                "category": "web"},
    "deployment": {"type": "docker-compose", "compose_file": "compose.yaml"},
    "containers": [{"name": "frontend", "role": "frontend", "required": True},
                   {"name": "backend", "role": "backend", "required": True}],
    "endpoints": [{"name": "web", "type": "http", "exposure": "host",
                   "host_port": 8123, "container": "frontend", "container_port": 3000}],
    "security": {"required_env": ["EXAMPLE_VAR"]},
}


def test_plan_ready_when_all_checks_pass(fake_ctx):
    spec = validate_spec_dict(SPEC)
    plan = build_plan(spec, ctx=fake_ctx(available_env={"EXAMPLE_VAR"}))
    assert plan["result"] == "READY"
    assert plan["service"] == "sample-app"
    assert any(c["name"] == "frontend" for c in plan["changes"])


def test_plan_blocked_on_port_conflict(fake_ctx):
    spec = validate_spec_dict(SPEC)
    plan = build_plan(spec, ctx=fake_ctx(conflicting_ports={8123}))
    assert plan["result"] == "BLOCKED"
    assert any("포트" in i["message"] for i in plan["impact"])


def test_plan_blocked_on_missing_env(fake_ctx):
    spec = validate_spec_dict(SPEC)
    plan = build_plan(spec, ctx=fake_ctx(available_env=set()))
    assert plan["result"] == "BLOCKED"
    assert any("환경 변수" in i["message"] for i in plan["impact"])


def test_plan_reports_resource_warning(fake_ctx):
    spec = validate_spec_dict({**SPEC, "resources": {"memory_limit_mb": 2048}})
    ctx = fake_ctx(available_env={"EXAMPLE_VAR"}, mem_available_mb=100)
    plan = build_plan(spec, ctx=ctx)
    assert any(w["level"] == "warning" for w in plan["warnings"])


def test_plan_has_no_runtime_side_effects(fake_ctx):
    spec = validate_spec_dict(SPEC)
    plan = build_plan(spec, ctx=fake_ctx(available_env={"EXAMPLE_VAR"}))
    assert plan["runtime_unchanged"] is True
