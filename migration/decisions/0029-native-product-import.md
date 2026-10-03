# 0029: 旧トレースと完全snapshotのnative読込みを分ける

日付: 2026-10-02。状態: native評価実装。製品schema・採用言語の決定ではない。

## 判断

[決定0025](0025-product-exchange-compatibility.md)のPython互換adapterを比較基準として維持し、
[決定0027](0027-native-product-snapshot-codec.md)のnative parserを共有した読込み入口を追加する。
`ImportedProduct`は検査済みトレースと任意の完全snapshotを保持し、旧fileだけから
`MeasurementResult`を生成しない。既存result専用readerの旧file拒否も維持する。
旧Stream/Timebase/ChannelId等はunknown。元の軸/有限値/校正/metadataを保持し、
校正・単位換算の再適用、timestampからのclock生成、取得profileの自動適用を行わない。

## 境界と代償

CSVのoptions/descriptorを明示し、independentとmergedの32条件を実exporterへ通す。
mergedは保存済み共通gridの観測として返し、元sampleの復元保証を付けない。
完全snapshotにはindependent pairまたは明示descriptorを使い、予約carrier/全projectionの一致を要求する。
破損carrier、部分pair、不一致sidecarを旧トレースへfallbackしない。

各file 256 MiB、1024 trace、4,000,000 scalarの上限を維持する。
serdeが64bit範囲外の整数tokenをf64へ丸める前に拒否する。任意精度整数metadataは対象外とし、
既存native codecのJSON/sidecarにも同じ検査を適用する。元精度を保持できない入力の黙認を避ける。
容量上限はallocation/RSSのbyte予算ではない。同期APIはfile worker専用で、Qt/取得ownerの直接I/Oへ接続しない。

## 検証と後続

[再検査手順](../../native/product-import.md)で旧JSON/CSV値・軸・校正・metadataとunknown、
6保存snapshot×3入口の18完全import、null/reason、破損/欠落/範囲外整数、入力不変性を検査する。
固定binaryとsource/fixture/入力/成果物hashを保持し、数値許容差を変更しない。
既存snapshot codec、保存workerとdisplay-coreのpure回帰も検査する。

次はQt製品importの非同期配送/表示/寿命、005-A-common/006-D-integrationと008-Aの同じ2chフローへ進める。
取得profile再起動維持、取得中の保存負荷/長時間、他OSと採用判断は後続。
AC12全体、MIG-006/007/008は完了にせず、検査結果と未確認点を[status](../status.md)へ記録する。
