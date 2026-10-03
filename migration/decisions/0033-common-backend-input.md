# 0033: CPALとPortAudioの共通input.raw境界

日付: 2026-10-03。MIG-005-A-common-input。状態: 評価用入力境界、全backend/tap統合は進行中。
[正本計画](../../guide/RUST_QML_MIGRATION_PLAN.md)、[音声境界](0009-audio-boundary-uac232.md)、
[取得owner](0014-acquisition-history-shared-fft.md)、[再実行手順](../../native/backend-input.md)を参照。

## 判断

CPALの実callbackが直接作るqueueと、PortAudioが保存した入力の独立probeだけでは、
両backendの共通契約/元精度/位置を検査できない。まず`InputBinding`/`InputWriter<T>`を
audio-coreへ追加し、同じqueue/取得owner/共有FFTへ接続する。input.rawだけを対象とする。

bindingは明示backend/device/物理port/rate/精度/世代で不変とし、精度変更やdevice変更には新queueを要求する。
worker transportはsample位置/世代を検査してから書き込み、欠落を正常な連続値へ置き換えない。
callbackはbounded queueへの書込みだけを行い、filter/FFT/ファイル/pipeは解析側に置く。
device discoveryや各backendの開始/停止はadapterに残し、共通層がdeviceを推測しない。

PortAudioは既存sounddeviceを使ったblocking入力workerからRustへのbinary transportで評価する。
新しいnative FFI依存や製品callback変更をこの段階へ持ち込まず、実取得中のgraph進行と
元bytes/全FFTを確認する。追加buffer/pipeの費用とQtのbackend選択は008-Aで別に検証する。
このtransportは製品callback adapterの完成やCPAL直結との同条件性能を意味しない。

ローカルsounddeviceはfloat64指定をfloat32へ変更するため、実入力はf32を明示する。
保存f64とdevice精度を混同しない。006-Dのf64 filterへは暗黙変換せず、
次の統合単位で明示変換の来歴または対応精度を決める。最初のfilter候補の契約は変更しない。

## 証拠と未完了

元fixture/許容差を維持し、保存32条件の元bytes/正逆port/精度、両backend binding、
boxcar/Hann共有FFT、結果/単位/unknownと停止後のJSON/CSV完全snapshotを検査する。
実PortAudio BlackHole2/4/8chと、同じwriterへ接続したCPAL両Qtの回帰を別の実試験として記録する。
破損header/payload/世代/位置/EOFと、nonfinite/flags/overwriteの無効窓も検査する。
各command/report/失敗/未確認とsource/binary/hashは[進捗](../status.md)を正本とする。

全tap、動的routeのPortAudio配送、製品callback/Qt backend選択、filter/派生Trigger保存、
物理clock/USB/電圧/遅延、10分/負荷/他OS/clean配布は未完了。公開型/ABI/採用判断は固定しない。
