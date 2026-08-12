# Event Detector（異常イベント検出）

![Event Detector](../assets/widgets/event_detector.png)

Event Detectorは、入力信号が設定した閾値を横切った回数と発生レートを連続測定するウィジェットです。
JFETやオペアンプのポップコーンノイズ、RTN（Random Telegraph Noise）、接点不良によるクリックなど、まれに発生する現象の定量化に使用します。

## 他の時間領域ウィジェットとの違い

| ウィジェット | 主な目的 |
| :--- | :--- |
| Oscilloscope | 短い波形の形状を詳細に観察する。 |
| Raw Time Series | 間引いた長時間波形を目視で観察する。 |
| Transient Analyzer | トリガ収録した単発波形をCWTなどで解析する。 |
| Event Detector | 全入力サンプルを監視し、まれな閾値イベントを計数する。 |

Event Detectorは波形表示を持ちません。波形の形状を確認したい場合は、Raw Time SeriesまたはOscilloscopeを併用してください。

## 検出設定

### Input Channel

検出対象をCH1またはCH2から選択します。モノラル入力の場合はCH1が使用されます。

### Threshold

イベント開始を判定する閾値です。初期実装ではFS（Full Scale）単位で指定します。

### Polarity

- `Positive`: 正方向の閾値交差だけを検出します。
- `Negative`: 負方向の閾値交差だけを検出します。
- `Both`: 正負の両方を検出します。

### Hysteresis

閾値付近の小さな揺れを複数イベントとして数えないための幅です。

正極性の場合、信号が`+Threshold`を横切るとイベントが開始し、`Threshold - Hysteresis`以下へ戻ると終了します。負極性では符号を反転した条件を使用します。

HysteresisはThresholdより小さい値に設定してください。

### Holdoff

イベント終了後、次のイベント検出を禁止する時間です。リンギングや接点バウンスによる再カウントを抑制します。

## 測定結果

- `Detector State`: 停止、待機、イベント発生、ホールドオフの状態を表示します。
- `Event Count`: 測定開始またはReset以降のイベント開始回数です。
- `Event Rate`: 経過時間1分あたりのイベント回数です。
- `Measurement Time`: Event Rateの計算に使用した測定時間です。

Event Rateは次式で計算されます。

```text
Event Rate = Event Count × 60 / Measurement Time [seconds]
```

## 基本的な測定手順

1. DUTを低雑音プリアンプなどを介してオーディオインターフェースへ接続します。
2. Raw Time SeriesまたはOscilloscopeで通常ノイズと異常イベントのレベルを確認します。
3. Event Detectorで入力チャンネル、Threshold、Polarity、Hysteresis、Holdoffを設定します。
4. `Start`を押して測定を開始します。
5. 所定時間が経過したら`Stop`を押し、Event CountとEvent Rateを記録します。
6. DUTを交換し、同じゲイン、閾値、サンプルレート、測定時間で繰り返します。

測定中は条件がロックされます。条件を変更する場合は一度停止してください。`Reset`は測定を停止せずに回数、経過時間、警告をクリアします。

## イベント判定の注意点

- 測定開始時点ですでに閾値を超えている信号はカウントされません。一度解除レベルへ戻った後の新しい交差から検出します。
- イベントがオーディオブロックをまたいでも1回だけカウントされます。
- `CLIPPING`が表示された測定は入力振幅がFSへ到達しており、正しい振幅関係が失われている可能性があります。
- `I/O BUFFER ERROR`が表示された測定は入力サンプルを失った可能性があり、Event Countが実際より少ない場合があります。
- DCや非常に低い周波数を測定できるかどうかは、オーディオインターフェースの入力結合方式に依存します。

## 現在の制限

初期実装の表示項目はEvent CountとEvent Rateが中心です。イベントのピーク振幅、継続時間、イベント間隔は内部で記録されますが、分布表示やファイル出力は今後の拡張対象です。
