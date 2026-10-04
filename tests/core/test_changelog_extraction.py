import pytest

from misc.extract_changelog import extract_changelog


@pytest.mark.parametrize("version", ["v0.9.1", "0.9.1"])
@pytest.mark.parametrize("heading", ["[v0.9.1] - 2026-10-04", "v0.9.1", "[0.9.1]", "0.9.1 - 2026-10-04"])
def test_release_notes_preserve_final_release_notice(tmp_path, version, heading):
    notice = "### Final Python Release\n\n* v0.9.1 is the final Python release.\n\n### Added\n\n* New layout."
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(f"# Changelog\n\n## {heading}\n\n{notice}\n\n## [v0.9.0]\n\n* Previous release.\n")

    assert extract_changelog(version, changelog) == notice


def test_release_notes_fallback_only_matches_heading_lines(tmp_path):
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("## Release v0.9.1 (final)\n\n* v0.9.1 is the final Python release.\n\n## v0.9.0\n\n* Old.\n")

    assert extract_changelog("v0.9.1", changelog) == "* v0.9.1 is the final Python release."


def test_release_notes_do_not_match_longer_version(tmp_path):
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("## [v0.9.10]\n\n* Different release.\n")

    assert extract_changelog("v0.9.1", changelog) is None
