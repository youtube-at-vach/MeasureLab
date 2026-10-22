# Rust プロトタイプの公開準備

Rust版は`main`へ統合済みで、開発PRのbaseも`main`とする。ここには配布前の未完了条件と公開運用を置く。測定機能の受け入れは [PLAN](PLAN.md)、実機の確認範囲は [VALIDATION](VALIDATION.md) を参照する。mainへの統合、CIビルド、ローカル.app作成を配布済みとは扱わない。

## 初回公開に向けた準備範囲

現在はリリース日・公開実行を決めず、公開できる状態への準備を進める。タグ作成・Draft作成・公開・Latest変更は依頼された段階で行う。

* 配布候補はWindows 10／11 x64、glibc 2.35以降のLinux x86_64、macOS 13以降のIntel／Apple Silicon。形式は下記の既存パッケージを使う。ビルド下限と実機の確認済みOS・CPU・経路を区別し、未受け入れの組合せを動作保証へ広げない。
* 初回の機能案内は1〜16ch入力、4ch Scope／Spectrum、Spectrogram／XY、校正・条件付き保存復元を基本とする。Generator・Lock-in・同期2ch比較は実装済みだが実験段階と明記する。Generator／同期比較の最大Fs・反復再接続・長時間・物理校正を受け入れ済みとはしない。[PLANの段階4.5／5](PLAN.md) の統合評価を残し、FRF／Bode等の新機能を初回準備の必須条件へ加えない。
* 配布物の通常GUI、入出力の独立停止、保存復元・OFF復元、既知の欠落や高負荷停止の案内は公開候補で確認する。WindowsのGNU／dev-fast起動、Linuxの過去のAppImage起動、macOSの開発QAは、候補の同一SHA・配布実行ファイルの受け入れへ代用しない。
* 初回は現在の署名状態を案内して準備する。WindowsはAuthenticode未署名、Linuxは発行元署名なし、macOSはad-hoc署名・Developer ID署名／公証なし。署名・公証の追加は後続改善とし、チェックサムとbuild-infoを発行元認証と説明しない。Sigstore・統合チェックサム・VirusTotalは任意の改善候補で、旧処理を自動復活させない。
* 初回`v0.10.0`は**Prerelease、Latest=false**とする。Python v0.9.1のLatestと`version.json`を維持し、Rustは`rust-release.json`で別に管理する。公開前の`published:false`ではRustのダウンロードボタンを無効にする。

## 初回プロトタイプ配布前のタスク

| 項目 | 完了条件 |
| --- | --- |
| 版番号・互換性・リリースノート | 次のRust版は`v0.10.0`。Cargoとバンドルの版、設定／結果スキーマの互換性、タグ衝突・GitHub Latestの扱いを確認する。Pythonの配布用`version.json`は`v0.9.1`を保持し、Rustは`rust-release.json`を使用 |
| 対応OS／CPU・配布形式 | Windows x64はInno SetupとZIP、Linux x86_64はAppImageと同一AppDirのtar.gz、macOSはIntel／Apple Silicon別のDMGを実装。LinuxはUbuntu 22.04、macOSのdeployment targetは13.0。各OSの通常GUI・実入出力・保存、対応OS版ごとの受け入れを残す |
| 配布ビルド・Release workflow | 3 OSとも通常desktop・`--locked`・qaなしのビルド、版・アイコン・ライセンス・SHA-256とビルド情報を揃え、検証後に共通Draft Releaseへ集約する。初回の署名状態は上記方針に従い、実機受け入れを残す。タグ・公開は依頼された段階で実行 |
| ダウンロードの新旧選択 | Python固定とRust明示選択、別メタデータ、全CPU・形式の成果物選択テストを実装。Rustは未公開。公開後に全リンクと配布JSONを確認する |
| 利用者向け文書 | Rustの実画面、OS別の起動・権限・入力不在、単位・校正境界・保存形式・既知の制限を実装と照合。旧Python画像をRustへ流用しない |
| 公開候補の受け入れ | 対象SHAで通常起動→内部／実入出力→停止→保存・復元を確認。Generatorのレベル・独立停止・OFF復元、安全な再接続後の明示Start・再測定、同期比較の確認範囲を明記。未確認機能は実験段階の表記を維持 |
| GitHub上の確認 | 対象SHAの必須CI、関連するOS別ビルド、Pages公開結果と主要導線を確認。ローカル検証でremoteの成功を推測しない |

