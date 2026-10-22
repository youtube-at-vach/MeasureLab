# Bundled GUI font

`NotoSansCJK-Regular.ttc` is the unmodified Regular OpenType collection from
[Noto Sans CJK 2.004](https://github.com/notofonts/noto-cjk/tree/Sans2.004/Sans/OTC).
It is distributed under the SIL Open Font License 1.1 in [OFL.txt](OFL.txt).
The license and copyright notice are also embedded in the collection.

The GUI appends the font to egui's proportional and monospace fallbacks. The JP
face (index 0), KR face (1), or SC face (2) supplies regional CJK glyphs; existing
egui fonts keep their priority for Latin, Cyrillic, symbols, and numeric readings.
The collection and license are embedded in the executable; no system font or
runtime download is required. Help exposes the copyright notice and license.

SHA-256 of the unmodified collection:
`b76b0433203017ca80401b2ee0dd69350349871c4b19d504c34dbdd80541690a`.
