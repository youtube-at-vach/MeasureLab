# Oscilloscope Split State (State C) Plan

## Top-Level Overview

### 目標

`OscilloscopeWidget` に新しいウィンドウ状態 **State C（Split）** を追加する。

State C では、現在ひとつの `QWidget` にまとまっているウィジェットを、
**ディスプレイ部（左パネル）** と **コントロール部（右パネル）** の2つの独立した `QMainWindow` に分離して表示する。

### 現在の状態定義

| 状態 | 名称 | 説明 |
|------|------|------|
| A | 通常（デフォルト） | ディスプレイ部 + コントロール部が1つの `QWidget` に収まっている |
| B | Detached | ウィジェット全体が `IndependentWindow`（QMainWindow）に分離される |
| C | **Split（新規）** | ディスプレイ部と コントロール部がそれぞれ別の `QMainWindow` になる |

### 状態遷移

```
A ──[Detach]──► B ──[Split]──► C
A ──[Split]──────────────────► C
C ──[どちらかのウィンドウを閉じる or Reattach All]──► A
B ──[Reattach or ウィンドウ閉じる]──► A
```

### スコープ

- **対象:** `OscilloscopeWidget` のみ（他ウィジェットへの汎用化は今回スコープ外）
- **スコープ外:** コンパクトモードの意味論変更（別課題として後回し）
  - ただし State C でのコンパクトモードは「ディスプレイ部ウィンドウにのみ適用」という前提を維持する

---

## 設計方針

### OscilloscopeWidget の分割

現在の `OscilloscopeWidget.init_ui()` は以下の構造：

```
QHBoxLayout
  ├─ left_layout (stretch=1)   ← ディスプレイ部 (PlotWidget, Measurements, Cursors)
  └─ right_widget (fixed 250px) ← コントロール部 (TabWidget with General/Tools)
```

State C のために：
- `left_layout` の内容を `self.display_widget`（`QWidget`）にラップする
- `right_widget` は現状維持（すでに `QWidget`）
- `init_ui` の `QHBoxLayout` に `display_widget` と `right_widget` を並べる構造は変えない
- State C 遷移時：`display_widget` と `right_widget` を親から切り離し、それぞれ別の `QMainWindow` に移す

### DetachableWidgetWrapper の拡張

`DetachableWidgetWrapper.init_ui()` のヘッダーに **「Split」ボタン** を追加する。

- State C 固有の状態フラグ `is_split: bool` を追加
- `split()` メソッド：`display_widget` 用と `control_widget` 用の2つの `IndependentWindow` を生成
- `reattach_all()` メソッド：両ウィンドウを閉じて State A に戻す
- どちらかのウィンドウの `closed` シグナルが `reattach_all()` を起動する

### SplittableWidgetInterface の導入

`OscilloscopeWidget` が Split に対応していることを `DetachableWidgetWrapper` に伝えるためのインターフェースを新規作成する。

```python
class SplittableWidgetInterface:
    def get_display_widget(self) -> QWidget: ...
    def get_control_widget(self) -> QWidget: ...
```

`OscilloscopeWidget` がこのインターフェースを実装することで、
`DetachableWidgetWrapper` が `isinstance` チェックで Split ボタンの表示有無を決定する。

---

## Sub-Tasks

---

### Sub-Task 1: `SplittableWidgetInterface` の新規作成

**Status:** `[x] done`

**Intent:**
`DetachableWidgetWrapper` が「このウィジェットは分割できる」と判断するための薄いインターフェースを作る。
将来的に他のウィジェットへの拡張を可能にしつつ、今回は定義のみ行う。

**Expected Outcomes:**
- `src/gui/widgets/splittable_interface.py` が存在する
- `SplittableWidgetInterface` クラスが `get_display_widget()` と `get_control_widget()` の2メソッドを持つ
- 両メソッドは `NotImplementedError` を raise する（サブクラスが実装必須）

**Todo List:**
1. `src/gui/widgets/splittable_interface.py` を新規作成する
2. `SplittableWidgetInterface` クラスを定義する（`QWidget` への依存なし、純粋な Python ミックスイン）
3. `get_display_widget(self) -> QWidget` を `NotImplementedError` で定義する
4. `get_control_widget(self) -> QWidget` を `NotImplementedError` で定義する

**Relevant Context:**
- 参考パターン: [`src/gui/widgets/compactable_interface.py`](src/gui/widgets/compactable_interface.py)

---

