# MIG-004-B 開発反復・ローカルbundleの比較

[004-Aの共通画面](qt-probe.md)と同じSDK・依存lock・模擬workerを使う。
これは開発反復の検証で、音声callback・DSP・Analysis Graphの実行性能ではない。
[性能protocol](../migration/benchmarks/protocol.md)の回数と検証終点をrunnerへ固定した。
各reportのOS/CPUでの検査として扱い、クリーンOSへの配布、技術採用の判断には数えない。

## 再実行

リポジトリルートで実行する。Pythonは専用venv、SDKとRustは導入済みのものを使い、通信を行わない。
runnerが環境を設定するので、004-AのSDK環境変数を事前にexportする必要はない。

```bash
./.venv/bin/python scripts/migration_qt_iteration.py --qt-prefix .tools/qt/6.11.2/macos --report .migration-local/004-b.json
./.venv/bin/pytest -q tests/logic_verification/test_migration_qt_iteration.py tests/logic_verification/test_migration_qt_probe.py
```

LinuxではSDKを `.tools/qt/6.11.2/gcc_64` として同じコマンドを実行する。
Linuxの専用ツール導入・環境修復は[環境手順](../migration/environment.md#linuxでの再開)を参照。
ビルド時の不足ライブラリを作業用パスで補う場合、その条件をreportと環境記録に残す。

`--smoke`は各経路1回の診断用。protocol完了・予算判定には使わない。
reportと対応する`<report名>-logs/`へ、終了コード、単調clockの時間、ready観測時刻、
全コマンドのgzip圧縮log/hash、全sampleと中央値/min/max/標準偏差を保存する。
結果JSONと対応する`<report名>-logs/`はローカル生成物としてGit管理外に置く。
Gitには[比較記録](../migration/decisions/0006-qt-iteration-local-bundles.md)へ条件・結果・限界を残す。
report内のlog相対パスとhashはローカルログの照合用で、別checkoutにはreportとログを別途移す。
失敗sampleを除外した集計や、自動再試行による上書きはしない。
ログの`<repo>`・`<scratch>`・`<home>`は絶対パスの置換で、コマンドの引数自体は変更しない。

## 測定条件

| 経路 | 回数・開始条件 | 終点・検証 |
| --- | --- | --- |
| clean | 各方式3回。Cargo依存取得済み。方式別target全体を削除 | debug build、模擬coreテスト、同じQMLのready・全寿命試験・破棄完了 |
| no-op | 各方式warmup1回を除外して5回。source変更なし | 増分build、模擬coreテスト、同じQMLのready・全寿命試験・破棄完了 |
| QML編集 | 各方式5回。同じlabelの文字列変更を適用してから開始、毎回元のbytesに復帰 | CargoのFresh/no compile確認、ready・全寿命試験・破棄完了 |
| package | 各方式3回。既存のdebug実行物から開始 | bundle作成、Qt依存導入、署名検査、ZIP化、別ディレクトリへ展開、同じ寿命試験 |
| Python起動 | 3回。現行版全体を新process・分離状態・offlineで起動 | self-testの起動成功markerまでを記録。5秒後の自動終了も要求 |

CPU並列数4、Qt 6.11.2、Rust 1.98.1、offscreen/software/Basic、scale 1、英語560×360 px。
macOSのみ`MACOSX_DEPLOYMENT_TARGET=13.0`を両方式に指定する。macOS 13での起動確認を意味しない。
LinuxではhostのGCCを使い、macOS用のcompiler・SDK・電源照会は実行しない。
方式ごとに別targetを使い、同じsample番号でCXX-Qt→Qt Bridgeの順に交互実行する。
OS page cacheと熱・他processの影響は固定できない。
[QML disk cache](https://doc.qt.io/qt-6/qmldiskcache.html)は専用パスへ分離する。
QMLは外部ファイルで、resource埋込み経路ではない。
core編集・同じPython表示編集・release実行性能は後続作業。
Python起動は41モジュールを持つ現行版全体なので、小さなQML画面との速度比を予算判定に使わない。

各runの主時間は必要な検査完了までを含む。readyだけの観測値も別保存し、
検査を省略した時間を開発反復時間に置き換えない。
clean 600秒・表示編集10秒・package 900秒の絶対基準を記録する。
表示編集で10秒を超えても、同等Python値がなければ`max(10秒, Pythonの2倍)`の超過を断定しない。

## macOSローカルbundleの境界

[Qtの公式配布手順](https://doc.qt.io/qt-6/macos-deployment.html)に従い、
SDKの`macdeployqt -qmldir=...`でQt framework・QML importをbundleへ導入する。
`-no-plugins`で自動plugin一式の導入を外し、Cocoa/offscreenを明示して依存を書き換える。
実行物へbundleのframework検索パスを追加し、SDKのlibrary探索先も明示する。
この画面で使わないSQL driver等の外部依存をpackageへ持ち込まない。
終了コード0でも`macdeployqt`が依存の`ERROR:`を出したら不合格にする。
生成物は別名の評価アプリで、製品版の保存先・更新・配布には接続しない。
SDK標準のad-hoc署名を`codesign --verify --deep --strict`で検査する。

共通coreのQMLパス解決は、明示override、bundleの`Contents/Resources/Main.qml`、開発用QMLの順。
bundleの場合はresourceが欠けたら失敗させ、開発checkoutへfallbackしない。
ZIPを別の場所へ展開し、SDK環境変数と開発用PATHを外し、新しいHOME/cacheで起動する。
読み込んだQMLの実パスと`DYLD_PRINT_LIBRARIES`のQt library/plugin実パスが展開bundle内であることを要求する。

開発SDKが導入された同じMacでの試験なので、クリーンOS試験の代用にはしない。
物理画面・Finder起動・Gatekeeper・Developer ID署名・notarization・download経路は未確認。
full Xcodeも未導入。他OSのpackage手順をこの結果から成功と扱わない。

## Linuxローカルpackageの境界

[QtのLinux配布手順](https://doc.qt.io/qt-6/linux-deployment.html)と
[qt.conf](https://doc.qt.io/qt-6/qt-conf.html)に従い、実行物、QML、Qt/ICU共有ライブラリ、
QtQml/QtQuick import、offscreen/xcb pluginを同じdirectoryへ置く。
`ldd`で実行物と全QML/platform pluginの推移的依存を検査し、SDKの`lib`内の依存をコピーする。
不足依存を拒否し、glibc・X11・OpenGL・font等のhost依存をreportに記録する。
QtQml/QtQuick内の未使用styleも含むため、最小packageサイズや製品配布の比較には使わない。

launcherは自身のdirectoryから`LD_LIBRARY_PATH`を設定する。`qt.conf`でplugin/importの探索先を固定する。
tar.gzを新しいdirectoryへ展開し、開発PATH・SDK/plugin/QML overrideを外した新しいHOME/cacheで起動する。
`LD_DEBUG=libs`の実際の`calling init`記録から、Qt/ICU/pluginが展開物内であることを要求する。
検索候補だけの記録は合格にしない。QMLの実パスと全寿命markerも検査する。
`bin/`内の実行物は隣接する`share/measurelab-evaluation/Main.qml`を要求し、
QMLを取り除く異常系はexit 101と失敗markerを保存する。開発checkoutへfallbackしない。

検査後はarchiveと展開物を保持し、重複するstaging treeを削除する。
同じhostでのdebug package診断であり、clean OS・別distribution・release・署名・公開配布は未確認。
packageの反復時間には依存検査、圧縮、展開、正常起動、QML欠落拒否までを含む。

生成したworkspace・target・bundle・ZIPは`.migration-local/qt-iteration/run-*/`へ保持する。
runnerは実行ごとに新しい場所を作り、元のsourceや既存`native/target`を書き換えない。
worktreeを退役させる前に、必要な生成物は別途保護する。
