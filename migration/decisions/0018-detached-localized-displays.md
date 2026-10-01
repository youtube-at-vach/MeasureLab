# 0018: 同じviewの分離と既存JSONによるQML翻訳

2026-10-01、MIG-007-A。着手HEAD `973c8290`、branch `codex/migration-007-windows-i18n`。
参照・数値・core契約・公開型や技術採用は変更しない。

## 境界

Spectrum/Spectrogramの分離時に別の解析workerや同じ種類のviewを作る必要はない。
[共通wrapper](../../native/qml/PlotPane.qml)で同じQObjectを別Windowへreparentし、
需要token・不変projection・ch/cursor/zoom・表示履歴を維持する。
閉じる操作だけがviewを破棄して需要を解除する。再オープンは通常表示に戻し、新しいtokenで購読する。
最後の需要解除、分離中のBackend再生成・アプリ終了は既存のworker/graph回収境界へ接続する。

GUI文言の正本は製品と同じ`src/assets/lang/*.json`に置き、英語を基準とする。
評価画面の35キーだけをQt propertyからQMLの`tr()`へ渡す。catalogはbinaryへ埋め込むため、
起動に翻訳fileの配置やQMLからのfile読み取り許可を要求しない。翻訳更新後はnativeをrebuildする。
言語は起動時指定のみで、設定移行や動的切替の採用判断は後続に残す。
check/updateの共通source inventoryへQMLを加え、コメント・文字列内の偽tr呼び出しを除外する。

## 検証

[runner](../../scripts/migration_qt_workspace.py)で両Qt方式に元の4/8ch f32/f64入力を通す。
実表示catalog/ラベル/最小サイズ/button幅、4世代の完全result、3画像を要求する。
分離・再接続で同じview/token、単独close後の解析継続、最後のclose後の回収、
再オープン/旧世代拒否、分離中のBackend再生成/終了を実操作で検査する。
PNGの検査領域はQtの実Canvas座標を記録する。長い翻訳でpanel位置が変わっても細いpeakを見落とさず、
領域外・重複領域・破損PNG・描画なしを拒否する。

現在のPython GUIは翻訳JSONの追加以外変更しない。renderer spikeの既存SpectrumViewには英語catalogを渡す。
依存版、Cargo.lock、元fixture、数値許容差、音声callback/取得coreは不変。
最終結果・負荷がある実入力回帰の失敗を[status](../status.md)に記録する。

## 未確認

このwrapperは製品のDetachable Wrapperや機能能力宣言の移植ではない。
Qt SDK/offscreen/software/Basicの結果であり、実window manager/focus/minimize・他OS/font/DPI・配布は未確認。
AC08のtrigger表示、校正/製品保存UI、AC15/16、007-A全体/008と技術採用を完了にしない。
