"""Construct and tear down every registered measurement page."""

from __future__ import annotations

import pytest
from types import SimpleNamespace

from tests.gui_fuzz.diagnostics import Scenario
from tests.gui_fuzz.discovery import create_module_widget, module_keys
from tests.gui_fuzz.invariants import check_closed


@pytest.mark.parametrize("module_key", module_keys())
def test_registered_widget_smoke(module_key, qapp, fuzz_engine):
    with Scenario(module_key, 0) as trace:
        module, widget = create_module_widget(module_key, fuzz_engine)
        trace.module, trace.widget, trace.engine = module, widget, fuzz_engine
        widget.show()
        for _ in range(3):
            qapp.processEvents()
        assert widget.isVisible()
        widget.close()
        qapp.processEvents()
        check_closed(widget, module, fuzz_engine)
        trace.assert_clean()
        widget.deleteLater()
        qapp.processEvents()


@pytest.mark.parametrize("page", ("settings", "remote", "welcome"))
def test_shell_page_smoke(page, qapp, fuzz_engine, monkeypatch, tmp_path):
    from src.core.config_manager import ConfigManager

    with Scenario(page, 0) as trace:
        monkeypatch.setattr(ConfigManager, "_ensure_screenshot_dir", lambda *args: None)
        config = ConfigManager(str(tmp_path / "config.json"))
        if page == "settings":
            from src.gui.widgets.settings import SettingsWidget

            widget = SettingsWidget(fuzz_engine, config)
        elif page == "remote":
            from src.gui.widgets.remote_audio_io import RemoteAudioIOWidget

            monkeypatch.setattr(
                RemoteAudioIOWidget,
                "_new_discovery",
                lambda self: SimpleNamespace(start=lambda: None, stop=lambda: None, snapshot=lambda: ()),
            )
            widget = RemoteAudioIOWidget(fuzz_engine, config)
        else:
            from src.core.update_checker import UpdateChecker
            from src.gui.widgets.welcome import WelcomeWidget

            monkeypatch.setattr(UpdateChecker, "start", lambda self: None)
            widget = WelcomeWidget()
        trace.widget, trace.engine = widget, fuzz_engine
        widget.show()
        for _ in range(3):
            qapp.processEvents()
        assert widget.isVisible()
        widget.close()
        qapp.processEvents()
        trace.assert_clean()
        widget.deleteLater()
