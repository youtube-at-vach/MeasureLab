# Rust プロトタイプの公開準備

Rust版は`main`へ統合済みで、開発PRのbaseも`main`とする。ここには配布前の未完了条件と公開運用を置く。測定機能の受け入れは [PLAN](PLAN.md)、実機の確認範囲は [VALIDATION](VALIDATION.md) を参照する。mainへの統合、CIビルド、ローカル.app作成を配布済みとは扱わない。

## 今回の作業範囲と検証の分担

この文書は、進行中の実装とは別に、初回プロトタイプを公開するまでの残作業・成果物・完了条件を整理する正本とする。残作業の文章化と、実装修正・実機確認・公開操作の実施は別タスクとして扱う。

* **エージェントが行うアプリの検証はmacOS（Intel）に集中する。** 代表的な測定から停止・保存・復元までを十分に確認し、既存の証拠と変更の影響から追加範囲を選ぶ。
* **Windows・Linuxの確認はユーザーが行う。エージェントは不具合が報告された場合だけ、該当条件を調査・確認する。** 報告がない段階で両OSの網羅テストや再試験を追加せず、エージェントによる確認を公開前の必須条件にしない。
* Apple Siliconの実機確認も今回のエージェント作業には追加しない。既存のarm64パッケージ作成は維持し、実機未確認の範囲を案内する。
* 既存CI・パッケージ生成の仕組みは利用する。これらの成功とユーザーの実機確認を記録し、同じ条件の検証をエージェントが重ねない。テストマトリクスやCIの変更は今回の作業に含めない。

