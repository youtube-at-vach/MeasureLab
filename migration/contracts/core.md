# コア契約 v0.1（MIG-002）

2026-09-29。[評価計画](../../guide/RUST_QML_MIGRATION_PLAN.md)のP0契約。
これは検証用の意味・不変条件で、Rustの公開型、ABI、保存形式の確定ではない。
現行との差は[決定記録](../decisions/0001-p0-contracts.md)、判定例は[受け入れ条件](acceptance.md)に置く。
変更時は版、理由、影響する台帳・fixture・後続タスクを一緒に更新する。

## 識別と信号ブロック

| 概念 | v0.1の必須条件 |
| --- | --- |
| ChannelId | セッション内の論理信号ID。表示名、配列index、deviceの物理portから独立。配列の並替えでIDを変えない。入力/出力の物理bindingは別に保持 |
| StreamId | 一つの生成・取得・派生系列のID。別セッションとの衝突を避けるnamespaceを持つ |
| generation | Stream内で単調増加。開始/再開、rate、channel集合/順序、形式、clock/binding変更時に更新。単なる表示pauseでは変えない |
| SignalBlock | StreamId、generation、順序付きで重複のないChannelId列、dtype、frames、start sample、Timebase、validity、route revision、tapを持つ |
| sample区間 | 世代内の0始まり整数frame位置の半開区間 `[start, start + frames)`。sampleはchannelごとのスカラー数でなくframe位置を指す |
| 配列 | 交換fixtureはframe-majorの明示的な形状 `[frames, channels]`。内部配置は任意だがstride/layoutを境界で決める。mono複製・切捨て・paddingは暗黙に行わない |
| 形式 | f32/f64を区別。解析は原則f64、I/O形式の昇格は失われた精度を回復しない。FSはfull-scale peak=1の相対振幅。オフライン途中値は±1を超えても黙ってclampしない |
| 所有権 | 公開したblock/resultは不変。pool再利用で購読者が保持する値を変更しない。ゼロcopy採用時も同じ条件 |

入力数と出力数は独立。入力専用、出力専用、4入力→2出力、2入力→8出力を表せる。
空のSignalBlockを「無音の有効測定」としない。停止/進捗の通知は別event。
重複/逆順block、未知のChannelId、framesと配列長の不一致は受渡し前に拒否する。
同じ世代のgapは絶対位置の飛びで表し、欠落後を詰めて連続に見せない。

## Timebaseと同期

TimebaseはID、clock domain、正の有理数rate `p/q` Hz、世代、原点sampleと原点時刻、
原点の由来（device/host/virtual）、推定不確かさを持つ。未取得の原点・不確かさはunknownであり0ではない。
同一Timebaseのsample `n` は `t(n) = t0 + (n - n0) × q/p`。
monotonic時刻、UTC表示、device時刻を混ぜず、対応が推定なら推定の有効区間と誤差を保存する。
補正前のnominal rateと校正後のrateも分ける。

別clock domain間の差分・同時解析には明示的な写像が必要。写像には両Timebase/世代、offset、rate比、
有効区間、推定法、不確かさを含む。同じ公称48 kHzだけでは同期成立としない。
未対応のclock同期や外部trigger adapterは`unsupported`、時刻関係が未知なら`unsynchronized`として返す。
一つの配列へ連結して同期済みに見せない。

レート変換後は新しいStream/Timebaseを作り、親Stream、rate比、原点写像、filter revision、
信号上の遅延、結果が利用可能になるまでの処理遅延を保持する。遅延補償済みかを明示し、二重補償を防ぐ。
丸め前の位置は有理数で保持できるようにする。表示都合の丸めを測定位置に使わない。

## Triggerと履歴

TriggerEventはevent ID、発生元、Stream/generation、Timebase、sample位置（必要なら有理数）、
種別/極性、条件revision、validityを持つ。受信したhost時刻は診断用の別項目。
P1の整数trigger `k` に対しpre=`a`、post=`b`の要求は厳密に `[k-a, k+b)`。
分数位置を整数frame窓へ変換する場合はfloorをanchorとし、分数残差も保存する。
開始前の負位置や将来未取得のsampleを有効なゼロ埋めにしない。

保持容量はframe数で宣言する。各購読者のcursor/要求区間は独立し、一つのreadで他の履歴を消費しない。
取得済みならowned snapshot、不足ならpending、保持期限を過ぎたなら失われた区間を含むgapを返す。
取得を遅い購読者に合わせて待たせない。overflow時の方針は古いframeを捨てて位置を維持する。
trigger通知が遅れても、保持範囲内なら同じ区間を得る。再開後に旧世代のeventを新世代へ適用しない。

## RoutingとMonitorTap

Routingは入力ID列、出力ID列、有限のgain行列、revision、適用開始位置を持つ。
出力 `j` は `sum_i(gain[j,i] × input[i])`。選択、複製、並替え、mix、未接続の明示zeroをこの表で表す。
未知ID、重複した出力定義、次元不一致、非有限gainは開始前に拒否する。暗黙の平均化・音量正規化をしない。
P1はblock境界で切替え、実際の適用sampleをackに返す。将来sample途中で切替える場合はblockを分割する。
公開済みblockには後からroute revisionを適用しない。

| tapの意味 | 結果へ残す条件 |
| --- | --- |
| input.raw | backend入力とport binding。入力校正の適用前 |
| input.calibrated | profile/channel revisionと適用量。rawとは別入力 |
| output.mixed | generator/再生のmix後、出力mute/量子化前。DUT適用有無も別条件 |
| output.post_dut | DUT/model revision、遅延、処理状態。DUTなしのmixedと同一視しない |
| output.device_buffer | mute、gain、dither、量子化、channel mapping後のdevice提出buffer |

