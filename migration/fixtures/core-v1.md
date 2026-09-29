# 多ch・コア契約fixture v1

MIG-003-B、2026-09-30。[コア](../contracts/core.md)と[数値](../contracts/numerics.md)はv0.1のまま。
[manifest](core-v1/manifest.json)、[手計算の入力・期待値](core-v1/scenarios.json)、
[決定0003](../decisions/0003-core-contract-oracles.md)を参照。

## 保存内容と検証範囲

| 対象 | ケース・期待値の由来 | 確認した範囲 |
| --- | --- | --- |
| AC01 | 4/8ch、4096 frames、48 kHz、矩形窓、f64/f32の4ケース | 保存済み入力→現行FFTManager各chと独立解析式。bin/peak/RMS/phase/PSD/inverse |
| AC02 | 4→2、8→4、2→8、入力IDの並替え、明示zero、異常reason合成、単位不整合 | 独立した手計算の行列例。±1を超える仮想値もclamp/正規化しない |
| AC03 | sample101で要求、境界128で適用。未知ID、重複入力/出力、行列shape、NaN gainを拒否 | ackと既存routeの保持、公開済みrouteコピーの不変性 |
| AC08 | k=2048、pre256/post768、保持4096、遅い読者、未来、負位置、分数位置 | 両読者の要求は`[1792,2816)`。high watermark6000では`[1792,1904)`が失われる |
| AC09 | gap、世代/形式変更、旧event/block、別Timebase/clock、有効期限付き写像、解析窓の無効範囲 | 絶対位置とreasonの厳密一致。整数sampleの列挙でも区間oracleを照合 |
| AC11 | mute、gain、量子化、出力mapping、仮想loopback遅延 | mixedとdevice bufferを区別。物理出力は未測定、初期遅延はwarmup |
| AC12 | V/FS=1+c/4、ID並替え、未校正、profile更新、周波数補正1/1.0001 | snapshot不変、FS保持、V/SPLは未校正ならnullとreason。JSON/CSVを再読込 |

状態・metadataは27ケース。保存例は校正2ケース×JSON/CSVで4ファイル。
全82ファイル、約5.6 MiBをGit対象に保存。小規模の状態例はJSON、FFT配列は003-Aと同じlittle-endianの型/shape付きbytes。
JSONのNaN/Infinity、重複キー、CSVの非有限数を拒否し、欠損値を有効な0にしない。
不正shape、版/hash、channel順、整数位置、reason、nullと0の混同を異常系試験で検出する。
保存失敗は例外として伝わり、既存ファイルを上書きしない。

AC01の4/8chは現行FFT関数をchannelごとに呼ぶ参照まで。
27ケースは**新契約のoracle**であり、現行engine・候補coreの実装合格ではない。
履歴の実バッファ、共有graph、実機loopback、製品export互換は未実装。詳細は決定0003を参照。

## 結果

[固定環境の実行report](runs/2026-09-30-intel-core.json)に環境・hash・誤差を記録。
4 FFT・27契約例・4保存例すべて成功。f64の最大`X/N`複素誤差は約`1.56e-14`、f32は約`7.25e-9`。
bin・phase・peak/RMS・PSD積分・inverseも既存の契約許容差内。
新規Pytestは70件成功。別ディレクトリへの再生成でもmanifestを含む全82ファイルのbytesが一致した。

reportの時間・peak RSSはファイル読込と全検査を含む単発の診断値。性能protocolに沿う候補比較ではない。
Qt/deviceのimportなし。003-Aの既存20ケースも別に再検査している。

## 再検査

```bash
./.venv/bin/python scripts/migration_core_reference.py verify
./.venv/bin/pytest -q tests/logic_verification/test_migration_core_reference.py
```

別環境の比較では`verify --portable`を明示する。同一環境の再現とは区別してreportに記録し、
source/契約/runner hash・数値・metadataの条件は維持する。
report出力は`--report <新しいファイル>`で指定し、fixture配下や既存ファイルへの書込みは拒否する。

明示的な再生成は新しいディレクトリだけに行う。保存済みfixtureを更新するためには使わない。

```bash
./.venv/bin/python scripts/migration_core_reference.py generate --output .migration-local/core-reproduce-v1
./.venv/bin/python scripts/migration_core_reference.py verify --fixtures .migration-local/core-reproduce-v1 --baseline migration/fixtures/core-v1/manifest.json
```

後続の候補coreは保存した入力bytesと`scenarios.json`の入力/期待値を直接使う。
sinの再生成やこのPython oracleの成功を、候補core自身によるAC02/03/08/09/11/12の試験に代用しない。
