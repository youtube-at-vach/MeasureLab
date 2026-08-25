# スペクトログラム描画性能メモ

縦方向ウォーターフォール表示の実装時に確認できた、今後の描画性能改善候補です。
数値はmacOSのオフスクリーン描画による参考値であり、変更時には対象環境で再計測してください。

## 確認できたこと

- スペクトログラムの保存形式は `(履歴, 周波数ビン)` のまま維持し、縦方向では
  `ImageItem(axisOrder="row-major")` として解釈するのが効率的です。
  転置コピーが不要で、新しいスペクトルも連続した1行へ書き込めます。
- pyqtgraphではC-contiguousなrow-major配列が高速です。今回のFFT 8192では、
  縦方向が横方向より約35%高速でした。
- 現在の512段LUTを256段へ減らすと、pyqtgraphが高速なQImage変換経路を使える可能性があります。
  付属ベンチマークではFFT 8192の縦方向が約15.7 msから約9.3 msへ短縮し、QImage使用量も
  約7.8 MiBから約2.0 MiBへ減少しました。色表示への影響を確認し、方向変更とは別の変更として
  導入するのが安全です。
- 現在の履歴バッファは既定で`float64`です。FFT結果から表示バッファまでを`float32`へ統一できれば、
  履歴と変換用メモリをほぼ半減できます。FFT精度、Log/Mel変換、既存テストの許容誤差を先に確認してください。
- FFT 65536のような巨大画像では、画面解像度に合わせた`autoDownsample`の明示指定を検討できます。
  周波数ピークの欠落やLog/Mel表示の見え方を実画面で確認する必要があります。
- リングバッファを2枚の`ImageItem`へ分割する現在の方式では、ポインタ更新ごとに2枚の画像形状が変わります。
  pyqtgraph内部のQImageバッファ再確保を避ける固定形状方式は調査価値があります。ただし、`np.roll`などで
  履歴全体を毎回並べ替える方式は全要素コピーになるため、必ず現方式と比較してください。

## 推奨する検討順序

1. LUTを256段へ変更し、色表示と全カラーマップを確認する。
2. 表示・履歴バッファの`float32`化を検証する。
3. 大FFT向けのdownsamplingを実画面で評価する。
4. 固定形状のリング描画方式を試作し、コピー量とQImage再確保を比較する。

## ベンチマーク

通常ケースは次のコマンドで測定できます。

```bash
./.venv/bin/python tests/benchmarks/gui/benchmark_spectrogram_orientation.py
```

LUTサイズやFFT 65536を比較する場合:

```bash
./.venv/bin/python tests/benchmarks/gui/benchmark_spectrogram_orientation.py --lut-size 256
./.venv/bin/python tests/benchmarks/gui/benchmark_spectrogram_orientation.py --include-large
```

絶対時間はCIの合否条件にせず、同じ環境における変更前後の中央値とp95、QImage使用量を比較します。
pyqtgraphのImageItem性能指針も参照してください:
<https://pyqtgraph.readthedocs.io/en/pyqtgraph-0.14.0/api_reference/graphicsItems/imageitem.html>
