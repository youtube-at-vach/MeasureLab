"""Catalog safety, deferred translation freshness, and read-only PR task validation."""

import csv
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

from i18n import (
    ENGLISH,
    METADATA,
    Catalog,
    InvalidCatalog,
    check_calls,
    check_scope,
    digest,
    export_csv,
    git,
    load_catalog,
    make_diff,
    revision,
    snapshot,
    warnings,
)


def catalog_files(english=None, translation=None, source=None):
    english = {"common.ready": "Ready"} if english is None else english
    files = {"locales/common/en-US.yml": yaml.safe_dump({"_version": 1, **english}, allow_unicode=True)}
    if translation is not None:
        files["locales/common/ja.yml"] = yaml.safe_dump({"_version": 1, **translation}, allow_unicode=True)
    if source is not None:
        records = {
            key: dict(source=text, source_hash=digest(text), translation_hash=digest(translation[key]))
            for key, text in source.items()
        }
        files[METADATA] = json.dumps(dict(version=1, translations=dict(ja=records)), ensure_ascii=False)
    return files


class CatalogTests(unittest.TestCase):
    def test_nested_and_dotted_keys_merge_by_locale_and_keep_explicit_namespace(self):
        files = catalog_files()
        files["locales/io/en-US.yml"] = "_version: 1\nio:\n  start: Start input\n"
        files["locales/common/ja.yml"] = "_version: 1\ncommon:\n  ready: 準備完了\n"
        catalog = load_catalog(files)
        self.assertEqual(catalog.english, {"common.ready": "Ready", "io.start": "Start input"})
        self.assertEqual(catalog.texts["ja"], {"common.ready": "準備完了"})
        self.assertEqual(catalog.state("ja", "common.ready"), "unreviewed")

    def test_bad_yaml_types_duplicates_paths_and_namespaces_are_errors(self):
        bad = [
            "_version: 1\ncommon.ready: First\ncommon.ready: Second\n",
            "_version: 1\ncommon:\n  ready: First\ncommon.ready: Second\n",
            "_version: 1\ncommon.ready: true\n",
            "_version: 1\ncommon.ready: 42\n",
            "_version: 1\ncommon.ready: null\n",
            "_version: 1\ncommon.ready: [Ready]\n",
            "_version: 1\ncommon.ready: ''\n",
            "_version: true\ncommon.ready: Ready\n",
            "_version: '1'\ncommon.ready: Ready\n",
            "_version: 2\ncommon.ready: Ready\n",
            "_version: 1\nready: Ready\n",
            "_version: 1\nunknown: {}\n",
            "_version: 1\ncommon..ready: Ready\n",
            "_version: 1\ncommon.ready: Ready\ncommon.ready.extra: More\n",
            "_version: 1\ncommon: {ready: [\n",
            "_version: 1\ncommon.ready: 'Hello %{bad-name}'\n",
            "_version: 1\ncommon.ready: !unknown Ready\n",
            "_version: 1\ncommon.ready: &x Ready\ncommon: {<<: *x}\n",
            "_version: 1\ncommon: {ready: Ready, ready: Other}\n",
            "_version: 1\n0: Ready\n",
            "- Ready\n",
            "",
        ]
        for source in bad:
            with self.subTest(source=source), self.assertRaises(InvalidCatalog):
                load_catalog({"locales/common/en-US.yml": source})
        for path in ("locales/common/en.yml", "locales/common/en-US.yaml", "locales/en-US.yml"):
            with self.subTest(path=path), self.assertRaises(InvalidCatalog):
                load_catalog({path: "_version: 1\ncommon.ready: Ready\n"})

    def test_cross_file_final_duplicates_and_prefix_collisions_are_errors(self):
        for source in ("common.ready: Other", "common.ready.detail: Other", "common.ready: {}"):
            files = catalog_files()
            files["locales/io/en-US.yml"] = "_version: 1\n" + source
            with self.subTest(source=source), self.assertRaises(InvalidCatalog):
                load_catalog(files)

    def test_empty_translation_and_stale_variable_mismatch_only_warn(self):
        files = catalog_files({"common.ready": "Ready %{name}"}, {"common.ready": ""})
        self.assertEqual(load_catalog(files).state("ja", "common.ready"), "missing")
        files = catalog_files(
            {"common.ready": "Ready %{new_name}"},
            {"common.ready": "準備完了 %{old_name}"},
            {"common.ready": "Ready %{old_name}"},
        )
        catalog = load_catalog(files)
        self.assertEqual(catalog.state("ja", "common.ready"), "stale")
        self.assertIn("ja:common.ready: stale; use English fallback", warnings(catalog))

    def test_identical_technical_term_is_a_valid_translation(self):
        catalog = load_catalog(catalog_files({"common.ready": "FFT"}, {"common.ready": "FFT"}, {"common.ready": "FFT"}))
        self.assertEqual(catalog.state("ja", "common.ready"), "current")

    def test_current_translation_with_wrong_variables_is_an_error(self):
        files = catalog_files(
            {"common.ready": "Ready %{name}"}, {"common.ready": "準備完了 %{other}"}, {"common.ready": "Ready %{name}"}
        )
        with self.assertRaisesRegex(InvalidCatalog, "variables"):
            warnings(load_catalog(files))

    def test_metadata_corruption_or_translation_edit_without_hash_update_is_an_error(self):
        files = catalog_files(translation={"common.ready": "準備完了"}, source={"common.ready": "Ready"})
        for record in (
            dict(source="Other", source_hash=digest("Ready"), translation_hash=digest("準備完了")),
            dict(source="Ready", source_hash=digest("Ready"), translation_hash=digest("Other")),
            dict(source="Ready", source_hash=digest("Ready")),
        ):
            with self.subTest(record=record), self.assertRaises(InvalidCatalog):
                load_catalog(
                    {**files, METADATA: json.dumps(dict(version=1, translations=dict(ja={"common.ready": record})))}
                )
        for source in ('{"version":1,"version":1,"translations":{}}', '{"version":true,"translations":{}}'):
            with self.subTest(source=source), self.assertRaises(InvalidCatalog):
                load_catalog({**files, METADATA: source})

    def test_non_english_structure_and_duplicates_are_also_errors(self):
        for source in (
            "_version: 1\ncommon.ready: 42\n",
            "_version: 1\ncommon.ready: 一\ncommon.ready: 二\n",
        ):
            with self.subTest(source=source), self.assertRaises(InvalidCatalog):
                load_catalog({**catalog_files(), "locales/common/ja.yml": source})

    def test_csv_round_trip_preserves_quotes_newlines_unicode_and_states(self):
        english = {"common.z": 'Line 1, "quoted"\nLine 2', "common.a": "FFT"}
        catalog = load_catalog(catalog_files(english, {"common.z": "日本語\n第二行"}))
        rows = list(csv.DictReader(io.StringIO(export_csv(catalog))))
        self.assertEqual([row["key"] for row in rows], ["common.a", "common.z"])
        self.assertEqual(rows[1][ENGLISH], english["common.z"])
        self.assertEqual(rows[1]["ja"], "日本語\n第二行")
        self.assertEqual(rows[1]["ja:status"], "unreviewed")
        self.assertEqual(rows[0]["ja:status"], "missing")


