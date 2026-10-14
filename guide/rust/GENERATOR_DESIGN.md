# シグナルジェネレーターの設計契約

通常Generatorのf64コア・内部接続・CPAL出力は実装済み。統合評価の残りは [PLAN](PLAN.md#45generatorの統合評価)、操作は [README](README.md#generatorの出力と内部ループバック)、テストと実機QAは [VALIDATION](VALIDATION.md)。この文書は信号・時計・制御・保存の契約を保持する。

## 範囲と信号

初期用途は独立した2正弦波と、内部ループバックまたは1台の音声デバイスへの出力。対応する1〜16出力CHへ最大2信号を割り当て、未割当CHは無音、二重割当は拒否する。多波形・ノイズ・スイープ・変調・出力校正・自動FRFは後続候補とする。

```text
x[n] = A[n] × sin(θ[n] + φ[n])
θ[n+1] = wrap(θ[n] + 2π f[n] / Fs_out)
A = 10^(dBFS / 20)                         [FS peak]
```

Fs_outは出力の公称値。f64の有限範囲の蓄積位相と整数連番を別に持ち、巨大な絶対連番から角度を作らない。0 dBFSは1 FS peak、正弦波RMSはA/√2、P-Pは2A。物理Vrms／Vppへの換算には出力CH・機器・Fs・ゲイン・負荷に対応した校正が必要。

* 設定範囲は0.1 Hz以上・0.45×Fs_out未満、−120〜0 dBFS、±180°の進み位相。既定は1 kHz・−20 dBFS・0°・出力OFF。設定範囲・表示桁数を物理精度の保証にしない。
* 非有限・範囲外の要求は全体を拒否し、最後の適用値を維持する。別Fs・別形式・既定スピーカーへ暗黙に切り替えない。
* 周波数変更はcarrier位相を保持する。振幅・開始／停止・CH ON／OFFは原則10 msのraised-cosine遷移。位相は最短方向、半周の同距離は正方向へ補間する。上限近傍では位相増分がNyquist未満になるよう遷移を延長する。
* 遷移は適用境界の現在値から始め、`[applied_sample, transition_end)`を記録する。片CH OFF中も位相を進め、同周波数へ戻すだけで相対位相を揃えない。Align phasesは共通原点へ滑らかに整列する。

## 実行と制御

```text
Generator GUI / I/O → 非UI出力管理 → 固定容量制御 → f64 Engine
  ├ CPAL callback → PCM → DAC → DUT → 通常入力 → 測定ワーカー
  └ 内部生成ワーカー → 連番付き固定容量転送 → 測定ワーカー
測定ワーカー → Scope / Spectrum / Lock-in / Comparison / STFT → UI・保存
```

| 契約 | コードの入口 |
| --- | --- |
| 生成・設定検証・遷移・整数時計 | [generator.rs](../../src/generator.rs)、[数値テスト](../../src/generator/tests.rs) |
| 固定容量要求／応答、最新要求の集約、優先Stop | [generator/control.rs](../../src/generator/control.rs) |
| 内部生成・共通入力、条件付き結果 | [output.rs](../../src/output.rs)、[measurement.rs](../../src/measurement.rs) |
| 安定ID・能力再確認・PCM・コールバック | [output/device.rs](../../src/output/device.rs) |
| 接続・期限付き停止・ERROR保持 | [output/runtime.rs](../../src/output/runtime.rs) |
| 外部出力の観測履歴 | [output/history.rs](../../src/output/history.rs) |

コールバックは事前確保した状態と固定サイズ値だけを使い、待機・ロック・確保／解放・ログ・列挙・FFT・ファイルI/Oを行わない。設定はCH群を含む不変スナップショットとしてフレーム境界で適用し、制御処理数を制限する。enqueue成功を実適用とせず、実行側の状態・版・整数境界を表示する。

Stopは編集キューと独立したatomic経路で古いStart／編集を取消す。停止フェード中の再Start／編集を拒否し、完了後の明示Startを必要とする。Startは新しい出力世代とcarrier原点を作り、連番を巻き戻さない。停止応答の排他的終端は最終ゼロフレームを含む。最新Reportを全設定履歴と扱わず、要求合流・取消・応答飽和を計数する。

PCMの量子化・端点・無音値は形式ごとに定義し、異常な非有限・範囲超過は無音化して失敗を保持する。デバイス通知は接続直後も失敗。コールバック停止・Stop応答の期限切れは管理側でERRORとして解放し、正常な有限Stopと区別する。具体的な容量・期限・PCM許容差はコードとテストを参照する。

macOS実入出力は共通のバッファ方針で約20 ms以上に相当するフレーム数を能力範囲内で要求する。Fs・CH数・PCMを保持し、能力不明なら既定値を使う。バッファの余裕と編集・停止遅延を同時に評価する。

## 時計・入力・保存

* 内部接続は同じ整数時計の実生成フレームを測定へ渡す。観測用に同じ波形を再計算しない。転送飽和で生成を待たせず、未受信を取得済みとして補完しない。既存Software Loopbackの固定条件の既知DUTモードは別経路として維持する。
* 内部入力の取得中は出力OFF後も新しい無音フレームを供給する。内部遷移サンプルはScope／STFTへ渡し、Spectrum／Lock-in／Comparisonは遷移後の完全窓から再評価する。
* 外部入出力は別の整数時計。同じ機器名・公称Fsで同期を仮定せず、実入力REFを使う。出力編集とADC入力窓は自動対応せず、入力解析を自動リセットしない。安定した入力と整定を確認して読む。
* 設定保存には出力先・Fs・PCM・CH割当と信号条件を含め、Start命令を保存しない。内部結果の`generator_output`は受信した区間の世代・適用版・境界・carrier・遷移を保持し、履歴外・欠落の条件をUI最新値から補わない。
* 外部結果の`external_output`は管理ワーカーの観測履歴と開始／保持時の観測を保存する。退役・報告された応答欠落・通知累計を残し、入力Stop／Single／失敗で固定する。ホスト観測時刻はDAC／ADC時刻ではなく、完全な設定履歴・解放後監査の証拠でもない。
* 内部の参照差は寄与区間が定常で、設定・同周波数の相対carrier位相が一致する場合だけ表示する。外部観測履歴の入力窓対応は未校正なので数値差を抑止する。保存形式・旧版互換性は [settings.rs](../../src/settings.rs)、[export.rs](../../src/export.rs)、[results.rs](../../src/results.rs) とそのテストが正本。

## 開始・停止とGUI

起動・復元・再接続はOFF。入力／出力を停止して出力先・形式・CH割当を変え、再出力には明示Startを要求する。Start inputとStart outputは別操作で、入力Stop／Single完了後も出力は継続する。アプリ終了・出力エラーでは出力を止める。

通常Stopはフェード応答後にストリームを解放する。応答なしの有期限解放を成功扱いしない。ERRORは明示Resetまで保持し、Resetや設定復元だけで開始しない。OSへ提出済みのバッファ・DAC端子での停止時刻は別に評価する。

GUIは設定値／実適用値、GEN／OUT／入力CH、STOPPED／STARTING／RUNNING／STOPPING／ERRORとPENDING／APPLIED／TRANSITIONを区別する。非表示時も出力状態と全出力停止を残す。数値編集は同じカードで完結し、狭幅はCHタブへ切り替える。プレビューは設定波形であり実測ではない。レイアウト・色・閾値の具体値は [generator_panel.rs](../../src/app/generator_panel.rs)、[io_panel.rs](../../src/app/io_panel.rs) を参照する。
