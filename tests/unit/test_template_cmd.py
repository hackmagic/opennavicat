"""Tests for template command."""

from __future__ import annotations

from pathlib import Path

from open_navicat.cli.template_cmd import _TEMPLATES


class TestTemplateList:
    def test_list_returns_templates(self) -> None:
        assert len(_TEMPLATES) >= 3
        assert "daily_backup.sh" in _TEMPLATES
        assert "daily_backup.ps1" in _TEMPLATES
        assert "docker-compose.yml" in _TEMPLATES

    def test_generate_creates_file(self, tmp_path: Path) -> None:
        from open_navicat.cli.template_cmd import template_generate
        dst = tmp_path / "daily_backup.sh"
        template_generate("daily_backup.sh", str(tmp_path))
        assert dst.exists()
        assert "opennavicat backup create" in dst.read_text()

    def test_generate_unknown_exits(self) -> None:
        from open_navicat.cli.template_cmd import template_generate
        try:
            template_generate("nonexistent", ".")
            assert False, "should have raised"
        except SystemExit:
            pass
