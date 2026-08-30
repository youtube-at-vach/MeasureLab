import logging
import sys
from unittest.mock import Mock

from main_gui import _install_expected_exception_logger
from src.core.errors import AudioEngineReservedError


def test_reserved_audio_error_is_logged_without_calling_previous_hook(caplog, monkeypatch):
    previous_hook = Mock()
    monkeypatch.setattr(sys, "excepthook", previous_hook)
    _install_expected_exception_logger()

    error = AudioEngineReservedError("Audio engine is reserved by Remote Audio I/O")
    with caplog.at_level(logging.WARNING, logger="main_gui"):
        sys.excepthook(type(error), error, error.__traceback__)

    previous_hook.assert_not_called()
    assert caplog.messages == ["Audio operation rejected: Audio engine is reserved by Remote Audio I/O"]


def test_unexpected_error_is_forwarded_to_previous_hook(monkeypatch):
    previous_hook = Mock()
    monkeypatch.setattr(sys, "excepthook", previous_hook)
    _install_expected_exception_logger()

    error = RuntimeError("unexpected")
    sys.excepthook(type(error), error, error.__traceback__)

    previous_hook.assert_called_once_with(type(error), error, error.__traceback__)