### Sub-Task 2: `OscilloscopeWidget` のディスプレイ部を `display_widget` にラップ

**Status:** `[x] done`

**Intent:**
`_setup_left_panel()` が返す `QVBoxLayout` の内容を、独立した `QWidget`（`self.display_widget`）に格納する。
これにより `display_widget` を `QMainWindow.setCentralWidget()` で独立ウィンドウに移動できるようにする。

**Expected Outcomes:**
- `self.display_widget: QWidget` が存在し、`meas_group`、`cursor_info_label`、`plot_widget`、`persistence_img` を含む
- `self.right_widget` は現状と変わらない
- `init_ui()` の `QHBoxLayout` は `display_widget` と `right_widget` を並べる構造になる
- 既存の動作（State A, B）に変化なし
- `update_compact_layout()` が `display_widget` の show/hide に関して正しく機能する（参照先はウィジェット内のオブジェクトなので変更不要）

**Todo List:**
1. `_setup_left_panel()` の戻り値を `QVBoxLayout` から `QWidget` に変更する
   - `QWidget` を作成し、そこに `QVBoxLayout` を設定して返す
2. `init_ui()` で `left_layout = self._setup_left_panel()` を `self.display_widget = self._setup_left_panel()` に変更する
3. `main_layout.addLayout(left_layout, stretch=1)` を `main_layout.addWidget(self.display_widget, stretch=1)` に変更する
4. `update_compact_layout()` が引き続き正しく動作することを確認する（`meas_group` 等の参照は `self.*` なので変更不要のはず）

**Relevant Context:**
- [`src/gui/widgets/oscilloscope.py` L581-595](src/gui/widgets/oscilloscope.py) — `init_ui`
- [`src/gui/widgets/oscilloscope.py` L597-668](src/gui/widgets/oscilloscope.py) — `_setup_left_panel`
- [`src/gui/widgets/oscilloscope.py` L1476-1483](src/gui/widgets/oscilloscope.py) — `update_compact_layout`

---

### Sub-Task 3: `OscilloscopeWidget` に `SplittableWidgetInterface` を実装

**Status:** `[x] done`

**Intent:**
Sub-Task 1 で作成した `SplittableWidgetInterface` を `OscilloscopeWidget` に実装する。
`get_display_widget()` は `self.display_widget` を、`get_control_widget()` は `self.right_widget` を返す。

**Expected Outcomes:**
- `OscilloscopeWidget` のクラス宣言に `SplittableWidgetInterface` が追加されている
- `get_display_widget()` が `self.display_widget` を返す
- `get_control_widget()` が `self.right_widget` を返す

**Todo List:**
1. `oscilloscope.py` の import に `SplittableWidgetInterface` を追加する
2. `OscilloscopeWidget` のクラス宣言に `SplittableWidgetInterface` を追加する
   - `class OscilloscopeWidget(QWidget, CompactableWidgetInterface, ComparableWidgetInterface, SplittableWidgetInterface)`
3. `__init__` で `SplittableWidgetInterface.__init__(self)` を呼ぶ（必要であれば）
4. `get_display_widget()` を実装する：`return self.display_widget`
5. `get_control_widget()` を実装する：`return self.right_widget`

**Relevant Context:**
- [`src/gui/widgets/oscilloscope.py` L551-559](src/gui/widgets/oscilloscope.py) — クラス宣言と `__init__`
- Sub-Task 1 で作成した `src/gui/widgets/splittable_interface.py`
- Sub-Task 2 完了後に `self.display_widget` が存在している前提

---

### Sub-Task 4: `DetachableWidgetWrapper` に Split 機能を追加

**Status:** `[x] done`

**Intent:**
`DetachableWidgetWrapper` のヘッダーに「Split」ボタンを追加し、`split()` / `reattach_all()` メソッドを実装する。
State C 遷移時に `display_widget` と `control_widget` を別々の `IndependentWindow` に表示し、
どちらかのウィンドウが閉じられたときに `reattach_all()` で State A に戻す。

**Expected Outcomes:**
- `SplittableWidgetInterface` を実装したウィジェットが `DetachableWidgetWrapper` に渡されると「Split」ボタンが表示される
- 「Split」ボタン押下で `split()` が呼ばれ、ディスプレイ部・コントロール部がそれぞれ独立ウィンドウに表示される
- `DetachableWidgetWrapper` 本体はプレースホルダー表示になる
- どちらかのウィンドウを閉じると `reattach_all()` が呼ばれ、両ウィンドウが閉じられて State A に戻る
- State B（Detach）中に Split ボタンを押した場合、State B のウィンドウを閉じてから State C に遷移する
- `is_split` フラグが状態管理に使われる
- 状態 C のとき「Detach」ボタンと「Split」ボタンは無効化（Enabled=False）される

