# N-channel audio boundary and UAC-232 diagnostic

MIG-005-A/B、2026-09-30。製品のbackend変更やRust/QML採用の決定ではない。
[決定0009](../migration/decisions/0009-audio-boundary-uac232.md)と[進捗](../migration/status.md)を参照。

## 取得境界

`audio-core`はQt/デバイスに依存しない。入力/出力数、ChannelId、物理portを別に指定する。
入力専用・出力専用・非対称I/Oを表現し、暗黙のmono複製・切捨ては行わない。
`Route`は制御側で検証・compileし、`CompiledRoute::process_into`は事前確保したframe-major f32出力へ書く。
f64のowned演算は解析worker用。FSのままmixし、異なるchannelのV/FSを一つの校正係数にしない。
`DeviceStage`は明示的mapping、gain、mute、ties-to-even量子化を持つ。ditherはnoneのみ。

取得queueは1 producer/1 consumer。両handleはCloneできず、同じwriterを複数callbackで共有しない。
容量はframe数、最大1,048,576 frame・16ch、callbackは最大8192 frame。
f32/f64を区別し、atomic slotへ元のbitsとsample位置・時刻・flagsを保存する。
遅いreaderには最古frameを捨てた厳密な半開gapを返し、位置を詰めない。
未知の時刻はNone、backend異常の区間が不明ならunknownとして別記録する。
取得後のowned snapshotはslotの再利用で変化しない。

slotとpayloadは全てatomic、sequenceの前後照合はSeqCst。unsafeやcallback内のlockを使わず、
writerはreaderを待たない。読み出しはworker側でallocし、競合時は後で再試行する。
queueの上限は内部numeric storage/slot数の制限で、workerが保存するsnapshotやRSSの上限ではない。
生成・route compile・JSON/ファイル・queue handleの破棄は制御側に置く。

`RouteControl`は制御/worker側のtransactionalなblock境界API。
音声callbackへ動的routeを配送するschedulerはまだない。`BlockValidator`はgap、重複/逆順、
rate/channel/dtype/clock/binding変更の新generation、旧世代拒否を検査する。
Stream/Timebaseのgraph接続と完全なTimebase写像は006-C以降で行う。

## デバイスなしの再検査

ローカルRust環境の設定は[準備手順](README.md#このworktreeで使う)を参照。

```bash
cargo +1.98.1 test --offline --locked --manifest-path native/Cargo.toml -p audio-core
cargo +1.98.1 clippy --offline --locked --manifest-path native/Cargo.toml -p audio-core -p audio-probe --all-targets -- -D warnings
./.venv/bin/python scripts/migration_audio_candidate.py --report .migration-local/005-a-verify.json
./.venv/bin/pytest -q tests/logic_verification/test_migration_audio_candidate.py
```

runnerは保存済み003-Bのroute/tap/blockの10例を入力し、手計算期待値と照合する。
期待値はRust processへ送らない。4/8chのf32/f64入力4件は元のbytesをqueueへ通し、
全sample位置、ID/順序、dtype、出力bytesの完全一致を要求する。
`--portable`でもsource/hash/期待値は検査し、fixtureは更新しない。

## 実機の短時間診断

deviceを開くには明示的な`--hardware`が必要。同名デバイスが複数あれば拒否し、既定deviceへfallbackしない。
CPALは0.18.2をCargo.lockで固定。Core Audioの2ch f32/48 kHzを確認し、256 frameを要求する。
LinuxでのcompileにはALSA開発依存が必要。Linux CIはcompileだけで、実機合格とは扱わない。

配線は出力Lを分岐し、−20 dB attenuator経由で入力L、直結で入力R。出力Rは未接続。
48 kHz、256 frame、f32、4秒、出力peak −30 dBFS、1 kHz toneと固定seedの同期markerを使う。
muteはblock境界の`[108032,132096)`。入力校正は行わない。
出力mixedの元ファイルとdevice提出値を区別し、実入力のtone低下を別に検査する。

```bash
./.venv/bin/python scripts/migration_audio_hardware.py --hardware --device 'ZOOM UAC-232' --output .migration-local/uac232-new-run
```

出力ディレクトリが存在すれば拒否する。既定で現行AudioEngine/PortAudio→CPALを3回交互に測定する。
各回のraw input/output bytes、sample位置、backend時刻、状態、XRUN、失敗、source/binary/lock hashを保存する。
CPALはrelease、現行はPython。QML/FFT負荷がない短い診断なので、性能比や10分protocolの合格に使わない。
現行engineにはprocess内で取得記録のwrapperを付け、変更せずgeneratorを登録する。
状態保存先はrunディレクトリ内に分離する。

測定前の許容差: backend振幅差0.1 dB、nominal attenuator差1 dB、L/R marker差1 sample、
backend間の相対phase差1度、mute時tone低下60 dB。
時刻差は診断値として保存するが、原点/不確かさが未検証なので物理遅延の精度を合格にしない。
今回のraw時刻差は負値となった。`physical_delay_ms`はNoneのまま保持する。

CPALの準備中cancelと二重pause/drop、現行の二重stopを確認する。
取得異常を正常値で埋めず、エラー時も保存できたreportを残す。
追加配線が必要なのは出力Rの物理対応試験。USB抜き差しは同じ配線で人の操作が必要。
排他、切断復帰、長時間、他OS、動的route配送、実graph/GUI統合は未確認。
