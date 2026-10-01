"""Reject untranslated/clipped windows and incomplete detached lifecycle evidence."""

import json
from pathlib import Path

import pytest

from scripts import migration_qt_workspace as workspace
from scripts.translation_utils import extract_qml_tr_keys, extract_tr_keys, translation_source_files


def test_qml_keys_ignore_comments_strings_and_nonliteral_calls(tmp_path):
    text = """
    // tr("comment")
    /* tr('block comment') */
    property string explanation: "tr(\\"embedded string\\")"
    Label { text: tr("actual") }
    Label { text: view.tr('also actual') }
    Label { text: qsTr("Qt catalog") }
    function tr(key) { return messages[key]; }
    """
    assert extract_qml_tr_keys(text) == {"actual", "also actual"}
    path = tmp_path / "Example.qml"
    path.write_text(text)
    assert extract_tr_keys(path) == {"actual", "also actual"}


def test_qml_keys_included_in_check_and_update_inventory():
    paths = translation_source_files()
    for name in ("Display.qml", "PlotPane.qml", "SpectrumView.qml", "TriggerPanel.qml"):
        assert workspace.ROOT / "native/qml" / name in paths
    english = json.loads((workspace.ROOT / "src/assets/lang/en.json").read_text())
    used = set().union(*(extract_tr_keys(p) for p in paths if p.suffix == ".qml"))
    expected = {k for k in english if k.startswith(workspace.PREFIX)}
    assert used == expected and len(used) == 48
    for language in workspace.LANGUAGES:
        local = json.loads((workspace.ROOT / f"src/assets/lang/{language}.json").read_text())
        assert all(
            local[k]
            and {i: local[k].count(f"%{i}") for i in range(1, 5)} == {i: english[k].count(f"%{i}") for i in range(1, 5)}
            for k in used
        )


def record(language="ja"):
    catalog = {
        k: v
        for k, v in json.loads((workspace.ROOT / f"src/assets/lang/{language}.json").read_text()).items()
        if k.startswith(workspace.PREFIX)
    }
    body = {
        **dict.fromkeys(workspace.LIFECYCLE, True),
        "language": language,
        "catalog": catalog,
        "main": {"title": catalog[workspace.PREFIX + "title"], "minimum": [900, 540], "size": [1000, 640]},
    }
    for kind in ("spectrum", "spectrogram"):
        body[kind] = {
            "title": catalog[workspace.PREFIX + kind],
            "minimum": [400, 280],
            "size": [600, 450],
            "buttons_fit": True,
            "regions": {"spectrum": [52, 60, 536, 300], "spectrogram": [52, 60, 536, 300]},
            "labels": {
                "heading": catalog[workspace.PREFIX + kind],
                "reset": catalog[workspace.PREFIX + "reset_zoom"],
                "detach": catalog[workspace.PREFIX + "dock"],
                "save": catalog[workspace.PREFIX + "save_image"],
            },
        }
    return body


def output(body):
    return "DISPLAY_LANGUAGE ja\nqml: DISPLAY_WORKSPACE " + json.dumps(body, ensure_ascii=False) + "\n"


@pytest.mark.parametrize(
    "mutation",
    [
        "language",
        "catalog",
        "title",
        "label",
        "clipping",
        "width",
        "height",
        "undersized",
        "noninteger",
        "repeated",
        *workspace.LIFECYCLE,
    ],
)
def test_invalid_workspace_metadata_rejected_before_images(tmp_path, mutation):
    body = record()
    if mutation == "language":
        body["language"] = "en"
    elif mutation == "catalog":
        body["catalog"][workspace.PREFIX + "title"] = "untranslated title"
    elif mutation == "title":
        body["spectrum"]["title"] = "Spectrum"
    elif mutation == "label":
        body["spectrum"]["labels"]["reset"] = "Reset zoom"
    elif mutation == "clipping":
        body["spectrum"]["buttons_fit"] = False
    elif mutation == "width":
        body["main"]["minimum"][0] = 1181
    elif mutation == "height":
        body["main"]["minimum"][1] = 691
    elif mutation == "undersized":
        body["main"]["size"][0] = 800
    elif mutation == "noninteger":
        body["main"]["minimum"][0] = True
    elif mutation != "repeated":
        body[mutation] = False
    text = output(body)
    if mutation == "repeated":
        text += text
    with pytest.raises(workspace.fft.ReferenceError):
        workspace.validate_workspace(text, "ja", tmp_path / "display.png")


def test_valid_metadata_requires_each_detached_png(tmp_path, monkeypatch):
    image = tmp_path / "display.png"
    with pytest.raises(FileNotFoundError):
        workspace.validate_workspace(output(record()), "ja", image)
    inspected = []

    def inspect(path, **kwargs):
        inspected.append((path, kwargs))
        return {"sha256": "inspected"}

    monkeypatch.setattr(workspace, "inspect_png", inspect)
    workspace.validate_workspace(output(record()), "ja", image)
    assert inspected == [
        (
            Path(str(image) + f".{kind}.png"),
            {
                "size": [600, 450],
                "kind": kind,
                "regions": {"spectrum": [52, 60, 536, 300], "spectrogram": [52, 60, 536, 300]},
            },
        )
        for kind in ("spectrum", "spectrogram")
    ]
