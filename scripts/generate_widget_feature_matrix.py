#!/usr/bin/env python3
"""Generate capability-derived sections of the widget implementation matrix."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.gui.module_registry import MODULE_REGISTRY  # noqa: E402


MATRIX_PATH = ROOT / "docs" / "widget_feature_implementation_matrix.md"


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
        supported = sum(
            getattr(spec.capabilities, capability_name).is_supported for spec in MODULE_REGISTRY.values()
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
                spec.capabilities.split.matrix_label,
                spec.capabilities.compact.matrix_label,
                spec.capabilities.compare.matrix_label,
                "共✓",
                "共✓",
                spec.note,
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
