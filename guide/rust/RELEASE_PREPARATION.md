# Rust プロトタイプの公開準備

Rust版は`main`へ統合済みで、開発PRのbaseも`main`とする。ここには配布前の未完了条件と公開運用を置く。測定機能の受け入れは [PLAN](PLAN.md)、実機の確認範囲は [VALIDATION](VALIDATION.md) を参照する。mainへの統合、CIビルド、ローカル.app作成を配布済みとは扱わない。

## 初回プロトタイプ配布前のタスク

| 項目 | 完了条件 |
| --- | --- |
| 版番号・互換性・リリースノート | 次のRust版は`v0.10.0`。Cargoとバンドルの版、設定／結果スキーマの互換性、タグ衝突・GitHub Latestの扱いを確認する。Pythonの配布用`version.json`は別途配布変更まで`v0.9.1`を保持 |
| 対応OS／CPU・配布形式 | Windows x64はInno SetupとZIP、Linux x86_64はAppImageと同一AppDirのtar.gz、macOSはIntel／Apple Silicon別のDMGを実装。LinuxはUbuntu 22.04、macOSのdeployment targetは13.0。各OSの通常GUI・実入出力・保存、対応OS版ごとの受け入れを残す |
| 配布ビルド・Release workflow | 3 OSとも通常desktop・`--locked`・qaなしのビルド、版・アイコン・ライセンス・SHA-256とビルド情報を揃え、検証後に共通Draft Releaseへ集約する。発行元署名・macOS公証・実機受け入れを残す。タグ・公開は依頼された段階で実行 |
| ダウンロードの新旧選択 | Pythonを固定で残し、Rustへ明示的に切り替えるメタデータ・成果物選択テストを用意。単一`version.json`の置換で旧版導線を壊さない |
| 利用者向け文書 | Rustの実画面、OS別の起動・権限・入力不在、単位・校正境界・保存形式・既知の制限を実装と照合。旧Python画像をRustへ流用しない |
| 公開候補の受け入れ | 対象SHAで通常起動→内部／実入出力→停止→保存・復元を確認。Generatorのレベル・切断・OFF復元、同期比較の確認範囲を明記。未確認機能は実験段階の表記を維持 |
| GitHub上の確認 | 対象SHAの必須CI、関連するOS別ビルド、Pages公開結果と主要導線を確認。ローカル検証でremoteの成功を推測しない |

配布版と性能・精度の検証対象SHAを一致させる。旧VirusTotal処理を再導入する場合は、アップロードだけで安全判定せず、対象タグと実際の解析状態・結果を表示する。

## Windows配布

[Windows Packages](../../.github/workflows/build_windows.yml) は関連変更のmain宛PR、手動実行、Release workflowから呼び出す。Rust 1.99.0の`x86_64-pc-windows-msvc`を使い、`--release --locked --no-default-features --features desktop`でビルドする。CRTを静的リンクし、利用者へのPython・Rust・Visual C++再頒布可能パッケージの別途導入を不要にする。Windows 10／11 x64を対象とし、ARM64上のx64エミュレーションは受け入れ対象に含めない。

Inno Setup 6.7.3は公式配布のSHA-256を固定して取得する。Rust版のAppId、新規インストール先`%LOCALAPPDATA%\Programs\MeasureLabRust`、ショートカット`MeasureLab (Rust)`はPython最終版と分ける。既定のフォルダー名は空白を含まない。更新はRust版の同じ場所・タスクを引き継ぎ、旧既定の`MeasureLab Rust`や利用者が選んだ場所も自動では移動しない。アンインストールはパッケージ所有ファイルを削除し、設定・測定結果は残す。ASIO切り替え・PyInstaller・旧Pythonランタイムは含めない。

`windows-x64` artifactは以下の4ファイルを含む。版番号はCargoから取得し、タグ実行では完全一致を要求する。実行ごとに新しいステージングディレクトリを使い、過去の成果物を混ぜない。

* `MeasureLab-v<version>-windows-x64-setup.exe`
* `MeasureLab-v<version>-windows-x64.zip`
* `MeasureLab-v<version>-windows-x64-build-info.json`
* `SHA256SUMS-windows-x64.txt`

build-infoはソースSHA・ローカル変更の有無・対象・機能・Rust版・実行ファイルのSHA-256を記録し、ZIPとインストーラーにも同梱する。インストーラーとZIPのテストは日本語・空白を含むパス、実行ファイルの`--help`、QA専用オプションの拒否、ペイロードのハッシュ、ユーザー単位の登録、ショートカット、修復再インストール、データ保持、削除を検証する。通常GUI・GPU・音声の受け入れは別途必要である。

