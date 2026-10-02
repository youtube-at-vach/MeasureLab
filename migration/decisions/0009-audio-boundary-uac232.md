# 0009: 音声取得境界とUAC-232の短時間比較

2026-09-30、MIG-005-A/B。採用backend・製品API・Rust/QML採用の決定ではない。
開始HEADは`41d3a534`。006-Bはこのcommitへ保存済みと確認し、cleanなworktreeで
`codex/migration-005-a`へ分岐した。現行DSP/UI、003-A/B/Cのfixture/許容差は変更しない。

## 判断と変更境界

実機が接続されたため、次の独立作業として005-Aの取得/route/tapと005-Bの短い実機診断を優先した。
`native/audio-core`、`native/audio-probe`、runner/対象テスト、独立CIと検証文書へ変更を限定する。
現行PortAudioはAudioEngineの比較基準として維持する。
[CPAL公式API](https://docs.rs/cpal/0.18.2/cpal/)を確認し、0.18.2を固定してCore Audio adapterを試作した。
[ZOOM公式マニュアル](https://zoomcorp.com/manuals/uac-232-ja/)は2ch/32-bit floatの製品仕様の参照先。
実際のchannel数・利用可能なf32/48 kHz・callback frame数は各backendで再確認する。

1 producer/1 consumerのpreallocated atomic queueを選び、遅いconsumerからwriterを独立させる。
上書き前後にslot sequenceを照合し、取得後のowned値は保持する。
f32/f64のbitsを保存し、古いframeを捨てた位置をgapとして返す。
制御/workerのowned演算とcallback内のborrowed演算を分け、callbackへgraphのmutex/通知を転用しない。

queueはnumeric payload以外のatomic metadata/heap headerも持つ。容量からprocess RSSを保証しない。
workerが全診断データを保存するため、実保存sessionのbounded memory検証は後続。
アプリcallbackにalloc/lock/file/FFTを入れない条件をsourceで確認した。
CPAL内部のCore Audio listener/stream制御にはmutexがあり、backend全体のRT性は短い実測だけで保証しない。

## 参照と実機条件

003-Bの10件（route6、変更/拒否1、tap2、block/generation1）を候補Rustへ渡し、保存期待値と一致。
4/8ch f32/f64の4件は元の入力bytesを取得queueへ通し、ID/順序/位置と出力bytesを完全照合する。
Rustテストはshape/非対称I/O、route拒否時の旧条件保持、snapshot保持、最古frameのgap、
20,000 frameの同時上書き、f64精度、非有限入力のzero係数除外を含む。

実機はCore Audioの`ZOOM UAC-232`、2入力/2出力。
ユーザーの配線は出力Lの2分岐: −20 dB attenuator→入力L、直結→入力R。出力Rは未接続。
phantom/Hi-Z、端子種別、hardware/software gain、attenuatorの実校正値は未確認。
入力の絶対電圧・deviceの校正済み状態を推定しない。

48 kHz/256 frame/f32、4秒、1 kHz/−30 dBFS、同期marker、区間muteを同じsource bytesで使う。
基準と候補は同時にdeviceを開かず、現行→CPALの順を3回繰り返す。
振幅差0.1 dB、nominal attenuator差1 dB、L/R遅延差1 sample、相対phase差1度、
mute時tone低下60 dBを測定前に固定した。デバイスの絶対精度の仕様判定ではない。

## 結果と限界

最終raw記録は`.migration-local/2026-09-30-005-b-uac232-validated/report.json`。
全6取得・3 backend比較と準備中cancelが成功。
最終振幅差は最大0.0126094 dB、相対phase差0.000703度、入力L/R marker差は全runで0 sample。
L/Rのレベル差は−20.0135〜−20.0264 dB、mute tone低下は99.567 dB以上。
最終runのqueue gap/CPAL error/XRUNと現行statusは0。
CPAL入力queue最大深さ1792/1792/1536 frame、出力511/511/512 frame、容量各8192。

| 全3回の停止 wall ms | 1 | 2 | 3 |
| --- | --- | --- | --- |
| PortAudio | 278.668 | 274.337 | 261.156 |
| CPAL | 90.408 | 95.042 | 87.170 |

予備/開発/修正確認のrunも削除せず、最良のrunだけを選ばない。
予備のPortAudio playrecで入力underflowを1件検出した。診断runnerは開始時を含むstatusを保存する。

raw timestamp marker差は両backendで負値となった。
ADC/DAC時刻原点・reported latencyとmarkerの関係が未検証で、backend間写像の不確かさも未知。
そのため`physical_delay_ms=null`、精度判定unknownとし、raw差とbuffered marker offsetを別に残す。
同一入力stream内のL/R marker差は検査可能だが、絶対物理遅延の合格には置き換えない。

開始/二重停止とCPALの準備中cancelを実施。開始失敗はreport/終了コードへ反映する。
停止時間とcallback histogramは短いheadless診断値。10分3回、GUI通知p95、CPU/RSS比較、
停止p95予算、全AC13/16の合格ではない。

005-Aはpure boundaryと基本backend比較まで。callbackへの動的route配送、永続scheduler、
取得blockから共有graphへ接続する部分は未実装。
005-BのUSB切断/復帰、device排他、既知XRUNの正確な区間、物理出力R、絶対遅延精度は残る。
物理4/8/16ch、ARM/Windows/Linux、全P2/採用判断は未確認。

## 開発中の失敗

最初のCargo fetchは新crateのtarget作成前で拒否された。targetを追加して再実行した。
CPAL時刻APIの引数/返り値を誤って使い、compileが失敗した。固定版sourceに従い修正した。
fixture比較ではgain metadataの整数をRustがfloatへserializeしたため厳密比較が失敗した。
制御側の数値検証を保ち、公開metadataは元のJSON表現を保持した。期待値は変更していない。
Clippyのconstant chunk API指摘と、その修正時の配列参照型エラーを修正した。
Ruffの対象テストunused importを修正した。これらの失敗を成功runに含めない。

再実行は[手順](../../native/audio-boundary.md)を参照。