class CallTests(unittest.TestCase):
    def setUp(self):
        self.catalog = load_catalog(catalog_files({"common.ready": "Ready", "common.greet": "Hello %{name}"}))

    def check_source(self, source):
        check_calls({"src/app.rs": source}, self.catalog)

    def test_literal_keys_and_named_arguments_are_checked(self):
        self.check_source('i18n::text("common.ready");')
        self.check_source('crate::i18n::format("common.greet", &[("name", value),]);')
        self.check_source('i18n::format(r#"common.greet"#, &[("name", f(a, b)),]);')
        for source in (
            'i18n::text("missing.key")',
            'i18n::text("common.greet")',
            'i18n::format("common.greet", &[("other", value)])',
            'i18n::format("common.greet", &[("name", a), ("name", b)])',
            'i18n::format("common.ready", &[("extra", value)])',
            'i18n::format("common.greet", args)',
            "i18n::text(key)",
            'i18n::text(concat!("common", ".ready"))',
            "use crate::i18n::text as t;",
            "use crate::i18n::{text, format};",
            "use crate::i18n::*;",
            'use crate::i18n as tr; tr::text("missing.key")',
        ):
            with self.subTest(source=source), self.assertRaises(InvalidCatalog):
                self.check_source(source)

    def test_comments_normal_and_raw_strings_do_not_create_false_calls(self):
        self.check_source(
            '// i18n::text("missing.key")\n'
            '/* i18n::text("missing.key"); /* nested */ */\n'
            'let s = "i18n::text(\\"missing.key\\")";\n'
            'let s = r###"i18n::text("missing.key")"###;\n'
            "fn f<'a>(s: &'a str) { let c = '('; }\n"
        )