現在の実行ファイルとインストーラーはAuthenticode未署名。SHA-256は同一性確認であり、Windowsの発行元認証ではない。署名証明書・SmartScreenでの扱い、MSVC版の通常GUI・実入出力・保存復元は配布前の確認として残す。ローカル作成は [Windows手順](WINDOWS.md#windows配布パッケージの作成) を参照する。

## Linux配布

[Linux Packages](../../.github/workflows/build_linux.yml) は関連変更のmain宛PR、手動実行、Release workflowから呼び出す。Rust 1.99.0の`x86_64-unknown-linux-gnu`をUbuntu 22.04で使い、`--release --locked --no-default-features --features desktop`でビルドする。日常開発のUbuntu 24.04／26.04環境に22.04を導入する必要はない。公式の基準環境はクラウドrunnerで用意する。

`linux-x86_64` artifactは以下の4ファイルを含む。実行ごとの空のステージング先を使い、AppImageとtar.gzに同じ通常実行ファイル・AppRun・アイコン・版情報・ライセンス・起動説明を入れる。

* `MeasureLab-v<version>-linux-x86_64.AppImage`
* `MeasureLab-v<version>-linux-x86_64.tar.gz`
* `MeasureLab-v<version>-linux-x86_64-build-info.json`
* `SHA256SUMS-linux-x86_64.txt`

[linux_package.py](../../scripts/linux_package.py) はCargoの版・ソースSHA・変更状態・コンパイラー・ビルドOS・機能・実行ファイルと全payloadのSHA-256、ELFのglibc要求と直接依存を記録する。glibc要求は2.35以下を条件とし、新しい依存ライブラリは明示的な確認なしに配布へ混ぜない。appimagetool 1.9.1とtype-2 runtime 20251108は公式の版付きURLとSHA-256を固定する。AppImage作成中のruntime自動更新を使わない。

ALSA本体・設定・プラグイン、glibc、X11／Wayland、xkbcommon、GPUドライバーはホスト側を使い、ランチャーで`LD_LIBRARY_PATH`を変更しない。最小環境には対応するランタイムパッケージが必要である。musl／Alpine・ARM64はこの配布の対象外。GPUやALSAを同梱して全Linux対応と説明しない。

パッケージ検証はUbuntu 22.04／24.04／26.04で同じartifactをダウンロードし、チェックサム、同梱情報とソースSHA、AppImage／tar.gzの全ファイル一致、日本語・空白を含む展開先、`--help`、QA専用オプションの拒否を確認する。ソフトウェアVulkanによる既存の`--gpu-smoke`も実行する。実GPUの通常GUI、Wayland／X11、音声デバイス、測定精度、保存復元、再接続・長時間の受け入れとは分ける。

AppImageは実行権限を付けて起動する。FUSEマウントが使えない環境では`--appimage-extract-and-run`を使うか、tar.gzを展開して`MeasureLab/AppRun`を起動する。起動説明は各配布物の`README.txt`を参照する。ローカル作成はPython 3.12以降、Rust、ビルド依存と`desktop-file-validate`を用意して実行する。

```bash
./.venv/bin/python scripts/linux_package.py build
./.venv/bin/python scripts/linux_package.py verify dist/linux-<id>/release --require-clean --runtime
```

Ubuntu 22.04以外で作る場合もglibc条件を満たす必要がある。ローカル確認のため`--max-glibc`を変更した成果物を、公式の22.04基準を満たした配布物として扱わない。CI成果物の保持期間は14日で、GitHub Releaseでの公開とは別である。Linux資産は発行元署名を付けていない。

## macOS配布

[macOS Packages](../../.github/workflows/build_macos.yml) は関連変更のmain宛PR、手動実行、Release workflowから呼び出す。Rust 1.99.0でIntelの`x86_64-apple-darwin`とApple Siliconの`aarch64-apple-darwin`を各ネイティブrunnerでビルドする。通常desktopだけを`--release --locked --no-default-features --features desktop`で指定し、QA版と分けた`target/distribution-macos/`を使う。`MACOSX_DEPLOYMENT_TARGET=13.0`とInfo.plistの最低版を一致させ、Mach-OのCPU・最低OS版・システム外への動的リンクを検査する。13.0はビルド下限であり、全OS版・機器の動作確認を意味しない。

配布物は`MeasureLab-v<版>-macos-<CPU>.dmg`、同名の`-build-info.json`、`SHA256SUMS-macos-<CPU>.txt`。CPUは`x86_64`／`arm64`で、Universal Binaryではない。DMGはmacOS標準の`hdiutil`で作り、`MeasureLab.app`、`/Applications`へのリンク、起動・権限の説明、The Unlicenseを含める。利用者は`.app`をApplicationsへコピーし、DMGを取り出してから起動する。Python・Rustの導入は不要。旧Python版も`MeasureLab.app`のため、併用時は先に別名・別フォルダーへ退避する。Rust版のbundle identifierは既存の`dev.measurelab.app`を保持し、旧Python版の`com.github_vach.measurelab`とは分ける。

旧版`v0.9.1`の`MeasureLab_macOS.spec`と`entitlements_mac.plist`を参考に、`NSMicrophoneUsageDescription`と`com.apple.security.device.audio-input`を付け、Hardened Runtimeを有効にしてad-hoc署名する。利用目的文と音声入力entitlementは[Appleのマイク権限](https://developer.apple.com/documentation/bundleresources/information-property-list/nsmicrophoneusagedescription)・[音声入力entitlement](https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.security.device.audio-input)の役割に合わせる。Python向けの動的ライブラリ検証緩和・未署名実行メモリーの例外、未実装のRemote Audio I/O用ローカルネットワーク利用目的は引き継がない。権限設定の正本は[entitlements.plist](../../packaging/macos/entitlements.plist)と[パッケージスクリプト](../../scripts/macos_package.py)。

実入力を開始した際はMeasureLabへのマイクアクセスを許可する。外部Core Audio入力も対象となる。拒否した場合は「システム設定 → プライバシーとセキュリティ → マイク」でMeasureLabを許可し、再起動する。アプリ起動とターミナル経由では権限の帰属が異なるため、配布受け入れではコピーした`.app`をFinderから起動し、初回の許可・拒否・設定変更後の再開を確認する。スクリプトはTCC設定を変更せず、この操作を自動検証済みとは扱わない。

Developer ID署名・Appleの公証は未整備。ダウンロードしたアプリはGatekeeperで止まる場合があり、配布元とチェックサムを確認したうえで「プライバシーとセキュリティ」の「このまま開く」を使う。Gatekeeper全体を無効にする手順は配布しない。SHA-256とad-hoc署名は発行元認証の代わりにならない。

パッケージ検証ではチェックサム、ソースSHA・版・通常機能構成、DMGの整合性、Applicationsリンク、同梱物を確認する。マウント中と、日本語・空白を含むパスへのコピー・取り出し後の両方で、全ファイルのSHA-256、署名・Hardened Runtime・音声入力entitlement・利用目的文、`--help`とQA専用オプションの拒否を確認する。署名後の実行ファイル・署名リソース・埋め込みビルド情報のハッシュは、循環参照を避けるため外部manifestへ記録する。CIでのパッケージ検証は、通常GUI・初回権限ダイアログ・音声I/O・測定精度の受け入れとは分ける。

ローカル作成にはmacOS、Xcode Command Line Tools、Rust、Python 3.12以降を使う。Pythonはビルド用で、配布アプリの実行依存には含めない。

```bash
./.venv/bin/python scripts/macos_package.py build
./.venv/bin/python scripts/macos_package.py verify dist/macos-<CPU>-<id>/release --runtime
```

既定は実行中MacのCPU。明示する場合は`--target x86_64-apple-darwin`または`--target aarch64-apple-darwin`をbuild／verifyの両方へ付ける。`--require-clean`は未コミット差分を含む成果物を拒否し、`--runtime --gpu`はコピー後のアプリで既存GPU読み戻しも実行する。`.app`だけ必要なら従来の`./scripts/bundle-macos.sh`を使う。CI成果物の保持期間は14日で、GitHub Releaseでの公開とは別である。

## Release workflowの実行

[Release](../../.github/workflows/release.yml) をブランチで手動実行するとWindows／Linux／macOSのartifactだけを作る。`v*`タグのPushまたはタグを選んだ手動実行では、次の条件を満たして3 OS共通の**Draft Release**を作る。

1. `v0.10.0`以降のRust版で、タグがCargoの版と一致している。
2. タグのコミットが`origin/main`に含まれ、同じSHAのmain Push CIで`lint-and-test`・`docs-lint`・`actionlint`が成功している。CIが未完了なら、成功を待ってRelease workflowを再実行する。
3. Windowsのインストーラー検証、Linuxの3環境のパッケージ検証、macOSのIntel／Apple Silicon別のDMG・署名・コピー後の起動検証が成功し、ダウンロードした全artifactのSHA-256・ソースSHA・対象・通常機能構成が一致している。
4. 同じタグのReleaseがまだ存在しない。途中失敗でDraftが残った場合は内容を確認して削除後に再実行する。既存Releaseへの上書きや資産追加は行わない。

リリースノートはCHANGELOGの対象版から抽出し、3 OSのプロトタイプの制限とソースSHAを加える。各OSはReleaseへ個別に書き込まず、全対象の検証後に単一jobで作成する。通常の`GITHUB_TOKEN`を使い、書き込み権限はDraft作成jobだけに付与する。追加の`RELEASE_TOKEN`は不要。ハイフン付きのCargo版はprereleaseにする。Draftの確認・公開は手動で行い、このworkflowはGitHub Latest、配布サイト、`version.json`を更新しない。

## CIの運用ポイント

実行条件とコマンドの正本は [ci.yml](../../.github/workflows/ci.yml)、変更分類は [ci_changes.py](../../scripts/ci_changes.py) と [回帰テスト](../../scripts/test_ci_changes.py)。ローカル手順は [Tool Usage Guide](../../.agents/workflows/tool_usage.md)。main宛PRとmainへのPush、手動実行を使い、PRの旧実行はキャンセルする。mainのPages公開は中断しない。

| ステータス | 役割 |
| --- | --- |
| `lint-and-test`（必須） | Linuxのfmt・全ターゲット全機能Clippy・GUIなし／通常／QAテスト・doctest。関連変更ではRust 1.95の全ターゲット確認も実行 |
| `docs-lint`（必須、job IDは`build`） | Ruff・Markdown lintは常時。関連変更で新旧MkDocs strict、サイトテスト／ビルド、URL・内部リンク検証、preview |
| `actionlint`（必須） | workflow構文・式・シェルを確認 |
| `compatibility`（任意） | 3 OSの通常desktop release、macOS／WindowsのQAテスト。OS固有変更・配布前に結果を確認 |
| 性能・実機評価 | 手動の反復benchとローカルQA。共有runnerの数値テストとは別に判定 |

必須名は保護ルールとの互換性のため維持する。workflow全体のpathsフィルターで必須ステータスを消さない。関連変更がない場合の省略は変更分類の成功を前提とし、判定失敗・履歴不足・未知入力は全検証へ戻す。任意ビルドの失敗を隠さない。

依存キャッシュはOS・Rust版・依存・コンパイル環境を区別し、mainのPushで更新する。キャッシュヒットは検証の代用にしない。数値テストの条件・許容差は減らさず、`cargo test`のbenchは各条件1回の動作確認、反復性能は`cargo bench`で評価する。保護ルール変更時はGitHubが返した実際のチェック名を確認する。

## 新旧マニュアルとPages

| 公開先（`/MeasureLab/`以下） | ソース | 維持するもの |
| --- | --- | --- |
| `/`・`/en/`と既存ページ | `docs/`、`mkdocs.yml` | Python v0.9.1の本文・画像・検索・深いリンク、旧版ラベルとRustへのリンク |
| `/rust/`・`/rust/en/` | `docs-rust/`、`mkdocs-rust.yml` | 現在使えるRust機能、独立した検索・ナビ |
| `/download/`・`/version.json` | `download-site/`、`version.json` | 現在配布中のPython v0.9.1。Rust配布開始時もPythonへの導線を保持 |

[build_pages.py](../../scripts/build_pages.py) が旧マニュアル→Rust→downloadの順で`site/`へ組み立て、旧ページの日英ルート・主要資産・旧版ラベル・配布JSONと全生成HTMLの内部リンクを検証する。旧版を別ディレクトリへ移さない。PDF自動生成は退役済みで、既存ReleaseのPDF資産は保持する。

PRはpreviewを作る。**mainへマージするとPagesが自動更新される**。公開は新旧サイトビルドと必須3チェックの成功後に限る。タグ・アプリのReleaseとは別の運用である。

## 継続運用の課題

* 文書用Python依存の版固定・更新、CI初回／キャッシュ復元後の時間・容量、Cargo依存の脆弱性・ライセンス確認を整える。依存更新を全自動でマージしない。
* OS別のGPU／音声・長時間試験を再実行できる環境を用意し、対象SHAと条件をQA成果物に保存する。
* 旧版のURLと原本の意味を維持する。Pythonアプリの機能追加・旧テスト環境の復元は再開しない。
