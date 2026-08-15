#!/usr/bin/env python3
"""Generate capability-derived sections of the widget implementation matrix."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.gui.module_registry import (  # noqa: E402
    MODULE_REGISTRY,
    CapabilityExclusionReason,
    FeatureCapability,
)


MATRIX_PATH = ROOT / "docs" / "widget_feature_implementation_matrix.md"

CAPABILITY_FIELDS = {
    "compact": "compact_mode",
    "split": "split_window",
    "compare": "comparison",
}
EXCLUSION_LABELS = {
    CapabilityExclusionReason.NO_INDEPENDENT_DISPLAY: "外A",
    CapabilityExclusionReason.NON_TRACE_COMPARISON: "外B",
    CapabilityExclusionReason.COMPARISON_RECEIVER: "外C",
    CapabilityExclusionReason.COMPARISON_DEFERRED: "外D",
    CapabilityExclusionReason.COMPACT_DEFERRED: "外E",
    CapabilityExclusionReason.SPLIT_DEFERRED: "外F",
}
EXCLUSION_NOTES = {
    CapabilityExclusionReason.NO_INDEPENDENT_DISPLAY: "独立表示部なし",
    CapabilityExclusionReason.NON_TRACE_COMPARISON: "比較対象がトレースではない",
    CapabilityExclusionReason.COMPARISON_RECEIVER: "比較データの受信・表示側",
    CapabilityExclusionReason.COMPARISON_DEFERRED: "比較送信は未実装",
    CapabilityExclusionReason.COMPACT_DEFERRED: "コンパクトは未実装",
    CapabilityExclusionReason.SPLIT_DEFERRED: "2 窓分割は未実装",
}


def _matrix_label(capability: FeatureCapability) -> str:
    if capability.is_supported:
        return "個✓"
    reason = capability.exclusion_reason
    if reason is None:
        raise ValueError("Excluded capabilities must declare a reason")
    return EXCLUSION_LABELS[reason]


def _module_note(capabilities) -> str:
    reasons = {
        capability.exclusion_reason
        for capability in (
            capabilities.split_window,
            capabilities.compact_mode,
            capabilities.comparison,
        )
        if capability.exclusion_reason is not None
    }
    return "、".join(EXCLUSION_NOTES[reason] for reason in EXCLUSION_NOTES if reason in reasons)


def _table(headers: list[str], rows: list[list[str]], alignments: list[str]) -> str:
    separators = []
    for alignment in alignments:
        if alignment == "center":
            separators.append(":---:")
        elif alignment == "right":
            separators.append("---:")
        else:
            separators.append("---")

    def format_row(row: list[str]) -> str:
        return "|" + "|".join(row) + "|"

    return "\n".join([format_row(headers), format_row(separators), *(format_row(row) for row in rows)])


def render_summary() -> str:
    module_count = len(MODULE_REGISTRY)
    feature_rows = [
        ["単一ウィンドウ分離（State B）", f"{module_count} / {module_count}", "100.0%", "0", "0", "共通経路を確認", "共通ラッパー"],
        ["スクリーンショット", f"{module_count} / {module_count}", "100.0%", "0", "0", "共通経路を確認", "共通ラッパー"],
        ["ログビューア表示", f"{module_count} / {module_count}", "100.0%", "0", "0", "共通経路を確認", "共通ラッパー"],
    ]
    labels = {
        "compact": ("コンパクトモード", "ウィジェット個別"),
        "split": ("表示／操作の 2 窓分割（State C）", "ウィジェット個別"),
        "compare": ("Plot Comparer への送信", "ウィジェット個別"),
    }
    for capability_name in ("compact", "split", "compare"):
        field_name = CAPABILITY_FIELDS[capability_name]
        supported = sum(
            getattr(spec.capabilities, field_name).is_supported for spec in MODULE_REGISTRY.values()
        )
        label, provider = labels[capability_name]
        feature_rows.append(
            [
                label,
                f"{supported} / {supported}",
                "100.0%",
                "0",
                str(module_count - supported),
                f"{supported} / {supported}",
                provider,
            ]
        )

    return _table(
        ["機能", "実装数 / 判断対象", "実装率", "要判断", "対象外", "直接テスト済み", "提供方法"],
        feature_rows,
        ["left", "right", "right", "right", "right", "right", "left"],
    )


def render_modules() -> str:
    rows = []
    for module_key, spec in MODULE_REGISTRY.items():
        rows.append(
            [
                "✓",
                module_key,
                "共✓",
                _matrix_label(spec.capabilities.split_window),
                _matrix_label(spec.capabilities.compact_mode),
                _matrix_label(spec.capabilities.comparison),
                "共✓",
                "共✓",
                _module_note(spec.capabilities),
            ]
        )
    return _table(
        ["完了", "ウィジェット", "単一窓分離", "2 窓分割", "コンパクト", "比較送信", "撮影", "ログ", "備考"],
        rows,
        ["center", "left", "center", "center", "center", "center", "center", "center", "left"],
    )


def _replace_block(text: str, name: str, rendered: str) -> str:
    start = f"<!-- BEGIN GENERATED: {name} -->"
    end = f"<!-- END GENERATED: {name} -->"
    before, separator, remainder = text.partition(start)
    if not separator:
        raise ValueError(f"Missing marker: {start}")
    _, separator, after = remainder.partition(end)
    if not separator:
        raise ValueError(f"Missing marker: {end}")
    return f"{before}{start}\n\n{rendered}\n\n{end}{after}"


def generate_document(current: str) -> str:
    generated = _replace_block(current, "SUMMARY", render_summary())
    return _replace_block(generated, "MODULES", render_modules())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Fail if the generated sections are stale.")
    args = parser.parse_args()

    current = MATRIX_PATH.read_text(encoding="utf-8")
    generated = generate_document(current)
    if args.check:
        if generated != current:
            print(f"{MATRIX_PATH.relative_to(ROOT)} is out of date")
            return 1
        print(f"{MATRIX_PATH.relative_to(ROOT)} is up to date")
        return 0

    MATRIX_PATH.write_text(generated, encoding="utf-8")
    print(f"Updated {MATRIX_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