以降のOS別手順は配布方法と必要時の参照資料であり、全OSの試験をエージェントへ割り当てるものではない。現在のIntel Macで実施できない手動GUI・実モニター間DPI操作は、既存の [環境除外](VALIDATION.md#検証対象環境と既存成果物) を維持し、公開待ちの条件へ戻さない。

## 初回公開に向けた準備範囲

現在はリリース日・公開実行を決めず、公開できる状態への準備を進める。タグ作成・Draft作成・公開・Latest変更は依頼された段階で行う。

* 配布候補はWindows 10／11 x64、glibc 2.35以降のLinux x86_64、macOS 13以降のIntel／Apple Silicon。形式は下記の既存パッケージを使う。ビルド下限と実機の確認済みOS・CPU・経路を区別し、未受け入れの組合せを動作保証へ広げない。
* 初回の機能案内は1〜16ch入力、4ch Scope／Spectrum、Spectrogram／Cepstrogram／XY、校正・条件付き保存復元を基本とする。Generator・Lock-in・同期2ch比較は実装済みだが実験段階と明記する。Generator／同期比較の最大Fs・反復再接続・長時間・物理校正を受け入れ済みとはしない。[PLAN](PLAN.md#現在地と次の作業) の代表条件での統合評価は完了しており、その結果を引き継ぐ。FRF／Bode等の新機能を初回準備の必須条件へ加えない。
* 配布物の通常GUI、入出力の独立停止、保存復元・OFF復元は公開候補で短く確認する。エージェントはmacOS Intel、Windows・Linuxはユーザーが確認する。精度・継続性は対象ソースと条件を識別した開発QAを使い、各OS・CPU・配布形式で同じ数値試験を繰り返さない。既知の欠落や高負荷停止、未確認環境は制限として案内する。
* 初回は現在の署名状態を案内して準備する。WindowsはAuthenticode未署名、Linuxは発行元署名なし、macOSはad-hoc署名・Developer ID署名／公証なし。署名・公証の追加は後続改善とし、チェックサムとbuild-infoを発行元認証と説明しない。Sigstore・統合チェックサム・VirusTotalは任意の改善候補で、旧処理を自動復活させない。
* 初回`v0.10.0`は**Prerelease、Latest=false**とする。Python v0.9.1のLatestと`version.json`を維持し、Rustは`rust-release.json`で別に管理する。公開前の`published:false`ではRustのダウンロードボタンを無効にする。

## 初回プロトタイプ配布前のタスク

配布の仕組みを作り直す段階ではない。Windows Setup／ZIP、Linux AppImage／tar.gz、macOS Intel／arm64 DMG、チェックサム・build-info、共通Draft Release、Python／Rustのダウンロード分離、マニュアルと不具合報告窓口は実装済み。ローカルで確認した公開設定はCargo `0.10.0`、`rust-release.json`が`published:false`、Pythonの`version.json`が`0.9.1`である。候補SHA・最終配布物・GitHub上のRelease／Pagesの状態は別途確定する。

以下は未完了の残作業であり、文書へ記載しただけでは完了にしない。R1〜R6を公開前に整え、R7〜R8は公開を依頼された段階で実行する。

| 順序 | 残作業・対象 | 成果物と完了条件 |
| --- | --- | --- |
| R1 | 公開範囲と候補を確定する：[PLAN](PLAN.md)、[Cargo.toml](../../Cargo.toml) | 進行中の実装から初回へ含める変更と版を決め、公開用文書を揃えた時点で配布候補SHAを固定する。段階4.5／5の評価結果を引き継ぎ、この配布準備で同じ実装・評価を二重に進めない。Generator・Lock-in・同期比較は実験段階とし、新機能を追加の公開条件にしない |
| R2 | 既知問題の扱いを決める：[確認済みの条件と制限](VALIDATION.md#コードで代替できない確認の要約) | 代表条件で測定を完遂できない問題、保存結果の誤り、独立Stop／OFF復元の不具合は修正対象として切り出す。高Fs・高負荷・未校正条件は再現条件、回避策または推奨条件、未確認範囲を記した公開説明にまとめる。UAC-232の48 kHz表示負荷QAで過去の長い停止が再現しなかったことと、192 kHz起動欠落・小信号位相の未解決を区別する |
| R3 | 利用者文書を現行仕様へ揃える：[README日英](../../README.ja.md)、[Rustマニュアル](../../docs-rust/index.md)、[詳細操作](README.md) | README日英のGenerator「2信号の正弦波」を最大16カード・Sine／Square／Triangle／Noiseへ更新する。Spectrogram内のCepstrogram、入出力の独立開始・停止、結果保存の対象と制限を各入口で一貫して案内する。通常の開始→観察→停止→保存を既存クイックスタートから辿れ、必要な画像だけ現行Rust画面と照合する |
| R4 | 同梱説明と保存形式を揃える：[packaging/](../../packaging/)、[CHANGELOG](../../CHANGELOG.md)、[配布受け入れ手順](VALIDATION.md#配布パッケージの受け入れ) | macOS／Linuxの同梱READMEにある「要求時だけ設定を保存」を、現行の設定自動保存・停止中復元と、利用者が明示保存する結果に分けて直す。設定版11（旧1〜10）・結果JSON版7（旧1〜6）を [settings.rs](../../src/settings.rs)／[export.rs](../../src/export.rs) と照合し、CHANGELOGと受け入れ手順の旧v9／v6表記を更新する |
| R5 | リリースノートを仕上げる：[CHANGELOGのv0.10.0節](../../CHANGELOG.md) | 機能・互換性・実験段階・署名状態・推奨条件・未確認範囲を記す。古い約29秒のUI停止と、その後の48 kHz表示負荷QAの結果を区別し、確認済みの安全な再接続と通常Generatorの別プロセスOFF復元・再測定を反映する。公開日が決まったらタグ作成前にUnreleasedを公開日へ変更し、既存の抽出処理でDraft説明へ渡せる状態にする |
| R6 | 配布候補を揃え、Intel Macの確認を終える：[既存workflow](../../.github/workflows/release.yml)、[最小確認セット](#公開前の最小確認セット) | 候補の既存CI結果と全14資産の版・CPU・通常desktop／qaなし・ソース識別・ハッシュ・同梱物を照合する。macOS Intelの配布物に必要な確認を行い、Windows・Linuxはユーザーの確認結果を受け取る。不具合が報告された場合だけ該当OSを調査する。未確認の組合せは明記し、エージェントの全OS再試験を条件にしない |
| R7 | タグ・Draftを作り公開する：[公開運用](#公開候補の通し確認と公開運用) | 依頼後にCargoと一致するタグと共通Draftを作り、最終資産・リリースノート・Prerelease=true・Latest=falseを確認して公開する。Python v0.9.1のLatestを維持する。既存workflowの成功を使い、最終資産と受け入れた実行ファイルが同じことを確認する |
| R8 | ダウンロードと案内を公開版へ切り替える：[rust-release.json](../../rust-release.json)、[配布サイト](../../download-site/)、[Rustマニュアル](../../docs-rust/install.md) | Releaseの全資産を取得できた後に`published:true`へ変更し、README日英・Rust導入案内の「未公開／ソースのみ」を公開状態へ揃える。サイトと文書の既存チェックを通し、依頼後にPagesへ反映する。公開URLの新旧切り替え・全6パッケージ・チェックサム・マニュアル・報告窓口を確認する。Pythonの配布と既存URLは維持する |

公開後の問い合わせ先は既存の [不具合報告フォーム](../../.github/ISSUE_TEMPLATE/bug_report.yml) を使う。版・OS・GPU・機器・Fs／CH・再現手順を受け取り、問題版の案内・配布停止・修正版を [既存の運用](#失敗不完全draft問題版) へつなぐ。新しい報告システムの実装は不要。

### 初回公開の必須条件に追加しないもの

FRF／Bode・THD／IR・VST3、旧Python版の全機能移植、Generatorのスイープ／Mix、物理校正・実時計校正、全Fs・全CH・全機器の動作保証は後続とする。Developer ID／公証・Authenticode、Sigstore・統合チェックサム・VirusTotal、追加の性能計測基盤も初回の前提にしない。既存の署名状態・校正境界・確認範囲を利用者へ説明する。全9言語の初回翻訳・I6レビューは完了済みで、公開準備を理由に一括でやり直さない。

## 公開前の最小確認セット

これはR6のmacOS（Intel）で行う確認範囲であり、残作業全体をテストの完了待ちへ置き換えるものではない。P0は公開前必須、P1は必要に応じて確認する後続課題とする。配布物は同一候補SHAの通常release／desktop・qaなしを使い、起動・停止・保存復元を短く通す。精度・欠落・エラー処理は既存の自動テストと対象ソース・条件が一致する開発QAを再利用する。QA版での成功を配布実行ファイルの起動・操作確認と読み替えない。文書だけの更新では、実装・依存・ビルド条件の変更がないことを確認し、Rust全検証や実機評価を重複実行しない。

現在のIntel MacではGUI操作手段の技術的制約により、手動GUI操作チェックと実モニター間DPI操作を検証計画から除外する。この環境では該当するP0／P1の手動操作を公開前の未完了条件に数えず、対象外と記録する。実行可能な自動QA・数値・連続動作評価、配布物と実入出力の条件は維持する。手動操作のためだけにWindows・Linuxへ確認を広げない。詳細は [検証対象環境](VALIDATION.md#検証対象環境と既存成果物) を参照する。

測定・出力中のUSB抜去は [安全上の必須制約](VALIDATION.md#物理デバイスの安全制約) により実施しない。以下の再接続は入出力停止・ストリーム解放後に限る。抜去試験を公開前条件へ戻さない。

| 優先 | 項目 | 完了・判断の基準 |
| --- | --- | --- |
| P0 | Generator→同期2ch比較の代表条件 | 48 kHzの内部・BlackHole・UAC-232で同じ入力窓の独立照合、独立Stop、JSON／CSV・別プロセスOFF復元・明示Start後の再測定。REF／SIG交換、低REF・欠落、ERROR保持・解放は既存の自動QAを使う |
| P0 | 配布物の短い通し確認 | macOS Intelで入出力選択→測定→独立停止→保存→再起動・OFF復元を行う。通常幅・狭幅の主要値・単位・無効理由・停止操作を確認する。変更のない全メニュー・カード操作・波形・配色の網羅を繰り返さない |
| P0 | OS／CPU別パッケージとCI | 配布対象のWindows MSVC Setup／ZIP、Linux AppImage／tar.gz、macOS Intel／arm64 DMGを既存のCIで検証する。実機確認は利用可能な環境で行い、未確認OS・GPU・機器と権限操作をリリースノートに明記する |
| P0 | 最終資産と公開内容の一致 | 受け入れた実行ファイルと最終資産のハッシュ、実測・失敗・未確認を記すリリースノート、Prerelease=true・Latest=false、Python v0.9.1維持 |
| P1 | 高Fs・多ch・負荷・再接続 | 物理4〜16ch、UAC-232の192 kHz起動欠落、最大設定、長時間・反復撮影・繰り返し再接続は関連変更や不具合調査に応じて実施する。再接続は停止・解放後に限る |
| P1 | 表示・環境差 | 実モニター間DPI、実表示遅延、他OS・機器のGUI／権限操作は必要な環境で追加確認する |

候補SHA・実行ファイルSHA-256・環境／機器／Fs・判定・証拠の場所を [配布パッケージの受け入れ](VALIDATION.md#配布パッケージの受け入れ) のGit管理外ディレクトリへ残す。同じ条件の証拠は再利用し、未確認範囲を合格へ広げない。600秒・全経路・全形式の実機再実行を毎回の公開条件にしない。Windows・Linuxのユーザー確認、Apple Silicon実機の未確認は別に記し、エージェントの追加試験を公開条件にしない。最終資産・Draftがまだない場合、その一致確認は未実施とする。

## PRの実機検証用Artifacts

main宛PRとCIの手動実行では、[CI](../../.github/workflows/ci.yml) から既存のOS別パッケージworkflowを呼び出す。PRの変更ファイルにかかわらず4種類を同じrunのArtifactsへ集める。PRのChecksからCIの実行詳細を開き、各ジョブのSummaryのリンク、またはArtifacts一覧から対象をダウンロードする。OS別workflowの手動実行も同じ検証用構成を使う。保持期間は14日。

| Artifact名 | ZIP展開後のパッケージ | 起動手順 |
| --- | --- | --- |
| `MeasureLab-windows-x64-installer` | `MeasureLab-v<version>-windows-x64-setup.exe` | インストーラーを直接起動し、インストール後にMeasureLab (Rust)を開く |
| `MeasureLab-macos-x86_64-dmg` | `MeasureLab-v<version>-macos-x86_64.dmg` | Intel MacでDMGを開き、Applicationsへコピーして取り出した後に起動 |
| `MeasureLab-macos-arm64-dmg` | `MeasureLab-v<version>-macos-arm64.dmg` | Apple Silicon MacでDMGを開き、同様にコピー・取り出し後に起動 |
| `MeasureLab-linux-x86_64-appimage` | `MeasureLab-v<version>-linux-x86_64.AppImage` | `chmod +x`で実行権限を付け、AppImageを起動。FUSEが使えなければ`--appimage-extract-and-run`を付ける |

GitHubが作るZIPは一度だけ展開する。各ZIP直下は上記パッケージ1個、`README.txt`、同名の`-build-info.json`、`SHA256SUMS-<OS>-<CPU>.txt`の4ファイルで統一する。portable ZIP・AppDir tar.gzやビルド中間ファイルは入れない。Linuxの実行権限はGitHubのZIPで保持されないため、起動説明にも権限付与を記載する。Python・Rustの導入は不要で、ホスト側のOS・GPU・音声ランタイムと権限条件は各OSの説明に従う。

既存のWindowsインストール・修復・削除、macOS DMG・署名・コピー後起動の検証を再利用する。LinuxはアップロードしたAppImageをUbuntu 22.04／24.04／26.04へダウンロードし、全payload・通常オプション・GPU読み戻しを検証する。検証用の選択処理は[ci_artifacts.py](../../scripts/ci_artifacts.py)に集約し、成果物の完全な集合、非空の通常ファイル、SHA-256、cleanなソースSHA、版・CPU・release／desktopを確認する。不足・破損・別ソース・QA版はCIを失敗させる。

Windowsのインストールログは`logs-windows-installer-tests`へ分離し、7日保持する。元の配布用ステージングとportable形式の検証は継続し、Release workflowには従来の全資産を渡す。PRとブランチの実行は検証用で、Release・タグ・サイト公開を行わない。build-infoのSHAはPRではheadとbaseを統合したテスト対象のコミットである。各パッケージジョブとLinuxの実行検証が成功したrunを使用し、通常GUI・実音声・権限ダイアログの実機受け入れは別途行う。

## Windows配布

[Windows Packages](../../.github/workflows/build_windows.yml) はPRのCI、手動実行、Release workflowから呼び出す。Rust 1.99.0の`x86_64-pc-windows-msvc`を使い、`--release --locked --no-default-features --features desktop`でビルドする。CRTを静的リンクし、利用者へのPython・Rust・Visual C++再頒布可能パッケージの別途導入を不要にする。Windows 10／11 x64を対象とし、ARM64上のx64エミュレーションは受け入れ対象に含めない。

Inno Setup 6.7.3は公式配布のSHA-256を固定して取得する。Rust版のAppId、新規インストール先`%LOCALAPPDATA%\Programs\MeasureLabRust`、ショートカット`MeasureLab (Rust)`はPython最終版と分ける。既定のフォルダー名は空白を含まない。更新はRust版の同じ場所・タスクを引き継ぎ、旧既定の`MeasureLab Rust`や利用者が選んだ場所も自動では移動しない。アンインストールはパッケージ所有ファイルを削除し、設定・測定結果は残す。ASIO切り替え・PyInstaller・旧Pythonランタイムは含めない。

Release workflow用の`windows-x64` artifactは以下の4ファイルを含む。版番号はCargoから取得し、タグ実行では完全一致を要求する。実行ごとに新しいステージングディレクトリを使い、過去の成果物を混ぜない。

* `MeasureLab-v<version>-windows-x64-setup.exe`
* `MeasureLab-v<version>-windows-x64.zip`
* `MeasureLab-v<version>-windows-x64-build-info.json`
* `SHA256SUMS-windows-x64.txt`

build-infoはソースSHA・ローカル変更の有無・対象・機能・Rust版・実行ファイルのSHA-256を記録し、ZIPとインストーラーにも同梱する。インストーラーとZIPのテストは日本語・空白を含むパス、実行ファイルの`--help`、QA専用オプションの拒否、ペイロードのハッシュ、ユーザー単位の登録、ショートカット、修復再インストール、データ保持、削除を検証する。通常GUI・GPU・音声の受け入れは別途必要である。

初回は現在の実行ファイル・インストーラーのAuthenticode未署名状態を案内する。SHA-256は同一性確認であり、Windowsの発行元認証ではない。SmartScreenでの扱い、MSVC版の通常GUI・実入出力・保存復元は配布前の確認として残す。署名証明書の整備は後続改善とする。ローカル作成は [Windows手順](WINDOWS.md#windows配布パッケージの作成) を参照する。

## Linux配布

[Linux Packages](../../.github/workflows/build_linux.yml) はPRのCI、手動実行、Release workflowから呼び出す。Rust 1.99.0の`x86_64-unknown-linux-gnu`をUbuntu 22.04で使い、`--release --locked --no-default-features --features desktop`でビルドする。日常開発のUbuntu 24.04／26.04環境に22.04を導入する必要はない。公式の基準環境はクラウドrunnerで用意する。

Release workflow用の`linux-x86_64` artifactは以下の4ファイルを含む。実行ごとの空のステージング先を使い、AppImageとtar.gzに同じ通常実行ファイル・AppRun・アイコン・版情報・ライセンス・起動説明を入れる。

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

[macOS Packages](../../.github/workflows/build_macos.yml) はPRのCI、手動実行、Release workflowから呼び出す。Rust 1.99.0でIntelの`x86_64-apple-darwin`とApple Siliconの`aarch64-apple-darwin`を各ネイティブrunnerでビルドする。通常desktopだけを`--release --locked --no-default-features --features desktop`で指定し、QA版と分けた`target/distribution-macos/`を使う。`MACOSX_DEPLOYMENT_TARGET=13.0`とInfo.plistの最低版を一致させ、Mach-OのCPU・最低OS版・システム外への動的リンクを検査する。13.0はビルド下限であり、全OS版・機器の動作確認を意味しない。

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
3. [配布パッケージの受け入れ](VALIDATION.md#配布パッケージの受け入れ) を同じ配布実行ファイルで行う。エージェントはmacOS Intel、Windows・Linuxはユーザーが確認する。OS・CPU別の未実施、失敗と既知の問題を区別し、受け入れ範囲を利用者文書とリリースノートへ反映する。ソース修正後は新しい候補SHAへ戻り、変更の影響がある範囲を担当に従って再確認する。
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
| `compatibility`（任意） | macOS／WindowsのQAテスト。通常desktop releaseはmain Pushで3 OSをビルドし、PR／手動ではパッケージジョブと重複させない |
| OS別パッケージ（任意） | PR／手動CIの4種類の実機検証用Artifacts。同じrunに完成済みパッケージを集め、各OSのパッケージ・実行検証を行う |
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
* macOS IntelのGPU／音声・長時間評価で既存の証拠を再利用し、追加確認の対象SHAと条件をQA成果物に保存する。Windows・Linuxはユーザー確認と不具合報告に応じた調査を基本とし、全OSの評価環境整備を初回公開の前提にしない。
* 旧版のURLと原本の意味を維持する。Pythonアプリの機能追加・旧テスト環境の復元は再開しない。