配布版と性能・精度の検証対象SHAを一致させる。旧VirusTotal処理を再導入する場合は、アップロードだけで安全判定せず、対象タグと実際の解析状態・結果を表示する。

## 公開前の最小確認セット

すべて同一候補SHAを基準にする。通常GUIの受け入れはrelease／desktop・qaなしの配布実行ファイルで行い、QA版・開発ビルド・別SHAの成功で置き換えない。P0は公開前必須、P1は確認するか未確認範囲を明記して公開判断する。P1未実施の計画項目は未完了のまま保持する。

現在のIntel MacではGUI操作手段の技術的制約により、手動GUI操作チェックと実モニター間DPI操作を検証計画から除外する。この環境では該当するP0／P1の手動操作を公開前の未完了条件に数えず、対象外と記録する。他の操作可能な環境の確認、実行可能な自動QA・数値・連続動作評価、配布物と実入出力の条件は維持する。詳細は [検証対象環境](VALIDATION.md#検証対象環境と既存成果物) を参照する。

測定・出力中のUSB抜去は [安全上の必須制約](VALIDATION.md#物理デバイスの安全制約) により実施しない。以下の再接続は入出力停止・ストリーム解放後に限る。抜去試験を公開前条件へ戻さない。

| 優先 | 項目 | 完了・判断の基準 |
| --- | --- | --- |
| P0 | 現行Generator→同期2ch比較 | 内部・BlackHole・UAC-232の代表条件で同じ入力窓の独立照合、REF／SIG交換、低REF・欠落の無効化、有限Stop、JSON／CSV・別プロセス復元・OFF復元・再測定 |
| P0 | エラー処理と安全な再接続 | ERROR保持・出力解放は模擬条件で判定。実機は停止・解放後の再接続を反復し、復元後OFFと明示Start後の再測定を別に判定 |
| P0 | 通常GUIの長時間完走 | 代表48 kHzでGenerator・Spectrum・Spectrogram、編集・保存を含め、有限Stop・最終数値照合・解放後通知監査まで完了。中断を成功にしない |
| P1 | 物理4chと高Fs境界 | 識別可能な4入力のCH・数値・保存を照合。UAC-232の192 kHz起動欠落を別判定。内部4ch・48 kHz成功で代用しない |
| P0 | 入出力から保存復元までのGUI操作 | 計器選択／併置、Generatorカードの追加・複製・削除・並べ替え・OUT、共通／別Fs、選択と実行状態、非表示中と入力停止後の出力確認・停止 |
| P0 | 通常幅・狭幅と直近GUI変更 | メニュー・編集・Help前面のSpace／Escape、XY詳細、Spectrumの4ch・カーソル・ESD、Spectrogramの全配色・Hold／Live・時間A／B。主要値・単位・停止操作と配置復帰 |
| P1 | 実モニター間DPI | 異なるネイティブDPIのモニター間を往復し、文字・プロット・操作位置・停止・配置復元を確認。単画面の倍率変更で代用しない |
| P0 | OS／CPU別配布物の受け入れ | Windows MSVC Setup／ZIP、Linux AppImage／tar.gz、macOS Intel／arm64 DMGの通常起動・内部／実入出力・独立停止・保存・再起動・OFF復元。実GPU・権限の許可／拒否／復帰は各環境で確認 |
| P0 | 最終資産と公開内容の一致 | 受け入れた実行ファイルと最終資産のハッシュ、実測・失敗・未確認を記すリリースノート、Prerelease=true・Latest=false、Python v0.9.1維持 |

各項目に候補SHA・実行ファイルSHA-256・環境／機器／Fs・pass／fail／not-run／対象外・証拠の場所を残す。内部／仮想／物理、QA自動検証／通常GUI手動、OS／CPU・配布形式ごとに結果を分け、一部成功で項目全体をpassにしない。成果物は [配布パッケージの受け入れ](VALIDATION.md#配布パッケージの受け入れ) のGit管理外ディレクトリへ保存する。最終資産・Draftがまだない場合、最終一致とPrerelease／Latestの実物確認はnot-runとし、workflow設定の照合とは区別する。

## Windows配布

[Windows Packages](../../.github/workflows/build_windows.yml) は関連変更のmain宛PR、手動実行、Release workflowから呼び出す。Rust 1.99.0の`x86_64-pc-windows-msvc`を使い、`--release --locked --no-default-features --features desktop`でビルドする。CRTを静的リンクし、利用者へのPython・Rust・Visual C++再頒布可能パッケージの別途導入を不要にする。Windows 10／11 x64を対象とし、ARM64上のx64エミュレーションは受け入れ対象に含めない。

Inno Setup 6.7.3は公式配布のSHA-256を固定して取得する。Rust版のAppId、新規インストール先`%LOCALAPPDATA%\Programs\MeasureLabRust`、ショートカット`MeasureLab (Rust)`はPython最終版と分ける。既定のフォルダー名は空白を含まない。更新はRust版の同じ場所・タスクを引き継ぎ、旧既定の`MeasureLab Rust`や利用者が選んだ場所も自動では移動しない。アンインストールはパッケージ所有ファイルを削除し、設定・測定結果は残す。ASIO切り替え・PyInstaller・旧Pythonランタイムは含めない。

`windows-x64` artifactは以下の4ファイルを含む。版番号はCargoから取得し、タグ実行では完全一致を要求する。実行ごとに新しいステージングディレクトリを使い、過去の成果物を混ぜない。

* `MeasureLab-v<version>-windows-x64-setup.exe`
* `MeasureLab-v<version>-windows-x64.zip`
* `MeasureLab-v<version>-windows-x64-build-info.json`
* `SHA256SUMS-windows-x64.txt`

build-infoはソースSHA・ローカル変更の有無・対象・機能・Rust版・実行ファイルのSHA-256を記録し、ZIPとインストーラーにも同梱する。インストーラーとZIPのテストは日本語・空白を含むパス、実行ファイルの`--help`、QA専用オプションの拒否、ペイロードのハッシュ、ユーザー単位の登録、ショートカット、修復再インストール、データ保持、削除を検証する。通常GUI・GPU・音声の受け入れは別途必要である。

初回は現在の実行ファイル・インストーラーのAuthenticode未署名状態を案内する。SHA-256は同一性確認であり、Windowsの発行元認証ではない。SmartScreenでの扱い、MSVC版の通常GUI・実入出力・保存復元は配布前の確認として残す。署名証明書の整備は後続改善とする。ローカル作成は [Windows手順](WINDOWS.md#windows配布パッケージの作成) を参照する。

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

Developer ID署名・Appleの公証は未整備で、初回はこの状態を明記して準備する。ダウンロードしたアプリはGatekeeperで止まる場合があり、配布元とチェックサムを確認したうえで「プライバシーとセキュリティ」の「このまま開く」を使う。Gatekeeper全体を無効にする手順は配布しない。SHA-256とad-hoc署名は発行元認証の代わりにならない。

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

リリースノートはCHANGELOGの対象版から抽出し、3 OSのプロトタイプの制限とソースSHAを加える。各OSはReleaseへ個別に書き込まず、全対象の検証後に単一jobで作成する。通常の`GITHUB_TOKEN`を使い、書き込み権限はDraft作成jobだけに付与する。追加の`RELEASE_TOKEN`は不要。初回`0.10.0`とハイフン付きのCargo版はprereleaseにする。Draftの確認・公開は手動で行い、このworkflowはGitHub Latest、配布サイト、`version.json`を更新しない。

## 公開候補の通し確認と公開運用

以下は実行時の手順であり、記載だけで実施済みとはしない。現段階では公開せず、候補SHAが決まった時点で開始する。

1. 候補を`main`へ統合し、そのSHAの必須3チェックを確認する。ブランチのRelease workflowを手動実行する（例：`gh workflow run release.yml --ref main`）。実行詳細の`headSha`が候補SHAであることを確認する。ブランチ実行ではDraftを作らない。
2. Windows、Linux、macOS Intel／Apple Siliconの4 artifactをダウンロードする。Windows 4、Linux 4、macOS各3の計14ファイル、版・ソースSHA・clean・release／desktop・対象CPU、全チェックサムを確認する。ソースをビルドし直した別実行ファイルで受け入れを置き換えない。
3. [配布パッケージの受け入れ](VALIDATION.md#配布パッケージの受け入れ) を同じ配布実行ファイルで行う。OS・CPU別の未実施、失敗と既知の問題を区別し、受け入れ範囲を利用者文書とリリースノートへ反映する。ソース修正後は新しい候補SHAへ戻り、影響するパッケージを再確認する。
4. リリースを依頼された段階でCargoと一致するタグを作り、タグのRelease workflowで共通Draftを作る。手動ビルドの成功はタグ時のCI・全資産検証・Draft作成の代わりにはならない。Draftの14ファイル・SHA・リリースノート・Prerelease=true・Latest=falseを確認する。Draftの再ビルド資産も受け入れた実行ファイルのハッシュと照合し、異なれば受け入れをやり直す。
5. 公開を依頼された段階でDraftを公開する。ログアウト状態でもタグ別Releaseと全資産を取得でき、SHA-256が一致することを確認する。Python v0.9.1が引き続きLatestであることも確認する。
6. 公開後、`rust-release.json`の`version`を公開したCargo版へ合わせ、`published:true`にする。`version.json`は変更しない。サイトテスト・新旧MkDocs strict・統合ビルドと必須CIを通し、サイト反映を依頼された段階でmainへ統合する。mainへの統合はPages公開を起こす。全資産の確認前に`published:true`にしない。
7. Pages deploy成功後、`/version.json`と`/rust-release.json`、Python／Rustの切り替え、日英中、全OS・CPU・形式、マニュアルの導線を公開URLで確認する。Rustの全6パッケージを取得し、Releaseのチェックサムと一致することを確認する。Pythonの既存Intel DMG・Windows onedir ZIPも確認する。

### 失敗・不完全Draft・問題版

* パッケージ／チェックサム／SHA不一致で失敗した場合は公開しない。失敗runと資産を保存し、原因を直した候補SHAで通し確認へ戻る。
* 同じタグのReleaseがあるとworkflowは上書きを拒否する。未公開の不完全Draftは資産・SHA・失敗runを確認し、削除を依頼された段階でDraftだけを削除してタグのworkflowを再実行する。正常な既存Releaseへの追加投稿や、移動したタグへの追随で資産を混ぜない。
* 公開後の問題は対象版・OS／CPU・症状と回避策をRelease説明とRustマニュアルに明記する。配布停止が必要なら`rust-release.json`を`published:false`へ戻してサイトを反映する。修正版は新しい版・タグで準備し、公開済みの同じ名前の資産を差し替えない。
* Rustメタデータが取得不能・不正の場合もRustのボタンは無効になる。Pythonの既存ダウンロードは独立して維持する。サイトをロールバックする際もPythonのURL・`version.json`を保持する。

## CIの運用ポイント

実行条件とコマンドの正本は [ci.yml](../../.github/workflows/ci.yml)、変更分類は [ci_changes.py](../../scripts/ci_changes.py) と [回帰テスト](../../scripts/test_ci_changes.py)。ローカル手順は [Tool Usage Guide](../../.agents/workflows/tool_usage.md)。main宛PRとmainへのPush、手動実行を使い、PRの旧実行はキャンセルする。PRの`edited`も監視し、前提PRの統合後に宛先をmainへ変更した場合も検証する。本文・タイトルの編集も再実行になる。mainのPages公開は中断しない。

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
| `/download/`・`/version.json`・`/rust-release.json` | `download-site/`と新旧の配布JSON | Python v0.9.1を保持し、Rustは明示選択。Rust公開前は`published:false`でダウンロードを無効化 |

[build_pages.py](../../scripts/build_pages.py) が旧マニュアル→Rust→downloadの順で`site/`へ組み立て、旧ページの日英ルート・主要資産・旧版ラベル・配布JSONと全生成HTMLの内部リンクを検証する。旧版を別ディレクトリへ移さない。PDF自動生成は退役済みで、既存ReleaseのPDF資産は保持する。

PRはpreviewを作る。**mainへマージするとPagesが自動更新される**。公開は新旧サイトビルドと必須3チェックの成功後に限る。タグ・アプリのReleaseとは別の運用である。

## 継続運用の課題

* 文書用Python依存の版固定・更新、CI初回／キャッシュ復元後の時間・容量、Cargo依存の脆弱性・ライセンス確認を整える。依存更新を全自動でマージしない。
* OS別のGPU／音声・長時間試験を再実行できる環境を用意し、対象SHAと条件をQA成果物に保存する。
* 旧版のURLと原本の意味を維持する。Pythonアプリの機能追加・旧テスト環境の復元は再開しない。
