from pathlib import Path

import pytest

from src.core import vst_discovery


@pytest.mark.parametrize(
    ("platform", "expected"),
    [
        (
            "darwin",
            ["~/Library/Audio/Plug-Ins/VST3", "/Library/Audio/Plug-Ins/VST3", "/Network/Library/Audio/Plug-Ins/VST3"],
        ),
        ("linux", ["~/.vst3", "/usr/lib64/vst3", "/usr/lib/vst3", "/usr/local/lib64/vst3", "/usr/local/lib/vst3"]),
        ("win32", ["/local/Programs/Common/VST3", "/common/VST3"]),
        ("unknown", []),
    ],
)
def test_standard_locations(monkeypatch, platform, expected):
    monkeypatch.setattr(vst_discovery.sys, "platform", platform)
    monkeypatch.setenv("LOCALAPPDATA", "/local")
    monkeypatch.setenv("CommonProgramFiles", "/common")
    assert vst_discovery.vst3_search_paths() == [Path(path).expanduser() for path in expected]


def test_windows_fallback_locations(monkeypatch):
    monkeypatch.setattr(vst_discovery.sys, "platform", "win32")
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.delenv("CommonProgramFiles", raising=False)
    monkeypatch.setenv("ProgramFiles", "D:/Applications")
    assert vst_discovery.vst3_search_paths() == [
        Path.home() / "AppData/Local/Programs/Common/VST3",
        Path("D:/Applications/Common Files/VST3"),
    ]


def test_recursive_discovery_stops_at_bundle_and_keeps_distinct_same_names(tmp_path):
    bundle = tmp_path / "Vendor/Effect.vst3"
    bundle.mkdir(parents=True)
    (bundle / "internal.vst3").touch()
    other = tmp_path / "Other/Effect.vst3"
    other.parent.mkdir()
    other.touch()
    upper = tmp_path / "A.VST3"
    upper.touch()
    (tmp_path / "ignore.vst").touch()
    result = vst_discovery.discover_vst3([tmp_path, tmp_path / "missing", tmp_path])
    assert result.paths == [upper, other, bundle]
    assert result.errors == []


def test_symlinks_are_followed_without_duplicates_or_cycles(tmp_path):
    root = tmp_path / "scan"
    root.mkdir()
    vendor = tmp_path / "external"
    vendor.mkdir()
    plugin = vendor / "Effect.vst3"
    plugin.mkdir()
    try:
        (root / "vendor").symlink_to(vendor, target_is_directory=True)
        (vendor / "loop").symlink_to(root, target_is_directory=True)
        (root / "broken.vst3").symlink_to(tmp_path / "missing")
        (root / "alias.vst3").symlink_to(plugin, target_is_directory=True)
    except OSError:
        pytest.skip("Symlinks are unavailable")
    result = vst_discovery.discover_vst3([root, vendor])
    assert len(result.paths) == 1
    assert result.paths[0].resolve() == plugin
    assert not result.errors


def test_inaccessible_folder_does_not_stop_scan(tmp_path, monkeypatch):
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    plugin = tmp_path / "Good.vst3"
    plugin.touch()
    original = Path.iterdir

    def iterdir(path):
        if path == blocked:
            raise PermissionError("denied")
        return original(path)

    monkeypatch.setattr(Path, "iterdir", iterdir)
    result = vst_discovery.discover_vst3([tmp_path])
    assert result.paths == [plugin]
    assert len(result.errors) == 1
    assert "denied" in result.errors[0]


def test_cancelled_scan(tmp_path):
    assert vst_discovery.discover_vst3([tmp_path], cancelled=lambda: True).paths == []
