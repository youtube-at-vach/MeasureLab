# Decision 0010: BlackHole as the default audio evaluation device

2026-09-30、MIG-005-A/B。Rust/QMLやCPALの採用決定ではない。
[作業票](../tasks.md)、[進捗](../status.md)、[音声境界](../../native/audio-boundary.md)を参照。

## テスト方針と引き継ぎ

ユーザーはUAC-232での動作を確認済みとし、以後はBlackHole 16ch／2ch経由のテストを許可した。
通常の音声回帰、チャンネル対応、mute、開始／停止、再オープンはこの2台を優先する。
UAC-232は物理ADC/DAC、電圧・hardware gain・配線、USB切断／復帰、物理遅延など、
仮想デバイスでは確認できない要件を検証する場合だけ使う。
物理操作が必要な試験だけを未確認として残し、依存しない工程は進める。
UAC-232の接続変更や再測定は今回行っていない。

[BlackHole公式README](https://github.com/ExistentialAudio/BlackHole)では出力portと同じ入力portの
ループバック、2／16ch版、48 kHz対応を説明している。
これは実機4／8／16ch、USB復帰、別clockの同期、校正済み物理遅延の保証には置き換えない。

## 比較の境界

- [CPALプローブ](../../native/audio-probe/src/main.rs)を1〜16の入力／出力数、複数source、
  明示gain行列、mute区間へ拡張。既存UAC-232 requestの2ch・Lのみ出力の既定値は維持する。
- route・source ID・shape・gain・容量をdevice open前に検証し、routeを制御側でcompileする。
  callbackでは事前確保したscratchとqueueを使用する。動的route配送はまだ実装しない。
- [仮想device runner](../../scripts/migration_audio_virtual.py)は完全一致するBlackHole 2ch／16chだけを
  解決する。明示`--virtual-device`と新規出力先を要求し、既定deviceへfallbackしない。
- 2chは既存AudioEngineを変更せず使う。runnerから既存のCore Audio設定APIを呼び、
  process内で設定／校正／wisdomの保存先を分離する。両出力へ異なる信号を出す。
- 16chはsounddeviceの直接PortAudio streamと比較する。現行AudioEngineはN-channelに拡張していない。
  16ch比較を製品engineの16ch対応や同等GUI負荷の性能合格として扱わない。
- 全16portのidentity、4／8chから16portへの並替え・複製・明示mix・無音portを検査する。
  route変更は停止後の次の取得で行う。動作中のtransactional更新の合格ではない。

## 事前条件と失敗の扱い

48 kHz／256 frame／f32／4秒。各sourceは異なるtoneと固定seedのmarker、peak 0.015 FS。
muteは`[108032,132096)`。比較許容差は全sampleの絶対差2e-6 FS、
channel間marker差1 frame、backend振幅差0.1 dB。無音portも全区間を照合する。
時刻不確かさはunknown、`physical_delay_ms=null`のまま保存する。

初回開発runではBlackHole 16chの初期設定が96 kHzだった。
PortAudio取得1件にinput underflow8件と最大約0.00317445 FSの波形差が出て不合格。
CPALと後続の取得は合格だった。48 kHzの論理streamだけでは変換を排除できない可能性があるため、
PortAudio側に`change_device_parameters=True`と`fail_if_conversion_required=True`を明示した。
このAPIの意味は[sounddevice公式説明](https://python-sounddevice.readthedocs.io/en/0.5.5/api/platform-specific-settings.html)を確認した。
この設定は指定したBlackHoleのrate／frame sizeを変えうる。system default deviceは変更しない。
変更後は16chを再度96 kHzで開いて閉じ、48 kHzの明示openから再検証した。

失敗runとraw bytesは`.migration-local/2026-09-30-005-virtual-development/`へ保持する。
96 kHzの準備記録は`.migration-local/2026-09-30-005-virtual-rate-setup.json`。
最終run・検証結果は[statusの仮想device欄](../status-history-2026-10-03.md#mig-005仮想デバイスの成果と検証)を参照。
XRUNやqueue gapを埋めて合格にせず、準備中cancel・二重stop・再オープンと数値一致を別に検査する。

## 残る範囲

動的route配送、永続取得scheduler、PortAudio／Rustの製品共通adapter、時刻写像、
実graph／Qt接続、device排他、10分3回、他OSは未確認。
再オープン時のgeneration metadata確認は旧世代event拒否の実装検証ではない。
MIG-006-Cの実履歴／Timebase／旧世代拒否は次に進められる。
