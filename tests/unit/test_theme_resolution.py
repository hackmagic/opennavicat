"""Regression tests for issue #1 — the app crashed at startup on an unknown theme.

The reporter's settings.json carried the value this project used to ship as its
default, ``"light"``, while the registry only ever registered ``pro-dark`` and
``pro-light``; ``apply_theme`` then raised ``RuntimeError("No theme found")``
inside ``MainWindow.__init__``, so the frozen GUI never opened a window.
"""

from __future__ import annotations

import pytest

from open_navicat.ui import themes


class TestResolveTheme:
    def test_exact_key_is_returned_unchanged(self) -> None:
        assert themes.resolve_theme("pro-dark") == "pro-dark"
        assert themes.resolve_theme("pro-light") == "pro-light"

    def test_legacy_light_maps_to_the_registered_light_theme(self) -> None:
        # The literal value from the reporter's settings.json.
        assert themes.resolve_theme("light") == "pro-light"

    def test_legacy_acrylic_maps_to_a_theme_that_exists(self) -> None:
        assert themes.resolve_theme("acrylic") == "pro-dark"

    @pytest.mark.parametrize("spelling", ["pro_light", "Pro-Light", "PRO-LIGHT", "prolight"])
    def test_spelling_variants_of_a_registered_theme(self, spelling: str) -> None:
        assert themes.resolve_theme(spelling) == "pro-light"

    @pytest.mark.parametrize("value", ["", None, "   ", "no-such-theme", "0"])
    def test_unresolvable_names_return_none(self, value: str | None) -> None:
        assert themes.resolve_theme(value) is None

    def test_every_resolvable_name_is_in_the_registry(self) -> None:
        for name in list(themes.THEME_ALIASES) + ["pro-dark", "pro-light"]:
            assert themes.resolve_theme(name) in themes.theme_map


class TestFallbackTheme:
    def test_fallback_is_registered(self) -> None:
        assert themes.fallback_theme() in themes.theme_map

    def test_fallback_is_the_default_when_available(self) -> None:
        assert themes.fallback_theme() == themes.DEFAULT_THEME


class TestApplyTheme:
    def test_unknown_name_degrades_instead_of_raising(self, qapp) -> None:
        # The exact call MainWindow.__init__ makes with a stale settings.json:
        # before the fix it raised RuntimeError and no window was ever shown.
        assert themes.apply_theme("light", qapp, None) == "pro-light"

    def test_unknown_garbage_degrades_to_the_default(self, qapp) -> None:
        assert themes.apply_theme("definitely-not-a-theme", qapp, None) == themes.DEFAULT_THEME

    def test_returns_the_theme_it_actually_applied(self, qapp) -> None:
        assert themes.apply_theme("pro-dark", qapp, None) == "pro-dark"

    def test_stylesheet_is_set_for_the_requested_theme(self, qapp) -> None:
        themes.apply_theme("light", qapp, None)
        assert qapp.styleSheet()


class TestShippedDefault:
    def test_config_default_theme_resolves(self) -> None:
        # A fresh install writes this value into settings.json, so it must name
        # a theme that exists — otherwise every new user crashes on first launch.
        from open_navicat.config import AppConfig

        assert themes.resolve_theme(AppConfig._defaults()["theme"]) is not None
