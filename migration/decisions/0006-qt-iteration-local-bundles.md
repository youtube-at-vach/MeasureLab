# 0006: Qt接続方式の開発反復とIntelローカルbundle

2026-09-30、MIG-004-B。基準HEADは004-Aの`80435eef`。
作業開始時はremote一致・cleanで、`codex/migration-004-b`へ分岐した。
Rust/QMLの採用、製品の配布方式、公開ABIは決定しない。

## 測定範囲

[004-A](0005-qt-boundary-probes.md)の同じQML・模擬worker・Cargo.lockとQt SDKを使い、
[性能protocol](../benchmarks/protocol.md)の開発反復経路をIntel Macで測定した。
[runner](../../scripts/migration_qt_iteration.py)と[再実行手順](../../native/qt-iteration.md)を追加した。
元のsource・`native/target`へ測定patchを適用せず、専用コピーと方式別targetを使う。

macOS 14.8.9、Core i5-5675R、RAM 8 GiB、AC電源、並列数4。
Rust 1.98.1、Qt 6.11.2、CXX-Qt 0.10.0、Qt Bridge 0.3.0、debug、
offscreen/software/Basic、英語560×360 px、Qt scale factor 1。
`MACOSX_DEPLOYMENT_TARGET=13.0`を明示し、実行物の`minos 13.0 / sdk 15.2`も確認した。
macOS 13での起動確認ではない。

全sample・集計・source/hash・コマンドログをローカルの
`../benchmarks/results/2026-09-30-004-b-intel.json`へ保存した。
詳細reportとログはGit管理外とし、Gitにはこの文書の条件・結果・限界と再実行手順を残す。
clean各3回、no-op各warmup1回+5回、QML編集各5回、package各3回。
warmupを除いた32 sampleはすべて合格し、warmup2回も寿命検査を通った。
ログはgzip圧縮し、reportから相対パスとhashで参照する。
測定sourceのhashは開始時のコピーを示す。測定後のLinux専用SDK/CI修正はMacの組合せを変更しない。

## 結果と判断

時間は必要な検証完了までを含む。単発のreadyのみの値に置き換えない。

| 経路 | CXX-Qt 中央値、min〜max | Qt Bridge 中央値、min〜max | 判定 |
| --- | --- | --- | --- |
| clean + core/UI検査 | 221.795秒、221.259〜224.705秒 | 258.154秒、254.057〜258.282秒 | 両方式とも600秒以内 |
| no-op + core/UI検査 | 2.470秒、2.440〜2.513秒 | 2.646秒、2.578〜2.894秒 | 回数・状態/寿命検査合格。専用の時間予算なし |
| QML編集 + UI検査 | 2.063秒、2.035〜2.093秒 | 2.241秒、2.215〜2.341秒 | 両方式とも10秒以内 |
| package + 展開/UI検査 | 56.903秒、56.807〜75.745秒 | 59.842秒、58.845〜101.453秒 | 両方式とも900秒以内。クリーンOSは未確認 |

各経路の主時間は次の全sampleを測定順に保存する（秒、小数3桁に丸め、warmupを除く）。

| 経路 | CXX-Qt 全sample | Qt Bridge 全sample |
| --- | --- | --- |
| clean | 221.795 / 224.705 / 221.259 | 258.154 / 258.282 / 254.057 |
| no-op | 2.513 / 2.440 / 2.478 / 2.470 / 2.458 | 2.658 / 2.646 / 2.578 / 2.619 / 2.894 |
| QML編集 | 2.093 / 2.086 / 2.063 / 2.063 / 2.035 | 2.234 / 2.215 / 2.261 / 2.241 / 2.341 |
| package | 56.807 / 56.903 / 75.745 | 59.842 / 58.845 / 101.453 |

QMLの固定変更は表示labelだけ。各回元のbytesへ戻し、10回すべてCargoのFresh/no compileを要求した。
外部QMLを読む設計なので、Rust codegen/resource/relinkは発生しない。
resource埋込み・QML事前コンパイル・測定DSPの変更を同じ待ち時間と扱わない。

