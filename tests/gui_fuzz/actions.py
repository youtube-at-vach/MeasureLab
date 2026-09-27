"""Find executable user actions from the current QObject tree."""

from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtWidgets import (
    QAbstractButton,
    QAbstractSlider,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QLineEdit,
    QRadioButton,
    QSpinBox,
    QTabWidget,
    QWidget,
)


@dataclass(frozen=True)
class Action:
    target: QWidget
    kind: str
    value: object

    @property
    def description(self) -> str:
        path = []
        current = self.target
        while isinstance(current, QWidget):
            parent = current.parent()
            siblings = [child for child in parent.children() if type(child) is type(current)] if parent else [current]
            ordinal = siblings.index(current) if current in siblings else 0
            name = current.objectName() or f"{type(current).__name__}[{ordinal}]"
            path.append(name)
            current = parent
        return f"{'/'.join(reversed(path))}.{self.kind}({self.value!r})"

    def execute(self) -> None:
        if self.kind == "click":
            self.target.click()
        elif self.kind == "checked":
            self.target.setChecked(self.value)
        elif self.kind == "index":
            self.target.setCurrentIndex(self.value)
        elif self.kind == "value":
            self.target.setValue(self.value)
        elif self.kind == "text":
            self.target.setText(self.value)
        else:
            raise AssertionError(self.kind)


def available_actions(root: QWidget, *, primary_button: QWidget | None = None) -> list[Action]:
    """Recompute after every step; disabled/hidden controls cannot be selected."""
    actions = []
    for control in root.findChildren(QWidget):
        if not control.isEnabled() or not control.isVisibleTo(root):
            continue
        if isinstance(control, QTabWidget):
            actions.extend(Action(control, "index", n) for n in range(control.count()) if control.isTabEnabled(n))
        elif isinstance(control, QComboBox):
            actions.extend(Action(control, "index", n) for n in range(control.count()) if n != control.currentIndex())
        elif isinstance(control, (QCheckBox, QRadioButton)):
            actions.append(Action(control, "checked", not control.isChecked()))
        elif isinstance(control, (QSpinBox, QDoubleSpinBox, QAbstractSlider)):
            low, high = control.minimum(), control.maximum()
            if high > low:
                for value in (low, (low + high) / 2, high):
                    value = round(value) if not isinstance(control, QDoubleSpinBox) else value
                    if value != control.value():
                        actions.append(Action(control, "value", value))
        elif isinstance(control, QLineEdit) and not control.isReadOnly():
            # Editing can affect a path/URL; limit to explicit search/filter fields.
            name = (control.objectName() + control.placeholderText()).lower()
            if "search" in name or "filter" in name:
                actions.append(Action(control, "text", "sine"))
        elif isinstance(control, QAbstractButton):
            if control is primary_button or control.text().strip().lower() in {"reset", "clear", "clear peak"}:
                actions.append(Action(control, "click", None))
    return actions


def reveal_control(root: QWidget, control: QWidget) -> list[Action]:
    """Switch containing tabs so a lifecycle action is reachable by a user."""
    transitions = []
    for tabs in root.findChildren(QTabWidget):
        for index in range(tabs.count()):
            page = tabs.widget(index)
            if page is control or page.isAncestorOf(control):
                if tabs.currentIndex() != index and tabs.isTabEnabled(index):
                    transitions.append(Action(tabs, "index", index))
    return transitions
