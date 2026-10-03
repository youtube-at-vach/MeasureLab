# Dynamic output route candidate

MIG-005-A、2026-10-01。既存の[音声境界の実装](audio-core/src/lib.rs)へ制御→callbackの配送を追加した。
[進捗・検証結果](../migration/status.md)を参照。
製品backendの変更、全tap/Qt統合、Rust/QML採用の決定ではない。

## 配送と所有権

[route_mailbox](audio-core/src/dynamic_route.rs)は単一所有の制御handleとcallback handleを作る。
sourceの順序、outputのID/port順序、generationは開始時に固定する。並替え、複製、mix、符号、zeroはgain行列で変える。
物理port bindingの変更は新しいendpoint/generationを作る。旧endpointへ新旧の世代を混ぜない。

制御側で検証・compileした有限gainだけを、固定16×16 termsのatomic mailboxへ書く。
未確認の要求は1件まで。busy、無効route、旧世代、逆順の要求は現在のrouteを変更せず拒否する。
callbackはblockのshape/位置を検証してから、要求位置以上の最初のblock境界で係数をコピーする。
要求が遅れて届いた場合も実際の開始sampleをackへ残す。block途中で分割しない。

callback内の変更は固定回数のatomic load/storeと固定配列へのcopy。lock、待機loop、alloc、解放、文字列処理はない。
EMPTY→PENDING→APPLIEDのAcquire/Releaseでpayloadの所有権を移し、ackを読んだ制御側だけが次を書ける。
active係数はmailboxから独立し、遅いack readerでも音声を続ける。unsafeを使わない。
source列を参照するtermの加算順とzero係数の除外は既存CompiledRouteと同じ。
f32入力をf64でmixし、最後にf32へ戻す。clipping/正規化を追加しない。

callbackのBlockRouteはgeneration、数値sequence、半開区間だけを返す。
文字列revision、要求/実適用sample、applied/cancelledは制御側のRouteEventへ保存する。
公開済みblockのsequenceやbytesは後の変更で書き換えない。
closeは冪等。進行中のblockは完了しうるため、未適用要求のcancelはcallback破棄後に確定する。
handle、stream、Arcの破棄は制御側で行う。通常のcallback演算が破棄を行うAPIではない。

## 対象変更の検証

現在の範囲は[MIG-008計画](../guide/RUST_QML_MIGRATION_PLAN.md)に従う。
関連する変更がある場合だけ[対象テスト](../tests/logic_verification/test_migration_audio_route.py)と[runner](../scripts/migration_audio_route.py)を使う。
オプションは`./.venv/bin/python scripts/migration_audio_route.py --help`で確認する。
全条件の再実行・長時間試験・他OS検証はMIG-008の前提にしない。
