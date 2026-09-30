# Native evaluation environment

MIG-001の開発環境準備とMIG-004-AのQt境界プローブ。Rust/QMLの採用・公開API・製品クレート境界は未決定。
[進捗](../migration/status.md)と[参照環境](../migration/environment.md)を先に確認する。
MIG-002の[コア契約](../migration/contracts/core.md)と[後続作業票](../migration/tasks.md)を作成済み。
MIG-004-AでCargo workspace/lockと同じ小さなQML画面を追加した。
`probe-core`はGUI非依存の模擬worker、`cxxqt-probe`/`qtbridge-probe`は薄いQt adapter。
MIG-006-Aの`dsp-core`はGUI非依存のFFT/窓/単位/PSD候補。[FFT比較手順](fft-candidate.md)を参照。
006-Bの`graph-core`は固定DAG・共有FFT結果・購読token・独立平均・容量制限付きcacheの候補。
[共有graphの手順](shared-graph.md)を参照。音声backendと実取得schedulerは未実装。
[Qt SDK・比較画面の起動手順](qt-probe.md)を参照。
004-Bの開発反復とローカルbundleは[反復測定手順](qt-iteration.md)へ分離する。

## このworktreeで使う

コマンドはリポジトリのルートで実行する。導入済みのローカルツールを現在のシェルで有効にする。

```bash
export CARGO_HOME="$PWD/.tools/cargo"
export RUSTUP_HOME="$PWD/.tools/rustup"
export PATH="$CARGO_HOME/bin:$PWD/.tools/build-venv/bin:$PATH"
migration_rust_version="$(./.venv/bin/python -c 'import tomllib; print(tomllib.load(open("native/rust-toolchain.toml", "rb"))["toolchain"]["channel"])')"
rustc +"$migration_rust_version" -Vv
cargo +"$migration_rust_version" -V
rustup component list --toolchain "$migration_rust_version" --installed
cmake --version
ninja --version
clang++ --version
```

`CARGO_HOME`と`RUSTUP_HOME`も必要。PATHだけを変更すると、ユーザー共通のRust設定を参照してしまう。
別のworktreeから戻った場合はルートに移動してから設定し直す。
`rust-toolchain.toml`は`native/`以下に適用されるため、ルートからのコマンドでは明示的に`+version`を指定する。

## 新しい環境への導入

[Rust公式のインストール手順](https://doc.rust-lang.org/book/ch01-01-installation.html)と
[rustupの配布方法](https://github.com/rust-lang/rustup/blob/main/doc/user-guide/src/installation/other.md)に従う。
以下の例は初回に確認した**macOS Intel**用。別OS/CPUではhost tupleをその環境に合わせる。

先に上の環境変数と`migration_rust_version`を設定する。Rust未導入ならバージョン確認コマンドは導入後に実行する。

```bash
mkdir -p .tools/downloads
curl --proto '=https' --tlsv1.2 -fsSL https://static.rust-lang.org/rustup/dist/x86_64-apple-darwin/rustup-init -o .tools/downloads/rustup-init
curl --proto '=https' --tlsv1.2 -fsSL https://static.rust-lang.org/rustup/dist/x86_64-apple-darwin/rustup-init.sha256 -o .tools/downloads/rustup-init.sha256
./.venv/bin/python - <<'PY'
import hashlib
from pathlib import Path

installer = Path(".tools/downloads/rustup-init")
expected = Path(str(installer) + ".sha256").read_text().split()[0]
actual = hashlib.sha256(installer.read_bytes()).hexdigest()
if actual != expected:
    raise SystemExit("rustup-init SHA-256 mismatch")
print("rustup-init SHA-256 verified:", actual)
PY
```

ハッシュ一致・終了コード0を確認してから実行する。`--no-modify-path`でシェル設定ファイルを変更しない。
default設定も上で指定したworktree内のRUSTUP_HOMEに保存される。

```bash
chmod +x .tools/downloads/rustup-init
.tools/downloads/rustup-init -y --no-modify-path --profile minimal --default-toolchain "$migration_rust_version" --component rustfmt --component clippy
python3.12 -m venv .tools/build-venv
.tools/build-venv/bin/python -m pip install -r native/build-requirements.txt
```

Rust本体・componentsは`rust-toolchain.toml`、CMake/Ninjaは`build-requirements.txt`で固定する。
Qt開発SDKは[qt-sdk.toml](qt-sdk.toml)、CXX-Qt/Qt Bridge/CXXは[Cargo.toml](Cargo.toml)と[Cargo.lock](Cargo.lock)で固定した。
現行PyQtのQt runtimeと開発用SDKのパスを混在させない。

## ビルド・リンクのスモーク

ローカルの使い捨てプロジェクトで確認する。これは製品コードや測定処理の検証ではない。
上の環境変数を設定したシェルで実行する。

```bash
test -f .tools/rust-smoke/Cargo.toml || cargo +"$migration_rust_version" new --vcs none --name measurelab_toolchain_smoke .tools/rust-smoke
cargo +"$migration_rust_version" generate-lockfile --manifest-path .tools/rust-smoke/Cargo.toml
cargo +"$migration_rust_version" run --locked --manifest-path .tools/rust-smoke/Cargo.toml
cargo +"$migration_rust_version" fmt --manifest-path .tools/rust-smoke/Cargo.toml --check
cargo +"$migration_rust_version" clippy --locked --manifest-path .tools/rust-smoke/Cargo.toml -- -D warnings
```

初回はCargo生成の`Hello, world!`がコンパイル・リンク・実行でき、rustfmtとClippyが成功した。
C++側も最小のC++17実行物をCMake/Ninjaで確認した。再生成する場合は以下を使う。

```bash
mkdir -p .tools/cmake-smoke
cat > .tools/cmake-smoke/CMakeLists.txt <<'CMAKE'
cmake_minimum_required(VERSION 3.21)
project(MeasureLabToolchainSmoke LANGUAGES CXX)
add_executable(toolchain_smoke main.cpp)
target_compile_features(toolchain_smoke PRIVATE cxx_std_17)
CMAKE
cat > .tools/cmake-smoke/main.cpp <<'CPP'
#include <iostream>
int main() { std::cout << "C++ toolchain OK\n"; }
CPP
cmake -S .tools/cmake-smoke -B .tools/cmake-smoke/build -G Ninja
cmake --build .tools/cmake-smoke/build
.tools/cmake-smoke/build/toolchain_smoke
```

これらのHello worldスモークはmacOS Intelでのツール単体の確認。
Qtとの接続は別の[共通プローブ](qt-probe.md)で確認し、配布・他OS/CPUは後続検証とする。
`.tools/`は再構築可能なGit管理外データとして扱う。
