# 開発者向けガイド (Development)

ソースコードからの実行や、開発環境のセットアップ方法について説明します。

## 🐍 ソースコードから実行する場合

**必要条件**: Python 3.12 以上

### 🚀 自動セットアップスクリプト（推奨）

Linux (Ubuntu) および macOS 環境向けに、OSパッケージのインストールから仮想環境（`.venv`）の構築、必要なPython依存パッケージやNode.jsなどの開発ツールのインストールまでを自動化する便利なスクリプトが用意されています。

ターミナルを開き、リポジトリのルートディレクトリで以下のコマンドを実行するだけで準備が整います：

```bash
./scripts/setup_dev_env.sh
```

※ 実行中、パスワードの入力やMacPortsでのデフォルト設定など、いくつかの確認が求められる場合があります。

セットアップ完了後は、以下のコマンドで仮想環境を有効化してからアプリケーションを起動してください。

```bash
source .venv/bin/activate
python main_gui.py
```

---

### 🛠️ 手動でセットアップする場合

自動スクリプトを使用せず、各環境に合わせて手動で構築したい場合は、以下の手順を参照してください。

#### Linux / Ubuntu: 手動で仮想環境 (venv) を構築する

リリース版（AppImage/ZIP）はそのまま動作しますが、ソースコードから実行する場合に **APT（OSパッケージ）の Python 依存（例: PyQt6 など）が古くて動かない**ことがあります。
そのため Linux では、**システムの Python はそのまま使いつつ、依存パッケージは venv + pip で入れる**運用を推奨します。

1. OS 依存ライブラリ（最低限）を入れます。
    - `sounddevice` は PortAudio を利用するため、実行時に `libportaudio2` が必要です。
    - `soundfile` は libsndfile を利用するため、実行時に `libsndfile1` が必要です。

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

    ※ `activate` を使わずに実行したい場合は、常に venv の Python を直接呼び出してもOKです：

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
    sudo port install python312 py312-pip fftw-3
    ```

2. Python のバージョン選択：

    ```bash
    sudo port select --set python python312
    sudo port select --set python3 python312
    ```

    ※ 設定後、ターミナルを再起動してください。

3. 仮想環境の作成と有効化：

    ```bash
    python3.12 -m venv .venv
    source .venv/bin/activate
    python -m pip install -U pip
    ```

4. pyFFTW のインストール（FFTW のパスを明示指定）：

    ```bash
    PYFFTW_FFTW_PREFIX=/opt/local \
    python -m pip install pyfftw --no-binary pyfftw
    ```

5. 依存パッケージのインストール：

    ```bash
    python -m pip install -c constraints.txt -r requirements.txt
    ```

### 🛠️ 開発向けセットアップ

テストやLint/型チェック、ドキュメントのビルドを実行する場合は追加のパッケージをインストールしてください。

- **コード開発（テスト/Lintなど）**:

    ```bash
    pip install -c constraints.txt -e ".[dev]"
    ```

    ※ zsh を使用している場合は `.[dev]` を `".[dev]"` のように引用符で囲む必要があります。

- **ドキュメント開発（MkDocs）**:

    ```bash
    pip install -c constraints.txt -r requirements-docs.txt
    ```

- Lint: `ruff check src scripts tests`
- Type check: `mypy src`
- Tests: `pytest`（ハードウェア/GUI依存テストは環境変数が必要; CIではデフォルトでスキップ）
