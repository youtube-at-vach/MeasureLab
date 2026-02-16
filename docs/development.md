# 開発者向けガイド (Development)

ソースコードからの実行や、開発環境のセットアップ方法について説明します。

## 🐍 ソースコードから実行する場合

**必要条件**: Python 3.12 以上

### Linux / Ubuntu（推奨）: 仮想環境 (venv) で実行する

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

### 🛠️ 開発向けセットアップ

テストやLint/型チェックを実行する場合は開発ツールもインストールしてください。

```bash
pip install -c constraints.txt -e .[dev]
```

- Lint: `ruff check src scripts tests`
- Type check: `mypy src`
- Tests: `pytest`（ハードウェア/GUI依存テストは環境変数が必要; CIではデフォルトでスキップ）
