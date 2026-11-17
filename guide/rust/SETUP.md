# Rust 開発環境のセットアップ

新しい環境でRustアプリ、ダウンロードサイト、公開マニュアルを開発するための手順です。[setup_dev_env.sh](../../scripts/setup_dev_env.sh)はツールをリポジトリ内に導入します。

## 自動セットアップ

macOSとglibcを使うLinuxのx86_64／ARM64に対応します。リポジトリをクローンした後、ルートで実行してください。

```sh
./scripts/setup_dev_env.sh --install-os-deps
source .tools/env.sh
./scripts/debug.sh
```

`--install-os-deps`はLinuxでapt-getからOSライブラリを導入し、macOSではXcodeツールの導入を確認します。必要な場合はsudoのパスワード入力があります。スクリプト全体をsudoで実行せず、通常のユーザーで起動してください。

引数なしのセットアップは依存関係を整え、`dev-fast`と文書用ライブラリの読み込みを確認します。OSのライブラリを導入済みなら `--install-os-deps` は省略できます。全体を確認する場合は `--verify` を追加し、Rustの共通チェック、サイトとPagesのビルド、Ruff、Markdown lint、actionlintを実行します。日常の確認コマンドは[検証ガイド](VALIDATION.md)を参照してください。

移行先では `target/`、`.tools/`、`.venv/`、`download-site/node_modules/`、`site/` をセットアップとビルドで再生成できます。`dist/` の実機証拠、測定設定・結果の保存ファイル、[起動設定](README.md#起動設定の自動保存復元)は必要分を引き継ぎ、移行先で使用するデバイスを確認してください。初回のセットアップはネットワーク接続が必要です。

## OSごとの事前準備

### macOS

Git、curl、tar、SHA-256ツールとXcode Command Line Toolsが必要です。Command Line Toolsが未導入の場合は、次を実行して画面上のインストールを完了してください。

```sh
xcode-select --install
```

RustのAudio I/OはCoreAudio、FFTはRustFFTを使います。停止中のPDFプラグインをWebビルドから外したため、マニュアル生成にMacPorts・Pango・WeasyPrintは不要です。

### Linux

Git、curl、tar、SHA-256ツールとC/C++コンパイラが必要です。Debian／Ubuntuでは、事前準備に次のコマンドを使えます。

```sh
sudo apt-get update
sudo apt-get install -y git curl ca-certificates tar build-essential pkg-config
```

`--install-os-deps`はALSA、X11、Wayland、xkbcommonの開発用ライブラリを導入します。apt-get以外の環境では、次に相当するパッケージをディストリビューションの手順で導入し、このオプションを省略してください。

```sh
sudo apt-get install -y build-essential pkg-config \
    libasound2-dev libxkbcommon-dev libwayland-dev libx11-dev \
    libxrandr-dev libxi-dev libxcursor-dev
```

### Windows

このBashスクリプトによるネイティブWindowsのセットアップには対応していません。[Windowsでのビルドと起動確認](WINDOWS.md#msvcでのセットアップ)のPowerShell手順で、標準のMSVCツールチェーンとVisual Studio C++ Build Tools／Windows SDK、サイト・文書用ツールを準備してください。Windowsの仮想環境は`.venv/Scripts/`を使います。Visual Studioを導入しない環境向けのGNU／LLD手順は同文書の別節に分けています。

### その他の環境

muslを使うLinuxやその他のCPUは手動セットアップの対象です。[Rust README](README.md#起動) と [検証ガイド](VALIDATION.md) を参照してください。

## 導入先とツール

| 対象 | スクリプトで導入する版・内容 | 導入先 |
| --- | --- | --- |
| Rust | 1.99.0、rustfmt、Clippy（アプリの最小要件は1.95） | `.tools/cargo/`、`.tools/rustup/` |
| Node.js | 24.21.0、付属のnpm | `.tools/node/` |
| Python | uv 0.12.23で導入するPython 3.13系 | `.tools/python/` |
| 文書・Python lint | `requirements-docs.txt`とRuff | `.venv/` |
| サイト | `download-site/package-lock.json`に従う依存関係 | `download-site/node_modules/` |
| Markdown lint | markdownlint-cli2 0.23.3 | `.tools/lint/` |
| GitHub Actions lint | actionlint 1.7.12 | `.tools/bin/` |

Rustは公式rustup、Node.js・uv・actionlintは配布元のバイナリを使用します。アーカイブは配布元のSHA-256値で検証してから展開します。Pythonは [uvが提供するPython配布](https://docs.astral.sh/uv/guides/install-python/) を使います。文書用Pythonパッケージは現在の`requirements-docs.txt`に従い、完全に版を固定した環境ではありません。

これらの導入先はGit管理の対象外です。シェルの起動設定、OSの既定Python／Node.js、Gitの名前・メール・認証設定は変更しません。既存の`.venv`はPython 3.12以降の仮想環境なら再利用し、古い版や壊れた環境はエラーとして扱います。必要な内容を確認して別名に移してから再実行してください。

## セットアップ後の使い方

新しいターミナルでは、リポジトリのルートでローカルツールのPATHを読み込みます。

```sh
source .tools/env.sh
cargo --version
node --version
python --version
```

PATHを読み込まずに `./scripts/cargo.sh` と `./scripts/debug.sh` を使うこともできます。起動プロファイルは[開発ビルドと時間計測](VALIDATION.md#開発ビルドと時間計測)、OS・機器を使う確認は[GUI・入出力QA](VALIDATION.md#gui入出力qaの再実行)を参照してください。BlackHole・物理機器は使用する経路に応じて用意します。

## ChatGPTアプリからの起動と検証

[ローカル環境のアクション](https://learn.chatgpt.com/docs/environments/local-environment)を[`.codex/environments/environment.toml`](../../.codex/environments/environment.toml)に保存しています。ChatGPTデスクトップアプリのCodexで、このリポジトリのルートをプロジェクトとして開くと、アクション欄から起動・検証を選べます。macOSとWindowsには同名の操作をOS別に登録しています。

| アクション | 実行する内容 |
| --- | --- |
| GUI 起動 | `dev-fast`・通常版を更新して`--compact`で起動。入出力は停止から開始 |
| CLI 起動確認 | 通常版を更新し、アプリの`--help`を確認して終了 |
| GPU 描画確認 | 通常版で`--gpu-smoke`を実行。対応GPUとデスクトップが必要 |
| コアテスト | GUIなしのRustテスト |
| 全 Rust テスト | 全ターゲット・全機能のRustテスト。benchは各条件1回 |
| Rust 静的検査 | 全ターゲット・全機能のClippy |

macOSは既存の`debug.sh`／`cargo.sh`、Windowsは`pwsh.cmd`から`debug.ps1`／`cargo.ps1`を呼びます。Windowsではプロジェクト内の`.tools/powershell/pwsh.exe`を優先し、なければPATH上のPowerShell 7を使います。CargoもPATH上またはプロジェクト内の`.tools/cargo/`を利用します。個人の絶対パスやシェルの起動設定は共有ファイルへ保存しません。

依存関係の導入はOSごとの手順で先に行ってください。自動セットアップ欄は空にしているため、新しいworktreeでツールの導入やGUI起動は自動実行しません。画面のクリック・撮影を行うComputer Useのアクセス許可は、このアクション設定とは別にアプリ側で管理されます。

起動処理の回帰検証は`python -m unittest discover -s scripts -p 'test_dev_actions.py'`です。記録用の偽Cargoへ置き換え、日本語・空白入りパス、引数、プロファイル、`qa`の明示指定、終了コードを確認します。実GUI・音声・GPUは起動しません。CIではLinuxの必須チェックと、macOS／Windowsの互換性ジョブで実行します。