class DiffTests(unittest.TestCase):
    def test_added_changed_variables_removed_and_file_move(self):
        old = load_catalog(catalog_files({"common.ready": "Ready %{old}", "common.removed": "Gone"}))
        files = catalog_files({"common.ready": "Ready %{new}", "common.added": "Added"})
        current = load_catalog(files)
        task = make_diff(old, current, "ja", ["common"], "base")
        entries = {entry["key"]: entry for entry in task["entries"]}
        self.assertIn("added", entries["common.added"]["reasons"])
        self.assertIn("changed", entries["common.ready"]["reasons"])
        self.assertIn("variables_changed", entries["common.ready"]["reasons"])
        self.assertEqual(entries["common.removed"]["reasons"], ["removed"])
        self.assertEqual(entries["common.ready"]["variables"], ["new"])
        moved = {"locales/io/en-US.yml": files["locales/common/en-US.yml"]}
        self.assertEqual(task, make_diff(old, load_catalog(moved), "ja", ["common"], "base"))

    def test_source_text_change_without_variable_change_is_included(self):
        old = load_catalog(catalog_files())
        new = load_catalog(catalog_files({"common.ready": "Ready to acquire"}))
        entry = make_diff(old, new, "ja", ["common"], "base")["entries"][0]
        self.assertIn("changed", entry["reasons"])
        self.assertNotIn("variables_changed", entry["reasons"])

    def test_deferred_translation_survives_later_feature_prs(self):
        current = load_catalog(
            catalog_files({"common.ready": "New English"}, {"common.ready": "準備完了"}, {"common.ready": "Ready"})
        )
        # The last feature PR is already the base: only persistent metadata reveals staleness.
        entry = make_diff(current, current, "ja", ["common"], "later-base")["entries"][0]
        self.assertEqual(entry["old_english"], "Ready")
        self.assertEqual(entry["new_english"], "New English")
        self.assertEqual(entry["reasons"], ["stale"])
        self.assertEqual(entry["source_hash"], digest("New English"))
        self.assertEqual(entry["translated_source_hash"], digest("Ready"))

    def test_initial_translation_only_emits_missing_or_unreviewed_keys_in_selected_group(self):
        catalog = load_catalog(catalog_files({"common.ready": "Ready", "io.start": "Start"}))
        task = make_diff(catalog, catalog, "ja", ["common"], "base")
        self.assertEqual([entry["key"] for entry in task["entries"]], ["common.ready"])
        self.assertEqual(task["entries"][0]["reasons"], ["missing"])
        self.assertEqual(make_diff(Catalog(), Catalog(), "ja", ["common"], None)["entries"], [])


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        git(self.root, "init", "-q")
        git(self.root, "config", "user.email", "i18n-test@example.invalid")
        git(self.root, "config", "user.name", "i18n test")
        self.write(catalog_files({"common.ready": "Ready", "common.other": "Other"}))
        self.commit()

    def write(self, files):
        for name, text in files.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")

    def commit(self):
        git(self.root, "add", ".")
        git(self.root, "commit", "-qm", "fixture")

    def catalogs(self):
        base = revision(self.root, "HEAD")
        old = load_catalog(snapshot(self.root, base))
        current = load_catalog(snapshot(self.root))
        return base, old, current

    def translate(self, key="common.ready", source="Ready", text="準備完了"):
        self.write(catalog_files({"common.ready": "Ready", "common.other": "Other"}, {key: text}, {key: source}))

    def task(self):
        base, old, _ = self.catalogs()
        return make_diff(old, old, "ja", ["common"], base)

    def test_feature_pr_can_change_only_english_while_missing_translations_warn(self):
        self.write(catalog_files({"common.ready": "New English"}))
        check_scope(self.root, *self.catalogs(), None)
        self.assertTrue(warnings(self.catalogs()[2]))

    def test_feature_pr_cannot_edit_untracked_translations_or_metadata(self):
        self.translate()
        with self.assertRaisesRegex(InvalidCatalog, "separate --task"):
            check_scope(self.root, *self.catalogs(), None)
        self.commit()
        self.translate(text="変更")
        with self.assertRaisesRegex(InvalidCatalog, "separate --task"):
            check_scope(self.root, *self.catalogs(), None)

    def test_translation_task_accepts_current_hash_and_partial_completion(self):
        task = self.task()
        self.translate()
        check_scope(self.root, *self.catalogs(), task)
        # The other key can remain missing; no automatic English fill is needed.
        self.assertEqual(self.catalogs()[2].state("ja", "common.other"), "missing")

    def test_outside_group_or_already_current_key_is_rejected(self):
        self.translate()
        self.commit()
        task = self.task()
        self.translate(text="変更")
        with self.assertRaisesRegex(InvalidCatalog, "outside"):
            check_scope(self.root, *self.catalogs(), task)

    def test_changed_source_task_and_feature_edits_are_rejected(self):
        task = self.task()
        self.translate()
        self.write({"src/app.rs": "fn main() {}"})
        with self.assertRaisesRegex(InvalidCatalog, "mixes feature"):
            check_scope(self.root, *self.catalogs(), task)
        (self.root / "src/app.rs").unlink()
        task["entries"][0]["source_hash"] = digest("Old source")
        with self.assertRaisesRegex(InvalidCatalog, "base snapshot"):
            check_scope(self.root, *self.catalogs(), task)

    def test_other_locale_and_outside_group_edits_are_rejected(self):
        task = self.task()
        self.translate()
        self.write({"locales/common/fr.yml": "_version: 1\ncommon.ready: Prêt\n"})
        with self.assertRaisesRegex(InvalidCatalog, "mixes feature"):
            check_scope(self.root, *self.catalogs(), task)
        (self.root / "locales/common/fr.yml").unlink()
        task["groups"] = ["io"]
        task["entries"] = []
        with self.assertRaisesRegex(InvalidCatalog, "outside"):
            check_scope(self.root, *self.catalogs(), task)

    def test_feature_pr_cannot_refresh_only_nonempty_metadata(self):
        self.translate()
        self.commit()
        self.write(catalog_files({"common.ready": "Ready!", "common.other": "Other"}))
        self.commit()
        self.write(
            catalog_files(
                {"common.ready": "Ready!", "common.other": "Other"},
                {"common.ready": "準備完了"},
                {"common.ready": "Ready!"},
            )
        )
        with self.assertRaisesRegex(InvalidCatalog, "separate --task"):
            check_scope(self.root, *self.catalogs(), None)

    def test_invalid_task_shape_or_hand_expanded_allowlist_is_rejected(self):
        self.translate()
        for task in (
            [],
            {"locale": "en-US"},
            {"locale": "ja", "groups": [{}]},
            {**self.task(), "groups": []},
            {**self.task(), "version": True},
        ):
            with self.subTest(task=task), self.assertRaises(InvalidCatalog):
                check_scope(self.root, *self.catalogs(), task)
        task = self.task()
        task["entries"].append({**task["entries"][0], "key": "io.extra"})
        with self.assertRaisesRegex(InvalidCatalog, "base snapshot"):
            check_scope(self.root, *self.catalogs(), task)

    def test_task_extracted_before_a_new_english_commit_is_rejected(self):
        task = self.task()
        self.write(catalog_files({"common.ready": "Changed", "common.other": "Other"}))
        self.commit()
        self.translate(source="Changed")
        with self.assertRaisesRegex(InvalidCatalog, "base snapshot"):
            check_scope(self.root, *self.catalogs(), task)

    def test_new_translation_needs_matching_variables_and_current_source_metadata(self):
        task = self.task()
        for source, text in (("Old", "準備完了"), ("Ready", "準備完了 %{unexpected}")):
            self.translate(source=source, text=text)
            with self.subTest(source=source), self.assertRaisesRegex(InvalidCatalog, "current source hash"):
                check_scope(self.root, *self.catalogs(), task)

    def test_removed_english_key_is_cleanup_only_and_persists_across_prs(self):
        self.translate()
        self.commit()
        self.write({"locales/common/en-US.yml": "_version: 1\ncommon.other: Other\n"})
        self.commit()
        task = self.task()
        self.assertEqual(task["entries"][1]["reasons"], ["removed"])
        self.assertEqual(task["entries"][1]["old_english"], "Ready")
        self.write({"locales/common/ja.yml": "_version: 1\ncommon: {}\n", METADATA: '{"version":1,"translations":{}}'})
        check_scope(self.root, *self.catalogs(), task)

    def test_stale_same_term_can_be_reviewed_by_updating_only_metadata(self):
        self.translate()
        self.commit()
        self.write(catalog_files({"common.ready": "Ready!", "common.other": "Other"}))
        self.commit()
        task = self.task()
        self.write(
            catalog_files(
                {"common.ready": "Ready!", "common.other": "Other"},
                {"common.ready": "準備完了"},
                {"common.ready": "Ready!"},
            )
        )
        check_scope(self.root, *self.catalogs(), task)

    def test_cli_is_read_only_and_invalid_base_or_task_fails_closed(self):
        script = str(Path(__file__).with_name("i18n.py"))
        before = snapshot(self.root)
        for args, success in (
            (["check", "--base", "HEAD"], True),
            (["diff", "--base", "HEAD", "--locale", "ja", "--group", "common"], True),
            (["export-csv"], True),
            (["check", "--base", "no-such-ref"], False),
            (["check", "--task", "missing.json"], False),
        ):
            result = subprocess.run(  # noqa: S603 - local script and fixed test arguments
                [sys.executable, script, "--root", str(self.root), *args], capture_output=True, text=True, check=False
            )
            with self.subTest(args=args):
                self.assertEqual(result.returncode == 0, success, result.stderr)
        self.assertEqual(snapshot(self.root), before)

    def test_cli_accepts_committed_task_file_and_uses_entire_pr_diff_after_commit(self):
        task = self.task()
        self.write({"i18n/translation-task.json": json.dumps(task)})
        self.translate()
        self.commit()
        script = str(Path(__file__).with_name("i18n.py"))
        result = subprocess.run(  # noqa: S603 - local script and fixed test arguments
            [
                sys.executable,
                script,
                "--root",
                str(self.root),
                "check",
                "--base",
                task["base_revision"],
                "--task",
                str(self.root / "i18n/translation-task.json"),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_metadata_on_an_updated_translation_is_rejected(self):
        task = self.task()
        self.write(catalog_files({"common.ready": "Ready", "common.other": "Other"}, {"common.ready": "準備完了"}))
        with self.assertRaisesRegex(InvalidCatalog, "current source hash"):
            check_scope(self.root, *self.catalogs(), task)


if __name__ == "__main__":
    unittest.main()
