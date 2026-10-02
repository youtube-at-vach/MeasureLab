"""Guard against incomplete inventories when the registry or either ledger changes."""

from pathlib import Path

import pytest

from scripts.check_migration_inventory import check_local_links, validate_ledgers

INVENTORY = """| M01 | `Example` / [source](../src/example.py) | A | FFT | [P01](primitives.md#p01) | test | 未着手 |
| C01 | Common | capture | [P01](primitives.md#p01) | source / test | 未着手 |
"""
PRIMITIVES = """## P01

利用機能: M01, C01

| 入出力・単位 | FS |
| Timebase・状態・初期化 | stream |
| validity・精度・共有条件 | f64 |
| 現行の入口 | source |
| 参照検証 | test |
"""
SOURCES = {"Example": "src/example.py"}


def test_matching_inventory():
    assert validate_ledgers(INVENTORY, PRIMITIVES, SOURCES) == []


@pytest.mark.parametrize(
    ("inventory", "primitives", "message"),
    [
        (INVENTORY.replace("`Example`", "`Renamed`"), PRIMITIVES, "Module coverage mismatch"),
        (INVENTORY.replace("src/example.py", "src/moved.py"), PRIMITIVES, "registry source mismatch"),
        (INVENTORY + INVENTORY, PRIMITIVES, "Duplicate feature ID"),
        (INVENTORY.replace("M01", "M02") + INVENTORY, PRIMITIVES, "Duplicate module key"),
        (INVENTORY.replace("未着手", "done"), PRIMITIVES, "unknown state"),
        (INVENTORY.replace("[P01]", "[P02]"), PRIMITIVES, "unknown primitive"),
        (INVENTORY.replace("#p01", "#p02"), PRIMITIVES, "anchor does not match"),
        (INVENTORY, PRIMITIVES.replace("M01, C01", "M01"), "reverse mapping mismatch"),
        (INVENTORY, PRIMITIVES.replace("M01, C01", "M01, C99"), "reverse mapping mismatch"),
        (INVENTORY, PRIMITIVES.replace("M01, C01", "M01, M01, C01"), "duplicate consumers"),
        (INVENTORY, PRIMITIVES + PRIMITIVES, "Duplicate primitive ID"),
        (INVENTORY, PRIMITIVES.replace("| 入出力・単位 | FS |", ""), "missing field"),
        (INVENTORY, "", "No primitives found"),
    ],
)
def test_invalid_inventory_is_rejected(inventory, primitives, message):
    assert any(message in error for error in validate_ledgers(inventory, primitives, SOURCES))


def test_new_registered_module_requires_inventory_entry():
    sources = SOURCES | {"Added module": "src/added.py"}
    assert any("Added module" in error for error in validate_ledgers(INVENTORY, PRIMITIVES, sources))


def test_missing_local_reference_is_reported(tmp_path: Path):
    doc = tmp_path / "inventory.md"
    doc.write_text("[missing](gone.py) [web](https://example.com) [heading](#local)", encoding="utf-8")
    assert check_local_links([doc]) == ["inventory.md: missing link target gone.py"]
    (tmp_path / "gone.py").touch()
    assert check_local_links([doc]) == []
