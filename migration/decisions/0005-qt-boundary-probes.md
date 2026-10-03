# 0005: Qt SDKと共通GUI境界プローブ

日付: 2026-09-30。MIG-004-A。Rust/QMLや接続方式の採用は未決定。
この決定は評価環境・比較用の実装境界を固定する。[作業票](../tasks.md)と[起動手順](../../native/qt-probe.md)を参照。

## SDKと公式要件

Qt 6.11.2の開発SDKを`.tools/qt/6.11.2/macos/`へ分離導入する。
aqtinstall 3.3.0でQt配布repositoryのqtbase/declarative/tools/svg/translationsを取得した。
`qmake`、headers/private headers、moc、QML tools、frameworksを開発SDKから使う。
Python参照版のPyQt runtimeとSDKの探索パスを混在させない。
[導入記録](../qt/2026-09-30-intel-sdk.json)に配布metadata、アーカイブのhash、導入版、compiler/Apple SDKを保存する。

[Qt 6.11のmacOS公式要件](https://doc.qt.io/qt-6/macos.html)はXcode 15/macOS 14 SDK以上と実行先macOS 13以上。
このhostはmacOS 14.8.9/Intel、Command Line ToolsのApple Clang 16/SDK 15.2でコンパイル・リンク・実行した。
full Xcodeは未導入なので、公式の開発環境構成への適合を確認したという意味にはしない。
[CXX-Qtの要件](https://kdab.github.io/cxx-qt/book/getting-started/index.html)はC++、CMake 3.24以上、Rust、Qtとqmake。
[Qt Bridge 0.3の固定README](https://github.com/qt/qtbridge-rust/blob/d9a89bc1767a444f280e0548edddbd5b2023104c/crates/qtbridge/README.md)は
Rust 1.88以上、Qt 6.10以上、private headersを要求し、macOSはarm64 experimentalと記載する。
Intelの成功はこのhostの実測として残す。未掲載構成の一般的なサポート保証とは扱わない。

Rust 1.98.1、CXX-Qt 0.10.0、Qt Bridge 0.3.0、CXX 1.0.202とCargo.lockを固定する。
最初にCXX 1.0.194を指定した際、解決されたcxx-gen 0.7.202が異なるbridge symbolを生成してリンクが失敗した。
CXXを生成器と同系列に揃え、期待値やSDKを変更せずに再ビルドした。
この失敗は接続方式の数値・状態契約の不合格とは別に扱う。
公式の[Qt Bridge 0.3発表](https://www.qt.io/blog/qt-bridge-for-rust-0.3-cxx-qt-compatibility-and-soundness)も
CXX-Qtとの共通基盤とビルド時間の増加を説明する。今回は時間比較の結論を出さない。

## 同じ境界を通す

両案が同じ[QML](../../native/qml/Main.qml)と[probe-core](../../native/probe-core/src/lib.rs)を使う。
probe-coreは音声やDSPを持たない、5 ms間隔の模擬workerと容量1の表示mailboxである。
Qt adapterはGUI threadで2行のlist modelと状態・世代・結果番号を更新する。
固定DAG、FFT共有、実SignalBlock、Timebase、履歴、校正・保存は実装していない。

| 比較点 | CXX-Qt 0.10.0 | Qt Bridge 0.3.0 |
| --- | --- | --- |
| Qt側型の宣言 | `cxx_qt::bridge`、RustQt/foreign type、qproperty/qinvokable | `qobject`、qproperty/qslot。公開は同じQML URI |
| GUI objectの変更 | `Pin<&mut QObject>`と`CxxQtType` | `Rc<RefCell<T>>`をbridgeが管理。callback中のborrowに制約 |
| worker通知 | 型を指定した`CxxQtThread::queue`のclosure | `QmlMethodInvoker`とslot名・QVariant引数。動的な型変換がある |
| list model | QAbstractListModel継承、role/data/rowCount、balanced resetを明示 | QListModel traitと通知付きmutation API |
| 寿命 | Qt objectのRust fieldがProbeを保持。破棄時にcancel/join | bridge registryとQML参照がRust objectを保持。GC/engine破棄後の回収を検査 |
| QMLのみの変更 | 同じ外部QMLを読込む。埋込み・再リンクは行わない | 同左 |
| このIntel hostの結果 | 共通シナリオ合格 | 共通シナリオ合格。公式READMEのIntel記載はない |

公開型、型変換やunsafe境界は最終ABIではない。GUIに渡す整数はこの短い試験の世代・結果番号だけで、
QML numberでの大きなsample位置や64-bit IDの精度を証明しない。
共有libを使う両案に同じ不具合が含まれる可能性も残す。

## 合否と残る範囲

[runner](../../scripts/migration_qt_probe.py)は同じQMLへStart/Stop、準備中cancel、開始失敗、重複要求、
list model通知、160 ms GUI停止、通知集約、旧世代拒否、Backend破棄・再生成を通す。
2view+模擬保存sessionから順にtokenを解除し、残る需要への供給と最後の解除による停止を確認する。
共有view windowを破棄・再生成した後、running中のアプリ終了でもworker/modelが0になることを要求する。
終了コードだけでは合格にせず、全シナリオとengine破棄のmarkerも検査する。

同じ模擬workerでQt境界のAC07/13に対応する経路を検証する。
AC07全体のAnalysis Graph node/cache/in-flight result回収は006-B、
AC13の実音声callback/backend/device回収は005-B/008で確認する。
アプリ全体のwindow root再生成や全例外経路は、このBackend/共有view window試験とは分けて残す。

offscreen/software/Basicの英語画面を画像確認した。両案の560×360 px canvasのPNG bytesは一致した。
これはQMLの描画スモークで、物理モニターの操作・描画速度、9言語、各OSのGUI合格とは数えない。
現行Python GUIの全言語UIサイズ検査も別に実行し、変更前の表示・scroll契約を確認する。

MIG-004-AのSDK・両実行物・基本GUI境界までを今回の成果とする。
4-Bのclean/incremental/QML編集/packageの反復時間、配布先起動、他OS、性能予算の判定は後続作業。
短時間のself-test時間は診断値であり、方式の速度差・採用理由には使わない。
独立したNative evaluation CIを追加するが、GitHub実行結果は公開後に確認する。