packageの3回目は両方式とも長くなった。全値と標準偏差を残し、短いrunだけを選ばない。
原因は特定していない。OS cache、熱、他processの条件は制御していない。
現行Python全体のoffline起動も3回成功し、ready中央値は7.100秒、範囲6.861〜8.815秒。
workloadが異なるため、小さなQML画面との速度比・表示編集予算には使わない。
今回の判断は両方式がこの開発反復の絶対基準内で成立した範囲に限る。

## bundleと再配置

QMLパス解決へbundleの`Contents/Resources/Main.qml`を追加した。
bundle内でresourceが欠けた場合はエラーとし、developer checkoutへfallbackしない。
`macdeployqt`ではCocoa/offscreen pluginとframework検索パスを明示し、
使わないSQL driverの外部依存を避ける。終了コード0でも依存の`ERROR:`を拒否する。

各回別のad-hoc署名bundleを作り、署名検査、ZIP化、別ディレクトリへの展開、寿命検査を行う。
SDKの環境変数・開発用PATHを外し、専用HOME/cacheで起動する。
QML実パスと実際にロードされたQt library/pluginがすべて展開bundle内にあることを要求した。
ZIPはCXX-Qt約44.47 MiB、Qt Bridge約45.17 MiB。配布・downloadは行っていない。

ローカルの補助検査report（`../qt/2026-09-30-intel-bundle.json`）で、Cocoa/softwareでの寿命検査と
展開後の`codesign --verify --deep --strict`も両方式で成功した。
bundleのQMLを一時的に外すと両方式ともexit 101となり、readyへ進まない。検査後は復元した。
英語canvasの画像を確認し、両方式のPNG bytesは一致した。画像は`.migration-local/`に保存する。
手動入力、フォーカス、物理画面の評価は未実施。

## 開発中の失敗とLinux CI

試行の事前検査失敗4件と修正4回を、ローカルの
`../benchmarks/results/2026-09-30-004-b-development.json`と圧縮ログへ別保存した。
locale警告をSDK版へ混ぜた検査誤り、offscreen/不要SQL plugin、system libraryの誤分類、
Qt Bridgeのbundle framework検索/署名エラーを修正した。
これらを本測定の成功sampleで上書きせず、試行の時間を予算判定にも混ぜない。
本測定のcompiler/test失敗は0。AIのpatch作成時間はツール待ちと分離計測していないためunknown。

004-Aの[GitHub実行](https://github.com/youtube-at-vach/MeasureLab/actions/runs/36671211283)を確認した。
pure worker jobは成功したが、Qt jobはSDKの`qmake`が`libicui18n.so.73`をロードできず失敗し、
QML検査はskipされていた。[失敗根拠](../qt/2026-09-30-linux-ci.json)を保存した。
Qt 6.11.2の配布metadataで`icu` archiveを確認し、Linux専用の追加archiveと
空の環境での`qmake -query QT_VERSION`をCIへ追加した。
これはCXX-Qtの`env_clear()`によるSDK検出と同じ条件を先に検査するため。
CI YAML・inline Python・SDK仕様の整合をローカル確認した。修正後のGitHub CIは未実行。

## 残す作業

- MIG-004-B: Linux CIの再実行、ARM/Windows/Linuxの反復測定、release package、クリーンOSでの起動。
- Gatekeeper・Developer ID署名・notarization・Finder/download経路。full Xcodeも未導入。
- 同等Python表示編集、core編集、10分連続、CPU/RSS・描画遅延・実機2ch。
- QMLの9言語、テーマ、入力・フォーカス、High DPI条件の組合せ。
- AC07の実graph所有権、AC13の実音声回収、AC16全体。採用判断はMIG-008。

残るOS確認は005-A/006-Aの純粋演算・契約比較を妨げない。
003-A/B/Cの保存入力・期待値・許容差と、現行製品のDSP/UIは変更していない。
