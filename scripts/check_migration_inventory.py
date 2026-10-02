"""Check migration ledger coverage and links without importing Qt or DSP code."""

from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.core.module_constants import ALL_MODULE_KEYS  # noqa: E402
from src.gui.module_registry import MODULE_REGISTRY  # noqa: E402

STATES = {"未着手", "契約作成済み", "実装中", "比較合格", "実機・UI待ち", "移行完了"}
LINK = re.compile(r"\[[^\]\n]+\]\(([^)\n]+)\)")


def validate_ledgers(inventory: str, primitives: str, expected_sources: dict[str, str]) -> list[str]:
    """Validate the documented table format and both directions of the mapping."""
    errors: list[str] = []
    features: dict[str, set[str]] = {}
    keys: list[str] = []
    for line in inventory.splitlines():
        if not re.match(r"^\| [MC]\d+ \|", line):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        feature_id = cells[0]
        is_module = feature_id.startswith("M")
        if len(cells) != (7 if is_module else 6):
            errors.append(f"{feature_id}: invalid table column count")
            continue
        if feature_id in features:
            errors.append(f"Duplicate feature ID: {feature_id}")
        if cells[-1] not in STATES:
            errors.append(f"{feature_id}: unknown state {cells[-1]!r}")
        primitive_cell = cells[4 if is_module else 3]
        pairs = re.findall(r"\[(P\d+)\]\(primitives\.md#(p\d+)\)", primitive_cell)
        refs = [pid for pid, _ in pairs]
        if not refs or len(refs) != len(set(refs)):
            errors.append(f"{feature_id}: missing or duplicate primitive references")
        if any(pid.lower() != anchor for pid, anchor in pairs):
            errors.append(f"{feature_id}: primitive anchor does not match ID")
        features[feature_id] = set(refs)
        if is_module:
            match = re.search(r"`([^`]+)` / \[source\]\(\.\./([^)]+)\)", cells[1])
            if not match:
                errors.append(f"{feature_id}: missing module key/source")
                continue
            key, source = match.groups()
            keys.append(key)
            if expected_sources.get(key) != source:
                errors.append(f"{feature_id}: registry source mismatch for {key!r}")
    for key, count in Counter(keys).items():
        if count > 1:
            errors.append(f"Duplicate module key: {key}")
    if set(keys) != set(expected_sources):
        errors.append(f"Module coverage mismatch: missing={sorted(set(expected_sources) - set(keys))}")

    sections = re.split(r"(?m)^## (P\d+)\s*$", primitives)
    reverse: dict[str, set[str]] = {}
    for pid, section in zip(sections[1::2], sections[2::2], strict=True):
        if pid in reverse:
            errors.append(f"Duplicate primitive ID: {pid}")
        match = re.search(r"(?m)^利用機能: (.+)$", section)
        consumers = re.findall(r"\b[MC]\d+\b", match[1]) if match else []
        if not consumers or len(consumers) != len(set(consumers)):
            errors.append(f"{pid}: missing or duplicate consumers")
        reverse[pid] = set(consumers)
        expected = {fid for fid, refs in features.items() if pid in refs}
        if set(consumers) != expected:
            errors.append(f"{pid}: reverse mapping mismatch")
        for field in ("入出力・単位", "Timebase・状態・初期化", "validity・精度・共有条件", "現行の入口", "参照検証"):
            if not re.search(rf"(?m)^\| {re.escape(field)} \| \S.+ \|$", section):
                errors.append(f"{pid}: missing field {field}")
    if not reverse:
        errors.append("No primitives found")
    for fid, refs in features.items():
        for pid in sorted(refs - reverse.keys()):
            errors.append(f"{fid}: unknown primitive {pid}")
    return errors


def check_local_links(documents: list[Path]) -> list[str]:
    errors = []
    for document in documents:
        for target in LINK.findall(document.read_text(encoding="utf-8")):
            if "://" in target or target.startswith(("#", "mailto:")):
                continue
            relative_path = target.split("#", 1)[0]
            if not (document.parent / relative_path).is_file():
                errors.append(f"{document.name}: missing link target {target}")
    return errors


def main() -> int:
    migration = ROOT / "migration"
    expected_sources = {key: entry.module_path.replace(".", "/") + ".py" for key, entry in MODULE_REGISTRY.items()}
    errors = []
    if set(ALL_MODULE_KEYS) != set(MODULE_REGISTRY) or len(ALL_MODULE_KEYS) != len(set(ALL_MODULE_KEYS)):
        errors.append("ALL_MODULE_KEYS and MODULE_REGISTRY disagree or contain duplicates")
    errors.extend(
        validate_ledgers(
            (migration / "inventory.md").read_text(encoding="utf-8"),
            (migration / "primitives.md").read_text(encoding="utf-8"),
            expected_sources,
        )
    )
    errors.extend(check_local_links(sorted(migration.rglob("*.md"))))
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print(f"Migration inventory OK: {len(expected_sources)} module keys, bidirectional mappings, local links")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
