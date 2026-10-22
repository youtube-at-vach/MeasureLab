"""Explicit translation-only prepare/apply workflow; never called by checks or CI."""

import argparse
import json
import sys
from pathlib import Path

import yaml

from i18n import (
    GROUPS,
    LOCALES,
    METADATA,
    TASK,
    InvalidCatalog,
    check_calls,
    check_scope,
    digest,
    git,
    load_catalog,
    make_diff,
    read_json,
    revision,
    snapshot,
    variables,
    warnings,
)

ANSWERS = "dist/i18n/answers.json"


def json_text(value):
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def prepare(root: Path, locale: str, group: str) -> dict:
    if git(root, "status", "--porcelain", "--untracked-files=all").strip():
        raise InvalidCatalog("prepare requires a clean working tree; commit or preserve existing work first")
    base = revision(root, "HEAD")
    files = snapshot(root)
    catalog = load_catalog(files)
    check_calls(files, catalog)
    task = make_diff(catalog, catalog, locale, [group], base)
    if not task["entries"]:
        raise InvalidCatalog(f"no pending translation keys in {locale}/{group}")
    answers = {
        "base_revision": base,
        "locale": locale,
        "entries": [
            {"key": entry["key"], "english": entry["new_english"], "text": None}
            for entry in task["entries"]
            if entry["new_english"] is not None
        ],
    }
    for path, value in ((TASK, task), (ANSWERS, answers)):
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json_text(value), encoding="utf-8")
    return task


def apply(root: Path) -> int:
    task = read_json((root / TASK).read_text(encoding="utf-8"))
    answers = read_json((root / ANSWERS).read_text(encoding="utf-8"))
    base = revision(root, "HEAD")
    old_files = snapshot(root, base)
    old = load_catalog(old_files)
    files = snapshot(root)
    current = load_catalog(files)
    # Recompute the immutable task and reject unrelated edits before planning any writes.
    check_scope(root, base, old, current, task)
    if files != old_files:
        raise InvalidCatalog("apply requires unchanged catalogs, metadata and Rust inputs; preserve manual edits first")
    locale = task["locale"]
    entries = {entry["key"]: entry for entry in task["entries"] if entry["new_english"] is not None}
    if (
        not isinstance(answers, dict)
        or set(answers) != {"base_revision", "locale", "entries"}
        or answers["base_revision"] != base
        or answers["locale"] != locale
        or not isinstance(answers["entries"], list)
    ):
        raise InvalidCatalog("answers must match the prepared base revision and locale")
    seen = set()
    updated = {}
    for answer in answers["entries"]:
        if not isinstance(answer, dict) or set(answer) != {"key", "english", "text"}:
            raise InvalidCatalog("each answer must contain only key, english and text")
        key = answer["key"]
        if not isinstance(key, str) or key not in entries or key in seen:
            raise InvalidCatalog(f"unknown or duplicate answer key: {key!r}")
        seen.add(key)
        source = entries[key]["new_english"]
        if answer["english"] != source:
            raise InvalidCatalog(f"do not edit English: {key}")
        text = answer["text"]
        if text is None:
            continue
        if not isinstance(text, str) or not text.strip() or variables(text) != variables(source):
            raise InvalidCatalog(f"nonempty text with the original named variables required: {key}")
        updated[key] = text
    if seen != entries.keys():
        raise InvalidCatalog("do not add or remove answer rows; leave text null to defer a key")
    removed = {entry["key"] for entry in task["entries"] if entry["new_english"] is None}
    if not updated and not removed:
        raise InvalidCatalog("no translations filled; edit only text fields in dist/i18n/answers.json")
    records = current.records.setdefault(locale, {})
    texts_by_path = {}
    for key in sorted(updated.keys() | removed):
        path = current.origins.get((locale, key), f"locales/{key.split('.')[0]}/{locale}.yml")
        if path not in texts_by_path:
            texts_by_path[path] = {k: v for k, v in current.texts[locale].items() if current.origins[locale, k] == path}
        if key in removed:
            texts_by_path[path].pop(key, None)
            records.pop(key, None)
        else:
            text = updated[key]
            texts_by_path[path][key] = text
            source = entries[key]["new_english"]
            records[key] = dict(source=source, source_hash=digest(source), translation_hash=digest(text))
    writes = {
        path: yaml.safe_dump({"_version": 1, **dict(sorted(texts.items()))}, allow_unicode=True, sort_keys=False)
        for path, texts in texts_by_path.items()
    }
    writes[METADATA] = json_text(dict(version=1, translations=current.records))
    candidate_files = {**files, **writes}
    candidate = load_catalog(candidate_files)
    check_calls(candidate_files, candidate)
    warnings(candidate)
    check_scope(root, base, old, candidate, task)
    # Validation above is all-or-nothing. Files are written only after every answer passes.
    for path, text in writes.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return len(updated)


def verify(root: Path) -> tuple[int, int]:
    task = read_json((root / TASK).read_text(encoding="utf-8"))
    base = revision(root, task["base_revision"])
    files = snapshot(root)
    current = load_catalog(files)
    check_calls(files, current)
    check_scope(root, base, load_catalog(snapshot(root, base)), current, task)
    warnings(current)
    active = [entry["key"] for entry in task["entries"] if entry["new_english"] is not None]
    completed = sum(current.state(task["locale"], key) == "current" for key in active)
    return completed, len(active) - completed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    commands = parser.add_subparsers(dest="command", required=True)
    prep = commands.add_parser("prepare", help="prepare one locale/group from clean HEAD")
    prep.add_argument("--locale", choices=LOCALES[1:], required=True)
    prep.add_argument("--group", choices=GROUPS, required=True)
    commands.add_parser("apply", help="validate answers, then write only scoped translations and hashes")
    commands.add_parser("verify", help="read-only check against the saved task base, including after committing")
    args = parser.parse_args()
    try:
        root = args.root.resolve()
        if args.command == "prepare":
            task = prepare(root, args.locale, args.group)
            print(f"Prepared {len(task['entries'])} keys at {task['base_revision']}.")
            print(f"Edit only text fields in {ANSWERS}; null defers a key. Removed keys are cleaned by apply.")
        elif args.command == "apply":
            print(f"Applied {apply(root)} translations. Review the diff, then run translate.py verify.")
        else:
            completed, deferred = verify(root)
            print(f"Translation task verified: {completed} current, {deferred} deferred; deferred keys use English.")
    except (InvalidCatalog, OSError, ValueError, TypeError, KeyError, RecursionError) as error:
        print(f"translation error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
