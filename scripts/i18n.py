"""Validate Rust GUI catalogs and export reviewable translation tasks (never edit assets)."""

import argparse
import csv
import hashlib
import io
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ENGLISH = "en-US"
LOCALES = (ENGLISH, "ja", "fr", "de", "es", "pt", "ru", "zh", "ko")
GROUPS = ("common", "shell", "io", "oscilloscope", "spectrum", "spectrogram", "xy", "generator", "lockin", "comparison")
METADATA = "i18n/source-hashes.json"
TASK = "i18n/translation-task.json"
KEY = re.compile(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+")
VARIABLE = re.compile(r"%\{([a-z][a-z0-9_]*)\}")


class InvalidCatalog(ValueError):
    """Invalid source or task; callers must not accept or apply the translation."""


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def variables(text: str) -> set[str]:
    if "%{" in VARIABLE.sub("", text):
        raise InvalidCatalog(f"malformed named variable in {text!r}")
    return set(VARIABLE.findall(text))


def unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if not isinstance(key, str) or key in result:
            raise InvalidCatalog(f"non-string or duplicate mapping key: {key!r}")
        result[key] = value
    return result


class UniqueLoader(yaml.SafeLoader):
    """Reject duplicates before PyYAML can silently overwrite them."""

    def construct_mapping(self, node, deep=False):
        return unique_pairs(
            (self.construct_object(key, deep=deep), self.construct_object(value, deep=deep))
            for key, value in node.value
        )


def read_json(text: str):
    return json.loads(text, object_pairs_hook=unique_pairs)


def git(root: Path, *args: str) -> str:
    executable = shutil.which("git")
    if executable is None:
        raise InvalidCatalog("Git executable is required for revision/scope checks")
    result = subprocess.run(  # noqa: S603 - argument array, no shell; refs validated by rev-parse
        [executable, "-C", str(root), *args], capture_output=True, text=True, encoding="utf-8", check=False
    )
    if result.returncode:
        raise InvalidCatalog(result.stderr.strip())
    return result.stdout


def revision(root: Path, ref: str) -> str:
    return git(root, "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}").strip()


def snapshot(root: Path, ref: str | None = None) -> dict[str, str]:
    """Read only managed catalog/metadata/Rust inputs, including working-tree additions."""
    if ref is not None:
        entries = []
        for entry in git(root, "ls-tree", "-r", "-z", ref, "--", "locales", "i18n", "src").split("\0"):
            if entry:
                header, path = entry.split("\t", 1)
                if relevant(path):
                    entries.append((path, header.split()[2]))
        executable = shutil.which("git")
        if executable is None:
            raise InvalidCatalog("Git executable is required for revision/scope checks")
        result = subprocess.run(  # noqa: S603 - fixed Git batch protocol, object IDs from ls-tree
            [executable, "-C", str(root), "cat-file", "--batch"],
            input="".join(oid + "\n" for _, oid in entries).encode(),
            capture_output=True,
            check=False,
        )
        if result.returncode:
            raise InvalidCatalog(result.stderr.decode("utf-8").strip())
        files = {}
        offset = 0
        for path, oid in entries:
            end = result.stdout.index(b"\n", offset)
            header = result.stdout[offset:end].decode("ascii").split()
            if len(header) != 3 or header[:2] != [oid, "blob"]:
                raise InvalidCatalog(f"cannot read catalog snapshot: {path}")
            size = int(header[2])
            offset = end + 1
            files[path] = result.stdout[offset : offset + size].decode("utf-8")
            offset += size + 1
        if offset != len(result.stdout):
            raise InvalidCatalog("invalid Git snapshot batch response")
        return files
    paths = [p for folder in ("locales", "i18n", "src") for p in (root / folder).rglob("*") if p.is_file()]
    return {
        path.relative_to(root).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted(paths)
        if relevant(path.relative_to(root).as_posix())
    }


def relevant(path: str) -> bool:
    return (
        (path.startswith("locales/") and path.endswith((".yml", ".yaml")))
        or path == METADATA
        or (path.startswith("src/") and path.endswith(".rs"))
    )


@dataclass
class Catalog:
    texts: dict[str, dict[str, str]] = field(default_factory=lambda: {locale: {} for locale in LOCALES})
    origins: dict[tuple[str, str], str] = field(default_factory=dict)
    records: dict = field(default_factory=dict)

    @property
    def english(self) -> dict[str, str]:
        return self.texts[ENGLISH]

    def state(self, locale: str, key: str) -> str:
        text = self.texts[locale].get(key)
        if not text or not text.strip():
            return "missing"
        record = self.records.get(locale, {}).get(key)
        if record is None:
            return "unreviewed"
        if record["source_hash"] != digest(self.english[key]):
            return "stale"
        if variables(text) != variables(self.english[key]):
            return "invalid_variables"
        return "current"


def load_catalog(files: dict[str, str]) -> Catalog:
    catalog = Catalog()
    namespaces = {locale: set() for locale in LOCALES}
    for path, source in sorted(files.items()):
        if not path.startswith("locales/"):
            continue
        parts = Path(path).parts
        locale = Path(path).stem
        if len(parts) != 3 or parts[1] not in GROUPS or locale not in LOCALES or not path.endswith(".yml"):
            raise InvalidCatalog(f"{path}: expected locales/<group>/<locale>.yml")
        try:
            data = yaml.load(source, Loader=UniqueLoader)  # noqa: S506 - SafeLoader subclass
        except yaml.YAMLError as error:
            raise InvalidCatalog(f"{path}: {error}") from error
        if not isinstance(data, dict) or type(data.get("_version")) is not int or data["_version"] != 1:
            raise InvalidCatalog(f"{path}: expected _version: 1 and a mapping")

        def flatten(mapping: dict, prefix: str = "", *, locale: str = locale, path: str = path) -> None:
            for name, value in mapping.items():
                key = f"{prefix}.{name}" if prefix else name
                if isinstance(value, dict):
                    # Empty namespaces are permitted while English groups are introduced in I3.
                    if (
                        not re.fullmatch(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*", key)
                        or key.split(".")[0] not in GROUPS
                    ):
                        raise InvalidCatalog(f"{path}: invalid namespace {key!r}")
                    namespaces[locale].add(key)
                    flatten(value, key)
                else:
                    if not KEY.fullmatch(key) or key.split(".")[0] not in GROUPS:
                        raise InvalidCatalog(f"{path}: key needs an explicit known namespace: {key!r}")
                    if not isinstance(value, str):
                        raise InvalidCatalog(f"{path}: {key}: expected a string (quote numbers/booleans)")
                    if locale == ENGLISH and not value.strip():
                        raise InvalidCatalog(f"{path}: {key}: empty English")
                    variables(value)
                    segments = key.split(".")
                    namespaces[locale].update(".".join(segments[:i]) for i in range(1, len(segments)))
                    if key in catalog.texts[locale]:
                        raise InvalidCatalog(f"{path}: duplicate final key {locale}:{key}")
                    catalog.texts[locale][key] = value
                    catalog.origins[locale, key] = path

        flatten({key: value for key, value in data.items() if key != "_version"})
    for locale, texts in catalog.texts.items():
        collisions = texts.keys() & namespaces[locale]
        if collisions:
            raise InvalidCatalog(f"namespace collision in {locale}: {sorted(collisions)}")
    if METADATA in files:
        data = read_json(files[METADATA])
        if not isinstance(data, dict) or set(data) != {"version", "translations"} or type(data["version"]) is not int:
            raise InvalidCatalog(f"{METADATA}: expected version and translations")
        if data["version"] != 1 or not isinstance(data["translations"], dict):
            raise InvalidCatalog(f"{METADATA}: unsupported metadata format")
        catalog.records = data["translations"]
        for locale, records in catalog.records.items():
            if locale not in LOCALES[1:] or not isinstance(records, dict):
                raise InvalidCatalog(f"{METADATA}: invalid translation locale: {locale}")
            for key, record in records.items():
                fields = {"source", "source_hash", "translation_hash"}
                if not KEY.fullmatch(key) or not isinstance(record, dict) or set(record) != fields:
                    raise InvalidCatalog(f"{METADATA}: invalid record: {locale}:{key}")
                if not all(isinstance(value, str) for value in record.values()):
                    raise InvalidCatalog(f"{METADATA}: record values must be strings: {locale}:{key}")
                if record["source_hash"] != digest(record["source"]):
                    raise InvalidCatalog(f"{METADATA}: corrupt source hash: {locale}:{key}")
                variables(record["source"])
                text = catalog.texts[locale].get(key)
                if text is None or record["translation_hash"] != digest(text):
                    raise InvalidCatalog(f"{METADATA}: translation hash mismatch: {locale}:{key}")
    return catalog


@dataclass(frozen=True)
class Token:
    value: str
    string: bool = False


def rust_tokens(source: str) -> list[Token]:
    """Tokenize the small, deliberately literal GUI call contract; skip comments/strings."""
    tokens = []
    offset = 0
    pattern = re.compile(r'\s+|//[^\n]*|/\*|r(\#*)"|"|\'(?:\\.|[^\'\\])\'|[a-zA-Z_][a-zA-Z_0-9]*|::|.', re.DOTALL)
    while offset < len(source):
        match = pattern.match(source, offset)
        assert match is not None
        word = match.group()
        offset = match.end()
        if word.isspace() or word.startswith("//") or word.startswith("'"):
            continue
        if word == "/*":
            depth = 1
            while depth:
                delimiter = re.search(r"/\*|\*/", source[offset:])
                if delimiter is None:
                    raise InvalidCatalog("unterminated Rust block comment")
                depth += 1 if delimiter.group() == "/*" else -1
                offset += delimiter.end()
            continue
        if word == '"' or (word.startswith("r") and word.endswith('"')):
            if word == '"':
                literal = re.match(r'(?:\\.|[^"\\])*"', source[offset:], re.DOTALL)
                if literal is None:
                    raise InvalidCatalog("unterminated Rust string")
                value = literal.group()[:-1]
                offset += literal.end()
            else:
                end = '"' + match.group(1)
                position = source.find(end, offset)
                if position < 0:
                    raise InvalidCatalog("unterminated Rust raw string")
                value = source[offset:position]
                offset = position + len(end)
            tokens.append(Token(value, True))
        else:
            tokens.append(Token(word))
    return tokens


def split_arguments(tokens: list[Token]) -> list[list[Token]]:
    args = [[]]
    stack = []
    for token in tokens:
        if not token.string:
            if token.value in ("(", "[", "{"):
                stack.append(token.value)
            elif token.value in (")", "]", "}"):
                if not stack or stack.pop() != {")": "(", "]": "[", "}": "{"}[token.value]:
                    raise InvalidCatalog("unbalanced i18n call")
            elif token.value == "," and not stack:
                args.append([])
                continue
        args[-1].append(token)
    if stack:
        raise InvalidCatalog("unbalanced i18n arguments")
    if not args[-1]:
        args.pop()
    return args


def literal(tokens: list[Token]) -> str:
    if len(tokens) != 1 or not tokens[0].string:
        raise InvalidCatalog("i18n keys and argument names must be string literals")
    return tokens[0].value


def check_calls(files: dict[str, str], catalog: Catalog) -> None:
    for path, source in files.items():
        if not path.endswith(".rs") or path == "src/i18n.rs":
            continue
        tokens = rust_tokens(source)
        for index, token in enumerate(tokens):
            if token == Token("rust_i18n"):
                raise InvalidCatalog(f"{path}: rust-i18n is private to src/i18n.rs")
            if (
                token == Token("i18n")
                and not (path in {"src/app.rs", "src/main.rs"} or path.startswith("src/app/"))
                and not (path == "src/lib.rs" and index > 0 and tokens[index - 1] == Token("mod"))
            ):
                raise InvalidCatalog(f"{path}: locale/translation state belongs to the GUI boundary")
            if token == Token("i18n") and tokens[index + 1 : index + 2] == [Token("as")]:
                raise InvalidCatalog(f"{path}: do not alias the i18n module")
            if token != Token("i18n") or tokens[index + 1 : index + 2] != [Token("::")]:
                continue
            tail = tokens[index + 2 :]
            if tail and tail[0] in (Token("text"), Token("format"), Token("{"), Token("*")):
                if len(tail) < 2 or tail[1] != Token("("):
                    raise InvalidCatalog(f"{path}: use qualified i18n::text/format calls, not function imports/aliases")
            else:
                continue
            depth = 1
            end = 2
            while end < len(tail) and depth:
                if tail[end] == Token("("):
                    depth += 1
                elif tail[end] == Token(")"):
                    depth -= 1
                end += 1
            if depth:
                raise InvalidCatalog(f"{path}: unterminated i18n call")
            args = split_arguments(tail[2 : end - 1])
            if len(args) != (1 if tail[0].value == "text" else 2):
                raise InvalidCatalog(f"{path}: invalid i18n argument count")
            key = literal(args[0])
            if key not in catalog.english:
                raise InvalidCatalog(f"{path}: undefined English key {key!r}")
            names = []
            if tail[0].value == "format":
                array = args[1]
                if array[:2] != [Token("&"), Token("[")] or array[-1:] != [Token("]")]:
                    raise InvalidCatalog(f"{path}: i18n::format requires a literal &[(name, value)] array")
                for pair in split_arguments(array[2:-1]):
                    if pair[:1] != [Token("(")] or pair[-1:] != [Token(")")]:
                        raise InvalidCatalog(f"{path}: expected (name, value)")
                    parts = split_arguments(pair[1:-1])
                    if len(parts) != 2 or not parts[1]:
                        raise InvalidCatalog(f"{path}: expected (name, value)")
                    names.append(literal(parts[0]))
            if len(names) != len(set(names)) or set(names) != variables(catalog.english[key]):
                raise InvalidCatalog(f"{path}: {key}: call arguments do not match English variables")


def warnings(catalog: Catalog) -> list[str]:
    result = []
    for locale in LOCALES[1:]:
        for key in sorted(catalog.english):
            state = catalog.state(locale, key)
            if state == "invalid_variables":
                raise InvalidCatalog(f"{locale}:{key}: current translation variables do not match English")
            if state != "current":
                result.append(f"{locale}:{key}: {state}; use English fallback")
        for key in sorted(catalog.texts[locale].keys() - catalog.english.keys()):
            result.append(f"{locale}:{key}: removed English key; translation cleanup pending")
    return result


def make_diff(old: Catalog, current: Catalog, locale: str, groups: list[str], base: str | None) -> dict:
    entries = []
    keys = old.english.keys() | current.english.keys() | current.texts[locale].keys()
    for key in sorted(keys):
        group = key.split(".")[0]
        if group not in groups:
            continue
        before = old.english.get(key)
        after = current.english.get(key)
        translation = current.texts[locale].get(key)
        record = current.records.get(locale, {}).get(key)
        reasons = []
        if after is None:
            if before is not None or translation is not None:
                reasons.append("removed")
            if before is None and record is not None:
                before = record["source"]
        else:
            if before is None:
                reasons.append("added")
            elif before != after:
                reasons.append("changed")
                if variables(before) != variables(after):
                    reasons.append("variables_changed")
            state = current.state(locale, key)
            if state != "current":
                reasons.append(state)
            if before == after and record is not None and record["source"] != after:
                before = record["source"]
                if variables(before) != variables(after):
                    reasons.append("variables_changed")
        if reasons:
            entries.append(
                dict(
                    key=key,
                    group=group,
                    reasons=reasons,
                    old_english=before,
                    new_english=after,
                    variables=sorted(variables(after)) if after is not None else [],
                    translation=translation,
                    source_hash=digest(after) if after is not None else None,
                    translated_source_hash=record["source_hash"] if record else None,
                )
            )
    return dict(version=1, base_revision=base, locale=locale, groups=groups, entries=entries)


def changed_keys(before: dict, after: dict) -> set[str]:
    return {key for key in before.keys() | after.keys() if before.get(key) != after.get(key)}


def make_review(catalog: Catalog, locale: str, groups: list[str], keys: list[str], base: str) -> dict:
    """Explicitly select existing, current translations for a one-group review."""
    if (
        len(groups) != 1
        or not isinstance(keys, list)
        or not keys
        or any(not isinstance(key, str) for key in keys)
        or len(keys) != len(set(keys))
    ):
        raise InvalidCatalog("review must select distinct existing keys in one group")
    entries = []
    for key in sorted(keys):
        if key not in catalog.english or key.split(".")[0] != groups[0] or catalog.state(locale, key) != "current":
            raise InvalidCatalog(f"review key must be current and in the selected group: {key}")
        source = catalog.english[key]
        entries.append(
            dict(
                key=key,
                group=groups[0],
                reasons=["review"],
                old_english=source,
                new_english=source,
                variables=sorted(variables(source)),
                translation=catalog.texts[locale][key],
                source_hash=digest(source),
                translated_source_hash=catalog.records[locale][key]["source_hash"],
            )
        )
    return dict(version=1, base_revision=base, locale=locale, groups=groups, review_keys=sorted(keys), entries=entries)


def changed_paths(root: Path, base: str, end: str | None = None) -> set[str]:
    paths = set(git(root, "diff", "--name-only", "--no-renames", "-z", base, *([end] if end else []), "--").split("\0"))
    if end is None:
        paths.update(git(root, "ls-files", "--others", "--exclude-standard", "-z").split("\0"))
    return paths - {""}


def translation_changes(old: Catalog, current: Catalog) -> set[tuple[str, str]]:
    return {
        (locale, key)
        for locale in LOCALES[1:]
        for key in changed_keys(old.texts[locale], current.texts[locale])
        | changed_keys(old.records.get(locale, {}), current.records.get(locale, {}))
    }


def review_source(old: Catalog, current: Catalog) -> Catalog:
    """Review the new English against the PR base's unmodified translations."""
    return Catalog(texts={**old.texts, ENGLISH: current.english}, origins=old.origins, records=old.records)


def review_component(old: Catalog, source: Catalog, locale: str, group: str, keys: list[str], base: str) -> dict:
    task = make_diff(old, source, locale, [group], base)
    if keys:
        reviewed = make_review(source, locale, [group], keys, base)
        task["review_keys"] = reviewed["review_keys"]
        task["entries"] = sorted(task["entries"] + reviewed["entries"], key=lambda entry: entry["key"])
    if not task["entries"]:
        raise InvalidCatalog("empty review component")
    return task


def task_selection(task: dict) -> tuple[str, list[str]]:
    locale = task.get("locale")
    if locale not in LOCALES[1:]:
        raise InvalidCatalog("translation task must select one supported non-English locale")
    groups = task.get("groups")
    if (
        not isinstance(groups, list)
        or not groups
        or not all(isinstance(group, str) for group in groups)
        or len(groups) != len(set(groups))
    ):
        raise InvalidCatalog("translation task must select distinct groups")
    if any(group not in GROUPS for group in groups):
        raise InvalidCatalog("translation task contains unknown groups")
    return locale, groups


def compact_task(task: dict) -> dict:
    """Keep selectors and a canonical content hash in Git; details are reproducible."""
    if type(task.get("version")) is not int or task["version"] not in (1, 2):
        raise InvalidCatalog("only version 1/2 task details can be compacted")
    result = {key: value for key, value in task.items() if key not in ("entries", "tasks")}
    result["version"] = 3
    if task["version"] == 1:
        result["kind"] = "translation"
        result["entries_hash"] = digest(
            json.dumps(task["entries"], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        )
    else:
        result["tasks"] = [compact_task(component) for component in task["tasks"]]
    return result


def expand_task(task: dict | None, base: str, old: Catalog, current: Catalog) -> dict | None:
    """Rebuild version 3 from Git/catalog inputs, never from ignored working files."""
    if not isinstance(task, dict) or type(task.get("version")) is not int or task["version"] != 3:
        return task  # Existing version 1/2 tasks remain valid.
    if task.get("kind") == "translation":
        locale, groups = task_selection(task)
        expected = (
            make_review(old, locale, groups, task["review_keys"], base)
            if "review_keys" in task
            else make_diff(old, old, locale, groups, base)
        )
    elif task.get("kind") == "visual_review":
        components = task.get("tasks")
        if not isinstance(components, list) or not components:
            raise InvalidCatalog("review bundle needs locale/group tasks")
        captured = review_source(old, current)
        expanded = []
        for component in components:
            if not isinstance(component, dict):
                raise InvalidCatalog("invalid review component")
            locale, groups = task_selection(component)
            keys = component.get("review_keys", [])
            if len(groups) != 1 or not isinstance(keys, list):
                raise InvalidCatalog("each review component must select one group and a list of review keys")
            expanded.append(review_component(old, captured, locale, groups[0], keys, base))
        expected = dict(
            version=2,
            kind="visual_review",
            base_revision=base,
            source_paths=task.get("source_paths"),
            tasks=expanded,
        )
    else:
        raise InvalidCatalog("invalid compact task kind")
    if compact_task(expected) != task:
        raise InvalidCatalog("compact translation task does not match its base snapshot/reviewed source; re-extract")
    return expected


def reviewed_source_paths(root: Path, base: str) -> list[dict]:
    before, after = snapshot(root, base), snapshot(root)
    paths = []
    for path in sorted(changed_paths(root, base)):
        if path in (METADATA, TASK) or path.endswith(".md"):
            continue
        if path.startswith("locales/") and Path(path).stem in LOCALES[1:]:
            continue
        english = path.startswith("locales/") and Path(path).stem == ENGLISH and path.endswith(".yml")
        gui = path in {"src/app.rs", "src/i18n.rs"} or (path.startswith("src/app/") and path.endswith(".rs"))
        tooling = path in {
            "scripts/i18n.py",
            "scripts/translate.py",
            "scripts/test_i18n.py",
            "scripts/qa_gui_redesign.py",
        }
        if not (english or gui or tooling):
            raise InvalidCatalog(f"file is outside localization review: {path}")
        # Tool sources are outside the runtime catalog snapshot.
        previous = before.get(path) if path in before else None
        latest = after.get(path) if path in after else None
        if tooling:
            try:
                previous = git(root, "show", f"{base}:{path}")
            except InvalidCatalog:
                previous = None
            latest = (root / path).read_text(encoding="utf-8") if (root / path).is_file() else None
        paths.append(
            dict(
                path=path,
                before_hash=digest(previous) if previous is not None else None,
                after_hash=digest(latest) if latest is not None else None,
            )
        )
    return paths


def check_review_bundle(root: Path, base: str, old: Catalog, current: Catalog, task: dict) -> None:
    if (
        set(task) != {"version", "kind", "base_revision", "source_paths", "tasks"}
        or task.get("kind") != "visual_review"
    ):
        raise InvalidCatalog("invalid visual review bundle")
    if task["base_revision"] != base:
        raise InvalidCatalog("review bundle must match the PR base revision")
    if task["source_paths"] != reviewed_source_paths(root, base):
        raise InvalidCatalog("localization sources changed after review extraction; re-extract the bundle")
    captured = review_source(old, current)
    if not isinstance(task["tasks"], list) or not task["tasks"]:
        raise InvalidCatalog("review bundle needs locale/group tasks")
    allowed = set()
    selected = set()
    for component in task["tasks"]:
        if not isinstance(component, dict) or component.get("locale") not in LOCALES[1:]:
            raise InvalidCatalog("invalid review component locale")
        locale = component["locale"]
        groups = component.get("groups")
        if not isinstance(groups, list) or len(groups) != 1 or groups[0] not in GROUPS:
            raise InvalidCatalog("each review component must select one group")
        if (locale, groups[0]) in selected:
            raise InvalidCatalog("duplicate review locale/group")
        selected.add((locale, groups[0]))
        keys = component.get("review_keys", [])
        if not isinstance(keys, list):
            raise InvalidCatalog("invalid review keys")
        expected = review_component(old, captured, locale, groups[0], keys, base)
        if component != expected:
            raise InvalidCatalog("review component does not match its source snapshot")
        allowed.update((locale, entry["key"]) for entry in expected["entries"])
    for path in changed_paths(root, base):
        translation = path.startswith("locales/") and path.endswith(".yml") and Path(path).stem in LOCALES[1:]
        if translation and (Path(path).stem, Path(path).parts[1]) not in selected:
            raise InvalidCatalog(f"translation file outside the review bundle: {path}")
        if not (
            translation
            or path in (METADATA, TASK)
            or path.endswith(".md")
            or any(item["path"] == path for item in task["source_paths"])
        ):
            raise InvalidCatalog(f"file is outside localization review: {path}")
    for locale, key in sorted(translation_changes(old, current)):
        if (locale, key) not in allowed:
            raise InvalidCatalog(f"translation edit outside the review bundle: {locale}:{key}")
        if key not in current.english:
            if key in current.texts[locale] or key in current.records.get(locale, {}):
                raise InvalidCatalog(f"removed review key must be cleaned: {locale}:{key}")
        elif current.state(locale, key) != "current":
            raise InvalidCatalog(f"review translation needs matching source and variables: {locale}:{key}")


def check_scope(
    root: Path, base: str, old: Catalog, current: Catalog, task: dict | None, *, paths: set[str] | None = None
) -> None:
    task = expand_task(task, base, old, current)
    if isinstance(task, dict) and type(task.get("version")) is int and task["version"] == 2:
        check_review_bundle(root, base, old, current, task)
        return
    translated = translation_changes(old, current)
    paths = changed_paths(root, base) if paths is None else paths
    translation_paths = {path for path in paths if path.startswith("locales/") and Path(path).stem in LOCALES[1:]}
    metadata_changed = METADATA in paths
    # Bootstrap an empty metadata registry in I1 without treating it as a translation edit.
    bootstrap = not old.records and not current.records
    if task is None:
        if translated or translation_paths or (metadata_changed and not bootstrap) or TASK in paths:
            raise InvalidCatalog("feature changes cannot edit other-language catalogs/metadata; use a separate --task")
        return
    if (
        not isinstance(task, dict)
        or type(task.get("version")) is not int
        or task["version"] != 1
        or task.get("locale") not in LOCALES[1:]
    ):
        raise InvalidCatalog("translation task must use version 1 and select one supported non-English locale")
    locale, groups = task_selection(task)
    expected = (
        make_review(old, locale, groups, task["review_keys"], base)
        if "review_keys" in task
        else make_diff(old, old, locale, groups, base)
    )
    if task != expected:
        raise InvalidCatalog("translation task does not match its base snapshot; re-extract before editing")
    allowed = {entry["key"] for entry in expected["entries"]}
    for path in sorted(paths):
        is_translation = path.startswith("locales/") and Path(path).stem == locale and path.endswith(".yml")
        if not (is_translation or path in (METADATA, TASK) or path.endswith(".md")):
            raise InvalidCatalog(f"translation task mixes feature changes: {path}")
    for language, key in sorted(translated):
        if language != locale or key not in allowed:
            raise InvalidCatalog(f"translation edit outside the extracted task: {language}:{key}")
        if key not in current.english:
            if key in current.texts[locale] or key in current.records.get(locale, {}):
                raise InvalidCatalog(f"removed key must be cleaned from catalog and metadata: {locale}:{key}")
        elif current.state(locale, key) != "current":
            raise InvalidCatalog(
                f"updated translation needs current source hash and matching variables: {locale}:{key}"
            )


def export_csv(catalog: Catalog) -> str:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(["key", "group", ENGLISH, *[item for loc in LOCALES[1:] for item in (loc, f"{loc}:status")]])
    keys = catalog.english.keys() | {key for locale in LOCALES[1:] for key in catalog.texts[locale]}
    for key in sorted(keys):
        row = [key, key.split(".")[0], catalog.english.get(key, "")]
        for locale in LOCALES[1:]:
            state = catalog.state(locale, key) if key in catalog.english else "removed"
            row.extend([catalog.texts[locale].get(key, ""), state])
        writer.writerow(row)
    return stream.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check", help="read-only structure, call, freshness and PR scope checks")
    check.add_argument("--base", help="PR base revision; compare the entire working tree, including untracked files")
    check.add_argument("--task", type=Path, help="JSON task extracted before this translation edit; requires --base")
    diff = commands.add_parser("diff", help="JSON translation task; stdout only")
    diff.add_argument("--base", help="English comparison revision; use HEAD for an applicable translation task")
    diff.add_argument("--locale", choices=LOCALES[1:], required=True)
    diff.add_argument("--group", choices=GROUPS, action="append", dest="groups")
    commands.add_parser("export-csv", help="review CSV on stdout (no import or asset mutation)")
    args = parser.parse_args()
    try:
        root = args.root.resolve()
        files = snapshot(root)
        catalog = load_catalog(files)
        check_calls(files, catalog)
        if args.command == "check":
            if args.task and not args.base:
                raise InvalidCatalog("--task requires --base")
            if args.base:
                base = revision(root, args.base)
                old = load_catalog(snapshot(root, base))
                task = read_json(args.task.read_text(encoding="utf-8")) if args.task else None
                check_scope(root, base, old, catalog, task)
            notices = warnings(catalog)
            for notice in notices:
                print(f"warning: {notice}")
            print(f"i18n check passed: {len(catalog.english)} English keys, {len(notices)} translation warnings")
        elif args.command == "diff":
            base = revision(root, args.base) if args.base else None
            old = load_catalog(snapshot(root, base)) if base else Catalog()
            groups = sorted(set(args.groups or GROUPS))
            print(json.dumps(make_diff(old, catalog, args.locale, groups, base), ensure_ascii=False, indent=2))
        else:
            sys.stdout.write(export_csv(catalog))
    except (InvalidCatalog, OSError, ValueError, RecursionError) as error:
        print(f"i18n error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
