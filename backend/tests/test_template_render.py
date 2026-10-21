from pathlib import Path

from app.services.template_render import render_service_dir


def test_render_creates_standard_layout(tmp_path):
    out = render_service_dir(tmp_path, "sample-app", name="Sample App", category="web")
    out = Path(out)
    for rel in ("service.yaml", "compose.yaml", ".env.example", "README.md", ".gitignore",
                "config/.gitkeep", "data/.gitkeep", "logs/.gitkeep"):
        assert (out / rel).exists(), rel
    text = (out / "service.yaml").read_text(encoding="utf-8")
    assert "id: sample-app" in text
    assert "schema_version: 1" in text


def test_render_rejects_bad_id(tmp_path):
    import pytest
    with pytest.raises(ValueError):
        render_service_dir(tmp_path, "Bad_ID")


def test_render_refuses_existing_dir(tmp_path):
    (tmp_path / "sample-app").mkdir()
    import pytest
    with pytest.raises(FileExistsError):
        render_service_dir(tmp_path, "sample-app")


def test_gitignore_and_env_example_have_no_secrets(tmp_path):
    out = Path(render_service_dir(tmp_path, "sample-app"))
    gi = (out / ".gitignore").read_text(encoding="utf-8")
    assert ".env" in gi
    envx = (out / ".env.example").read_text(encoding="utf-8")
    assert "=" in envx
