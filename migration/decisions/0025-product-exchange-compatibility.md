# 0025: 旧トレースと完全snapshotの復元保証を分ける

日付: 2026-10-02。状態: 互換adapter評価。製品schema・Rust/QML採用の決定ではない。

## 判断

現行`ExportTrace`/JSON exporterの軸/校正/metadataを互換境界に使う。
旧traceの値は既に保存された単位の観測値として読み、係数やoffsetを再適用しない。
旧fileにないStream/Timebase/generation/ChannelId/区間/trigger/route/tapをunknownに保つ。
timestampをdevice clockへ、trace IDをChannelIdへ置き換えない。

現行CSVは元の軸/校正/metadataを完全には持たず、merged形式は補間も行う。
翻訳済みheaderからschemaを推定せず、optionsと列descriptorを明示して読み込む。
independent列の元値と、merged union gridの保存値を区別し、後者から元gridを復元しない。

完全native snapshotは製品JSONの先頭metadata carrierへ一度だけ保持する。
legacy表示配列は有限値のprojectionとし、nullを含むprojectionは省略理由を明示する。
元のnull/reasonや全解析配列はcarrierに維持し、0/NaNにしない。
CSVの完全往復にはindependent列とmetadata sidecarを用い、bytes hashとsnapshot/projectionの一致を要求する。
復元時はRustの既存readerを数値/来歴契約の正本とし、二つ目のnative契約をPythonで作らない。

## 境界と代償

今回はPythonの独立評価adapterで、現行製品コード/GUI、Rust worker、v1 fixtureを変更しない。
native codecや製品保存schemaの版管理はMIG-008に残す。
完全snapshotと旧表示用配列の重複/deep copyがあるため、常時取得や性能試験へそのまま導入しない。
CSVとsidecarはfileごとにsync/no-clobber公開し、pair transactionは保証しない。
sidecar公開失敗でCSVが残る場合は失敗を維持し、readerは不一致の組を拒否する。

結果のprofileは保存/再読込して保持するが、取得設定へ自動適用しない。
校正profileの再起動維持、device再照合、旧設定自動移行は別の判断である。
全解析専用形式、非有限な旧file、欠落fieldや暗黙descriptorへの寛容なimportは対象外。

## 検証と後続

[再実行手順](../../native/product-exchange.md)で2校正契約/4交換例と4/8ch f32/f64を
JSON/CSVの両入口から製品形式へ通し、Rust readerで全値/来歴を完全照合する。
旧JSONとCSVの32条件は実exporterと独立した手計算値で検査する。
unknown、校正二重適用、破損snapshot/sidecar、上書き、失敗/回復とpair部分失敗を検査する。

007-A-saveとnative file workerへの接続、取得中の保存負荷を別途検査する。
AC12全体とMIG-006/008を完了にせず、今回の境界の結果だけを[status](../status.md)へ記録する。
