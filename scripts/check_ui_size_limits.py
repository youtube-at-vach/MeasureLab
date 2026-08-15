#!/usr/bin/env python3
"""Verify MeasureLab's real, displayed GUI layout contracts."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass
from unittest.mock import patch

# Avoid real configuration writes and audio-device access during verification.
os.environ["MEASURELAB_TESTING"] = "1"

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)

try:
    from PyQt6.QtGui import QFont
    from PyQt6.QtWidgets import QApplication, QScrollArea, QTabWidget, QWidget

    from src.core.config_manager import ConfigManager
    from src.core.localization import get_manager
    from src.gui.main_window import MainWindow
except ImportError as exc:
    print(f"Error importing GUI modules: {exc}")
    print("Please ensure your virtual environment is activated and dependencies are installed.")
    sys.exit(1)


MAX_WINDOW_WIDTH = 1400
MAX_WINDOW_HEIGHT = 740
MAX_WIDGET_WIDTH = 1180
MAX_WIDGET_HEIGHT = 690

SCROLL_ROLE_PROPERTY = "measurelabScrollRole"
AUDIT_EXPAND_PROPERTY = "measurelabLayoutAuditExpand"
OUTER_CONTROLS_ROLE = "outer-controls"
DYNAMIC_CONTENT_ROLE = "dynamic-content"
VALID_SCROLL_ROLES = {OUTER_CONTROLS_ROLE, DYNAMIC_CONTENT_ROLE}
RESULT_PREFIX = "__MEASURELAB_LAYOUT_RESULT__="

# Keep a preloaded window alive until its single-profile worker exits. Some
# modules own unparented QThreads that Qt must not destroy between profiles.
_AUDIT_WINDOWS: list[MainWindow] = []


@dataclass(frozen=True, slots=True)
class AuditProfile:
    language: str
    font_pixel_size: int | None

    @property
    def label(self) -> str:
        font = "default" if self.font_pixel_size is None else f"{self.font_pixel_size}px"
        return f"{self.language}/{font}"


@dataclass(frozen=True, slots=True)
class LayoutFailure:
    profile: str
    module: str
    state: str
    detail: str


def _process_events() -> None:
    QApplication.processEvents()
    QApplication.sendPostedEvents()
    QApplication.processEvents()


def _expand_layout_audit_controls(page: QWidget) -> None:
    for widget in page.findChildren(QWidget):
        if not bool(widget.property(AUDIT_EXPAND_PROPERTY)):
            continue
        setter = getattr(widget, "setChecked", None)
        if callable(setter):
            setter(True)
    _process_events()


def _scroll_name(scroll: QScrollArea) -> str:
    return scroll.objectName() or type(scroll).__name__


def _audit_scroll_areas(
    page: QWidget,
    *,
    profile: AuditProfile,
    module_name: str,
    state: str,
) -> list[LayoutFailure]:
    failures: list[LayoutFailure] = []
    for scroll in page.findChildren(QScrollArea):
        if not scroll.isVisible():
            continue

        role = str(scroll.property(SCROLL_ROLE_PROPERTY) or "")
        name = _scroll_name(scroll)
        if role not in VALID_SCROLL_ROLES:
            failures.append(
                LayoutFailure(
                    profile.label,
                    module_name,
                    state,
                    f"{name} has no valid {SCROLL_ROLE_PROPERTY!r} declaration",
                )
            )
            continue

        vertical_max = scroll.verticalScrollBar().maximum()
        horizontal_max = scroll.horizontalScrollBar().maximum()
        if role == OUTER_CONTROLS_ROLE and (vertical_max or horizontal_max):
            failures.append(
                LayoutFailure(
                    profile.label,
                    module_name,
                    state,
                    f"{name} outer controls scroll (vertical={vertical_max}, horizontal={horizontal_max})",
                )
            )
        elif role == DYNAMIC_CONTENT_ROLE and horizontal_max:
            failures.append(
                LayoutFailure(
                    profile.label,
                    module_name,
                    state,
                    f"{name} dynamic content scrolls horizontally ({horizontal_max})",
                )
            )
    return failures


def _audit_visible_state(
    window: MainWindow,
    page: QWidget,
    *,
    profile: AuditProfile,
    module_name: str,
    state: str,
) -> list[LayoutFailure]:
    failures: list[LayoutFailure] = []
    window.updateGeometry()
    page.updateGeometry()
    _process_events()

    hint = page.minimumSizeHint()
    if hint.width() > MAX_WIDGET_WIDTH or hint.height() > MAX_WIDGET_HEIGHT:
        failures.append(
            LayoutFailure(
                profile.label,
                module_name,
                state,
                f"minimumSizeHint {hint.width()}x{hint.height()} exceeds {MAX_WIDGET_WIDTH}x{MAX_WIDGET_HEIGHT}",
            )
        )

    failures.extend(
        _audit_scroll_areas(
            page,
            profile=profile,
            module_name=module_name,
            state=state,
        )
    )
    return failures


def _audit_page_tabs(
    window: MainWindow,
    page: QWidget,
    *,
    profile: AuditProfile,
    module_name: str,
) -> list[LayoutFailure]:
    failures = _audit_visible_state(
        window,
        page,
        profile=profile,
        module_name=module_name,
        state="default",
    )

    tab_widgets = list(page.findChildren(QTabWidget))
    for tab_number, tabs in enumerate(tab_widgets, start=1):
        original_index = tabs.currentIndex()
        for index in range(tabs.count()):
            tabs.setCurrentIndex(index)
            _process_events()
            failures.extend(
                _audit_visible_state(
                    window,
                    page,
                    profile=profile,
                    module_name=module_name,
                    state=f"tabs-{tab_number}:{index}",
                )
            )
        tabs.setCurrentIndex(original_index)
    return failures


def _audit_profile(app: QApplication, profile: AuditProfile, base_font: QFont) -> list[LayoutFailure]:
    font = QFont(base_font)
    if profile.font_pixel_size is not None:
        font.setPixelSize(profile.font_pixel_size)
    app.setFont(font)

    failures: list[LayoutFailure] = []
    with patch.object(ConfigManager, "get_language", return_value=profile.language):
        window = MainWindow(enable_experimental=True)
        window.preload_all_modules()
        window.resize(MAX_WINDOW_WIDTH, MAX_WINDOW_HEIGHT)
        window.show()
        _process_events()

        window_hint = window.minimumSizeHint()
        if window_hint.width() > MAX_WINDOW_WIDTH or window_hint.height() > MAX_WINDOW_HEIGHT:
            failures.append(
                LayoutFailure(
                    profile.label,
                    "MainWindow",
                    "preloaded",
                    (
                        f"minimumSizeHint {window_hint.width()}x{window_hint.height()} exceeds "
                        f"{MAX_WINDOW_WIDTH}x{MAX_WINDOW_HEIGHT}"
                    ),
                )
            )

        for row in range(window.sidebar.count()):
            item = window.sidebar.item(row)
            module_name = item.text()
            window.sidebar.setCurrentRow(row)
            _process_events()

            page = window.content_area.currentWidget()
            if page is None:
                continue
            _expand_layout_audit_controls(page)
            failures.extend(
                _audit_page_tabs(
                    window,
                    page,
                    profile=profile,
                    module_name=module_name,
                )
            )

        _AUDIT_WINDOWS.append(window)

    return failures


def _profiles() -> list[AuditProfile]:
    languages = sorted(get_manager().available_languages)
    # Pixel-sized fonts have substantially different metrics across Qt's
    # platform backends. Audit every translation with the platform's real
    # application default; explicit font sizes remain available through the
    # single-profile CLI for targeted diagnostics.
    return [AuditProfile(language, None) for language in languages]


def _run_single_profile(language: str, font_arg: str) -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    base_font = QFont(app.font())
    font_pixel_size = None if font_arg == "default" else int(font_arg)
    failures = _audit_profile(app, AuditProfile(language, font_pixel_size), base_font)
    payload = json.dumps([asdict(failure) for failure in failures], ensure_ascii=False)
    print(f"{RESULT_PREFIX}{payload}", flush=True)
    os._exit(0)


def _run_profile_worker(profile: AuditProfile) -> list[LayoutFailure]:
    font_arg = "default" if profile.font_pixel_size is None else str(profile.font_pixel_size)
    result = subprocess.run(
        [sys.executable, __file__, "--profile", profile.language, font_arg],
        check=False,
        capture_output=True,
        text=True,
    )
    result_line = next((line for line in result.stdout.splitlines() if line.startswith(RESULT_PREFIX)), None)
    if result.returncode != 0 or result_line is None:
        output = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
        detail = output or f"profile worker exited with status {result.returncode}"
        return [LayoutFailure(profile.label, "layout checker", "worker", detail)]

    raw_failures = json.loads(result_line.removeprefix(RESULT_PREFIX))
    return [LayoutFailure(**failure) for failure in raw_failures]


def main() -> int:
    failures: list[LayoutFailure] = []

    print("=== MeasureLab displayed UI layout check ===")
    print(f"MainWindow limit: {MAX_WINDOW_WIDTH}x{MAX_WINDOW_HEIGHT}")
    print(f"Module limit: {MAX_WIDGET_WIDTH}x{MAX_WIDGET_HEIGHT}")

    for profile in _profiles():
        print(f"Checking {profile.label}...", flush=True)
        failures.extend(_run_profile_worker(profile))

    if failures:
        print(f"\nVerification failed with {len(failures)} layout violation(s):")
        for failure in failures:
            print(f"- [{failure.profile}] {failure.module} ({failure.state}): {failure.detail}")
        print("\nReorganize controls with shallow tabs, reduce redundant margins, or use flexible size policies.")
        print("Do not hide fixed control overflow inside a scroll area to satisfy the size ceiling.")
        return 1

    print("\nVerification Passed!")
    print("All displayed layouts conform to size and scrolling contracts.")
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--profile":
        _run_single_profile(sys.argv[2], sys.argv[3])
    raise SystemExit(main())