**Todo List:**
1. `DetachableWidgetWrapper.__init__` に `is_split: bool = False` と `split_display_window`, `split_control_window` フィールドを追加する
2. `is_splittable` フラグを `isinstance(widget, SplittableWidgetInterface)` で設定する
3. `init_ui()` に Split ボタンを追加する
   - `is_splittable` のときのみ作成（`split_btn`）
   - `setEnabled(True)` で常に有効（State A/B から遷移可能）
   - ヘッダーの `Detach` ボタンの隣に配置する
4. `split()` メソッドを実装する：
   a. State B（Detached）のときは先に `reattach()` を呼んで State A に戻す
   b. `content_widget.get_display_widget()` と `content_widget.get_control_widget()` を取得する
   c. `display_widget` の親ウィジェット（`OscilloscopeWidget` 本体）から切り離す
   d. `control_widget` （`right_widget`）を `OscilloscopeWidget` 本体から切り離す
   e. `content_widget`（`OscilloscopeWidget`）自体も `content_container` から取り外す（親なしにする）
   f. `IndependentWindow` を2つ作成（display 用・control 用）
   g. 両ウィンドウの `closed` シグナルを `reattach_all` に接続する
   h. `content_container` を隠し、プレースホルダーを表示する
   i. `is_split = True` にセットする
   j. Split ボタン・Detach ボタンを無効化する
5. `reattach_all()` メソッドを実装する：
   a. `is_split` でなければ return する
   b. `split_display_window` / `split_control_window` の `closed` シグナルを disconnect する
   c. `display_widget` と `control_widget` を `OscilloscopeWidget` に戻す（元の `display_widget` / `right_widget` の親に再設定）
   d. `OscilloscopeWidget` を `content_container` に戻す
   e. 両 `IndependentWindow` を close/deleteLater する
   f. プレースホルダーを隠し、`content_container` を表示する
   g. `is_split = False`、ボタンを元の状態に戻す
6. プレースホルダーウィジェットに「Reattach All」ボタンを追加する（`reattach_all` に接続）
7. `IndependentWindow` の right-click コンテキストメニューに「Reattach All」アクションを追加することを検討する

**Relevant Context:**
- [`src/gui/widgets/detachable_wrapper.py` L93-393](src/gui/widgets/detachable_wrapper.py) — `DetachableWidgetWrapper` 全体
- [`src/gui/widgets/detachable_wrapper.py` L24-90](src/gui/widgets/detachable_wrapper.py) — `IndependentWindow`
- [`src/gui/widgets/detachable_wrapper.py` L304-328](src/gui/widgets/detachable_wrapper.py) — `detach()`（Split の参考実装）
- Sub-Task 1〜3 完了前提

---

### Sub-Task 5: テストと動作確認

**Status:** `[x] done`

**Intent:**
既存テストが壊れていないこと、および State C の基本的な動作フローを手動確認する。

**Expected Outcomes:**
- `pytest -q` がエラーなし（または既存の失敗数以上に増えていない）
- `ruff check` がエラーなし
- State A → Split → State C（2ウィンドウ表示）→ どちらか閉じる → State A に戻る
- State B → Split → State C → Reattach All → State A に戻る
- State A → Detach → State B が引き続き正しく動作する
- `update_compact_layout` でのコンパクトモードが State A・B で引き続き正しく動作する

**Todo List:**
1. `./.venv/bin/python -m pytest -q` を実行してテスト確認する
2. `./.venv/bin/ruff check src/gui/widgets/oscilloscope.py src/gui/widgets/detachable_wrapper.py src/gui/widgets/splittable_interface.py` を実行する
3. `./.venv/bin/python scripts/check_ui_size_limits.py` を実行して UI サイズ上限チェックを確認する

**Relevant Context:**
- AGENTS.md の「テスト」セクション

---

## 実装後の状態まとめ

```
src/gui/widgets/
  ├─ splittable_interface.py   ← 新規作成
  ├─ oscilloscope.py           ← SplittableWidgetInterface 追加、_setup_left_panel 修正
  └─ detachable_wrapper.py     ← Split ボタン追加、split()/reattach_all() 追加
```