これらは意味の名前で、全tapの常時copyを要求しない。購読されたtapだけを作る。
device bufferも物理端子で測った信号ではない。物理出力の成立はループバック実機測定で確認する。
現行の仮想loopbackは前回出力の量子化/mute前を参照し、VST有効時はその処理後になる。
block遅延とtapを明示して互換adapterへ閉じ込める。mute中もこのtapが非zeroであることは矛盾でない。
暗黙の出力feedbackは禁止。仮想loopbackには遅延と初期区間のvalidityを設定する。

## validityと伝播

validityは単一boolでなく、reason、対象channel、sample区間/結果成分、発生元、詳細を持つ。
正常は既知の異常がないことを示すが、未確認の物理精度を保証しない。
必須の状態は`missing`、`unsynchronized`、`warmup`、`uncalibrated`、`nonfinite`、`unsupported`、`cancelled`。
backendのunderflow/overflow等は入力/output/tapと区間が特定できる限り保持し、不明な範囲はunknownとする。
既存検出器から得る情報を伝える契約で、各モジュールへ新しい常時監視を追加する指示ではない。

| 演算 | 伝播規則 |
| --- | --- |
| select/並替え | 選択されたchannelと対応区間のreasonを維持 |
| mix | 非zero係数で寄与する入力のreasonの和集合。gain=0の入力は影響なし |
| FFT/RMS/積分 | 参照窓にgap/nonfiniteがあれば測定値は無効。FFTをゼロ埋めして正常扱いしない |
| FIR/畳込み/rate変換 | 各出力の入力supportが無効区間と交差したら無効。supportによる影響拡大を記録 |
| IIR/位相追跡/平均 | gap/世代変更でstateをresetし、個別に定めるwarmup区間を無効扱い。旧stateと黙って接続しない |
| 校正 | FS相対値は保持できる。必要な校正がなければV/SPL等の絶対値のみ無効。profileのdefault数値を校正済みの証拠にしない |
| 表示 | フレーム更新の省略は測定gapを作らない。無効値を0/前回の正常値で置換しない |
| 保存 | 値とreason・影響範囲を一緒に保存。無効要素を黙って削除しない |

reasonを除去できるのは影響区間外になった場合、または明示された補正/再計算で原因が解消した場合だけ。
欠落を補間した場合も生の取得値へ戻ったとは扱わず、補間の来歴を追加する。

## FFT共有・購読・寿命

FFT nodeの共有keyは次のすべてを含む。hashを使う場合も衝突で別条件を共有しない。

- 入力Stream/generation、ChannelIdと順序、Timebase revision、対象区間、frame alignment。
- N、hop、窓名/全パラメータ/係数hash、periodic/symmetric、前処理/DC除去、精度、transform/正規化の版。
- 信号を変えるroute revision、tap、前段filter/state revision、前段校正revision、validityの扱い。

同じblockを受ける2viewは同じcomplex結果IDを参照する。FFT planの共有だけを計算共有と数えない。
別hop/窓/校正前処理/入力世代なら分岐する。表示単位、色、zoom、後段の独立平均はraw FFTの共有を妨げない。
ただし平均状態を共有するには開始位置・履歴・reset条件も一致させる。
P1では最初に固定DAGを用い、汎用graph editorは作らない。

購読は明示的なtokenで保持し、viewだけでなく録音/保存sessionも所有者になれる。
一つのviewを閉じても残る購読へ結果を供給する。最後の購読解除で不要nodeを停止し、
in-flight結果の寿命を守ってから制御側で解放する。古い世代の通知は新しいviewを更新しない。
キャッシュは容量を制限し、未参照結果から解放する。表示のqueue溢れと取得queueのgapを区別する。

## 制御とリアルタイム境界

基本状態はIdle → Preparing → Running → Stopping → Idle。失敗はFailedに理由を保持する。
Start要求への受付と、backend/workerが準備を終えたRunning通知は別。Stopは冪等、
Preparing中のStop/画面破棄/例外でもcallback・worker・deviceを回収する。
設定要求にはrequest IDとrevisionを付け、成功ackは実際の適用位置/世代を返す。
過去の失敗ackが新しい要求の表示を上書きしない。停止しても確定済みresultは保持可能。

音声callbackでgraph構築、無制限alloc、file/network待機、GUI、同期IPC、FFT plan作成、
待ち時間の不明なlock/解放を行わない。事前確保bufferと容量のあるqueueを使う。
監視負荷も[性能予算](../benchmarks/protocol.md)へ含める。
ワーカーの数値結果とGUI向けsnapshotは分け、GUI停止が取得を停止させない。

## 結果・校正・保存

MeasurementResultはresult ID、演算版、元Stream/generation/ChannelId、参照区間、Timebase/写像、
trigger ID、route/tap、条件、校正snapshot、軸/単位、validity、値を不変で持つ。
生成/取得の時刻と結果生成host時刻を区別し、単位にはpeak/RMS/power/densityの種別を含む。
校正はChannelIdに結び付け、device binding・profile revision・係数・校正済み状態・適用位置を保存する。
channel並替えでも同じ校正が信号に追随し、profile変更は過去結果へ影響させない。

MIG-003の交換形式は小さなJSON manifestと型/shape付き配列とし、schema version・hashを持つ。
製品保存形式はMIG-008で版管理する。現行CSV/JSONとの互換adapterでは既存の軸/校正/metadataを保持し、
旧ファイルにないStream/Timebase情報を推定して埋めずunknownにする。
JSONにNaN/Infinityを出さず、無効値はnullとreason、CSVは空欄とreason/metadataで表す。
元精度の結果を保存し、画面の間引き配列で置き換えない。保存成功は書込み完了後に通知する。
