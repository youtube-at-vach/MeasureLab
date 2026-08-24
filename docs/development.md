# 開発者向けガイド (Development)

## 概要

ソースコードからの実行や、開発環境のセットアップ方法について説明します。

## 🐍 ソースコードから実行する場合

> [!IMPORTANT]
> Python 3.12 以上

### 🚀 自動セットアップスクリプト（推奨）

Linux（apt環境）および macOS 向けに、OSパッケージのインストールから仮想環境（`.venv`）の構築、必要なPython依存パッケージやNode.jsなどの開発ツールのインストールまでを自動化する便利なスクリプトが用意されています。

ターミナルを開き、リポジトリのルートディレクトリで以下のコマンドを実行するだけで準備が整います：

```bash
./scripts/setup_dev_env.sh
```

Linux で `apt` が使えない環境（例: Gentoo）や管理者権限が使えない環境では、スクリプトは OS パッケージの自動導入をスキップし、必要パッケージの案内を表示した上で venv/pip セットアップを続行します。
実行中、macOS では MacPorts のデフォルト設定など、いくつかの確認が求められる場合があります。

セットアップ完了後は、以下のコマンドで仮想環境を有効化してからアプリケーションを起動してください。

```bash
source .venv/bin/activate
python main_gui.py
```

### 🛠️ 手動でセットアップする場合

自動スクリプトを使用せず、各環境に合わせて手動で構築したい場合は、以下の手順を参照してください。

#### Linux / Ubuntu: 手動で仮想環境 (venv) を構築する

リリース版（AppImage/ZIP）はそのまま動作しますが、ソースコードから実行する場合に **APT（OSパッケージ）の Python 依存（例: PyQt6 など）が古くて動かない**ことがあります。
そのため Linux では、**システムの Python はそのまま使いつつ、依存パッケージは venv + pip で入れる**運用を推奨します。

1. OS 依存ライブラリ（最低限）を入れます。
    * `sounddevice` は PortAudio を利用するため、実行時に `libportaudio2` が必要です。
    * `soundfile` は libsndfile を利用するため、実行時に `libsndfile1` が必要です。

    ```bash
    sudo apt update
    sudo apt install -y python3 python3-venv python3-pip libportaudio2 libsndfile1
    ```

    もし `pip install` でビルドエラーが出る場合のみ、追加で開発ヘッダ等を入れてください：

    ```bash
    sudo apt install -y build-essential portaudio19-dev libsndfile1-dev
    ```

2. 仮想環境を作成して有効化します（例: リポジトリ直下に `.venv`）。

    ```bash
    python3 -m venv .venv
    source .venv/bin/activate
    python -m pip install -U pip
    ```

    以降は `python` / `pip` が venv を指します（`sudo pip` は使わないでください）。

    `activate` を使わずに実行したい場合は、常に venv の Python を直接呼び出してもOKです：

    ```bash
    ./.venv/bin/python -m pip install -U pip
    ./.venv/bin/python -m pip install -c constraints.txt -r requirements.txt
    ./.venv/bin/python main_gui.py
    ```

3. リポジトリをクローンします。
4. 依存関係をインストールします（再現性のため constraints を利用）：

    ```bash
    pip install -c constraints.txt -r requirements.txt
    ```

5. アプリケーションを起動します：

    ```bash
    python main_gui.py
    ```

#### macOS: MacPorts + Python 3.12 + pyFFTW を使用する場合

（macOS 13 以降で動作確認済み）

macOS で `pyFFTW` をインストールする場合、パッケージマネージャ（MacPorts 推奨）でインストールした FFTW ライブラリを明示的に指定する必要があります。

1. MacPorts の更新と必要パッケージのインストール：

    ```bash
    sudo port selfupdate
    sudo port install python312 py312-pip fftw-3 fftw-3-single
    ```

2. Python のバージョン選択：

    ```bash
    sudo port select --set python python312
    sudo port select --set python3 python312
    ```

    設定後、ターミナルを再起動してください。

3. 仮想環境の作成と有効化：

    ```bash
    python3.12 -m venv .venv
    source .venv/bin/activate
    python -m pip install -U pip
    ```

4. pyFFTW のインストール（FFTW のパスを明示指定）：

    ```bash
    python -m pip cache remove pyfftw
    PYFFTW_FFTW_PREFIX=/opt/local \
    python -m pip install pyfftw --no-binary pyfftw
    ```

5. 依存パッケージのインストール：

    ```bash
    python -m pip install -c constraints.txt -r requirements.txt
    ```

### 🛠️ 開発向けセットアップ

テストやLint/型チェック、ドキュメントのビルドを実行する場合は追加のパッケージをインストールしてください。

* **コード開発（テスト/Lintなど）**:

    ```bash
    pip install -c constraints.txt -e ".[dev]"
    ```

    zsh を使用している場合は `.[dev]` を `".[dev]"` のように引用符で囲む必要があります。

* **ドキュメント開発（MkDocs）**:

    ```bash
    pip install -c constraints.txt -r requirements-docs.txt
    ```

* Lint: `ruff check .`
* Format check: `ruff format --check .`
  `ruff format .` による全体フォーマットは通常実行せず、確認に失敗した場合も変更したファイルだけを必要に応じてフォーマットします。
* Type check: `mypy src`
* Tests: `pytest`（ハードウェア/GUI依存テストは環境変数が必要; CIではデフォルトでスキップ）

### 🤖 開発支援スキル拡張 (Skill Extensions)

MeasureLabのプロジェクトでは、開発ワークフローを自動化・支援するためのプロジェクトレベルのスキル拡張機能（Slash Commands）が用意されています。これらはGitHub Copilot CLIなどのMCP対応ツールから利用できます。

* **/ci-prechecker**: PR作成前に、Ruff(Lint)、Mypy(型チェック)、翻訳キー整合性、Markdown Lint、Pytestなどをローカルで一括実行し、CI要件を満たしているか事前検証します。
* **/multilingual-translator**: プロジェクト全体の翻訳ファイルの整合性をチェックし、不足しているキーの追加から翻訳の最終検証までを自動で行います。
* **/pr-reviewer**: Pull Requestのコード変更を取得し、ロジックの正確性、スタイル、テスト・ドキュメント、CI/安全性の観点からコードレビューを自動実施します。
* **/release-manager**: CHANGELOGの更新、ドキュメントの記述確認、バージョン番号の同期、UI変更時のスクリーンショット更新、リリースPRの作成など、リリース準備を支援します。

仕様詳細や各スキルの使い方については、リポジトリ内の `.github/extensions/` 以下のMarkdownファイルを参照してください。
