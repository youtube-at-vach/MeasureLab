# 0013: 不変resultと基本校正・実験用交換形式

日付: 2026-10-01。対象: MIG-006-E、P13/P14、AC12。
状態: pure候補の検証済み。Rust/QML採用と製品ファイルschemaは未決定。

## 判断と実装境界

[003-Bの参照](../fixtures/core-v1.md)と006-B/C/Dのpure共有graphを利用し、
[graph-coreのresult境界](../../native/graph-core/src/result.rs)にownedな`MeasurementResult`を追加した。
内部documentはprivateで、外部へmutable referenceやunchecked Deserializeを渡さない。
source/generation/ChannelId、区間、Timebase、raw result ID、演算条件、trigger/clock写像、
取得host時刻と結果host時刻、校正snapshot、軸/単位、validity、元精度の全配列を保持する。
`from_fft`は共有結果からコピーし、graphを所有し続けない。確定結果の寿命は取得世代と独立である。

校正はID付きprofileをsnapshot化し、`input.raw`の解析後に基本V/FSを適用する。
FSは保持し、未設定/未校正のV/dBVとSPLはnull＋reasonとする。profileの既定数値は証拠にならない。
並替え後もIDに係数が追随し、profile/軸補正の変更は新resultを作る。旧resultを更新しない。
SPLと周波数/位相mapは未実装。mixed/既に校正済みのtapへの単純な絶対係数の適用は拒否する。
周波数軸はnominal/correctedを別保存し、V²/Hzの密度には補正率のJacobianを適用する。

JSON/CSVは実験用v1とし、全metadata・配列・shape・precision・null/reasonを往復する。
保存はworker/control側の同期APIで、same-directory tempへの全書込み/flush/fsync後に、
hard-linkによるno-clobber公開を行う。例外、短いwrite、flush失敗、既存destinationは成功にしない。
非同期worker/cancel、directoryのcrash durability、複数fileの一括commitは今回の保証外。

既存003-A/B/Cの入力・期待値・hash・契約・許容差とCargo lockを変更していない。
新schemaのtyped f64から旧交換例へ照合する際、整数係数/軸補正の表記だけを戻す。
保存例への値/metadata一致を現行製品importerの互換性の証明として扱わない。製品形式と移行は008で評価する。

## 検証と後続

[runner](../../scripts/migration_result_candidate.py)は保存2校正契約/4交換例、4/8ch f32/f64の元bytesを使う。
2view＋保存sessionの同じraw result、評価1回、view解除後のsession、最後の解除/shutdown回収を確認する。
profile/世代変更後の不変性、無効窓、nonfinite/zero/未校正、trigger分数位置/clock写像のunknown、
重複JSON key、壊れた版/shape/precision/単位/null/reason、保存失敗はRust/Pythonで検査する。
最終の件数・report・環境は[進捗](../status-history-2026-10-03.md#mig-006-eの成果と検証)を正本とする。

再実行は[候補手順](../../native/result-candidate.md)。実取得/Qt/永続scheduler、製品save session、
校正map/実device、legacy importer、steady-state/長時間/他OSは未確認。
006-A〜Eのpure範囲が揃った。次は005の取得queue/graph接続か007-Aの実result表示境界へ進める。
MIG-006全体、最小2chフロー、Rust/QML採用の完了とはしない。
