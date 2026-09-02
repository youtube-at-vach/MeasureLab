import { defineConfig } from 'astro/config';
import { unified } from '@astrojs/markdown-remark';
import starlight from '@astrojs/starlight';
import rehypeClassNames from 'rehype-class-names';
import rehypeKatex from 'rehype-katex';
import { remarkHeadingId } from 'remark-custom-heading-id';
import remarkMath from 'remark-math';

const doc = (label, englishLabel, slug) => ({
  label,
  translations: { en: englishLabel },
  slug,
});

const group = (label, englishLabel, items) => ({
  label,
  translations: { en: englishLabel },
  items,
});

export default defineConfig({
  site: 'https://youtube-at-vach.github.io',
  base: '/MeasureLab',
  trailingSlash: 'always',
  integrations: [
    starlight({
      title: {
        ja: 'MeasureLab オペレーションマニュアル',
        en: 'MeasureLab Operation Manual',
      },
      description: 'MeasureLab audio and signal measurement documentation',
      favicon: '/favicon.png',
      defaultLocale: 'root',
      locales: {
        root: { label: '日本語', lang: 'ja' },
        en: { label: 'English', lang: 'en' },
      },
      social: [
        {
          icon: 'github',
          label: 'GitHub',
          href: 'https://github.com/youtube-at-vach/MeasureLab',
        },
      ],
      editLink: {
        baseUrl: 'https://github.com/youtube-at-vach/MeasureLab/edit/main/docs-site/',
      },
      lastUpdated: true,
      pagefind: true,
      customCss: ['katex/dist/katex.min.css', './src/styles/custom.css'],
      sidebar: [
        doc('ホーム', 'Home', 'index'),
        doc('クイックスタート', 'Quick Start', 'quickstart'),
        group('はじめに', 'Getting Started', [
          doc('キャリブレーション', 'Calibration', 'calibration'),
          doc('UI概要', 'UI Overview', 'widget_guide'),
        ]),
        group('ウィジット', 'Widgets', [
          group('基本', 'Basics', [
            doc('ようこそ', 'Welcome', 'widgets/welcome'),
            doc('設定', 'Settings', 'widgets/settings'),
            doc('リモート音声I/O', 'Remote Audio I/O', 'widgets/remote_audio_io'),
          ]),
          group('信号生成と入出力', 'Signal Generation & I/O', [
            doc('信号発生器', 'Signal Generator', 'widgets/signal_generator'),
            doc(
              '任意高調波ジェネレーター',
              'Arbitrary Harmonic Generator',
              'widgets/arbitrary_harmonic_generator',
            ),
            doc('録音・再生', 'Recorder / Player', 'widgets/recorder_player'),
            doc('ループバック検出', 'Loopback Finder', 'widgets/loopback_finder'),
            doc('生時系列', 'Raw Time Series', 'widgets/raw_time_series'),
          ]),
          group('信号可視化', 'Signal Visualization', [
            doc('オシロスコープ', 'Oscilloscope', 'widgets/oscilloscope'),
            doc(
              'スペクトラムアナライザー',
              'Spectrum Analyzer',
              'widgets/spectrum_analyzer',
            ),
            doc('スペクトログラム', 'Spectrogram', 'widgets/spectrogram'),
            doc('ゴニオメーター', 'Goniometer', 'widgets/goniometer'),
            doc(
              'ステレオ位置合わせモニター',
              'Stereo Alignment Monitor',
              'widgets/stereo_alignment_monitor',
            ),
          ]),
          group('精密測定', 'Precision Measurement', [
            doc('ロックインアンプ', 'Lock-in Amplifier', 'widgets/lock_in_amplifier'),
            doc(
              'ロックイン周波数カウンター',
              'Lock-in Frequency Counter',
              'widgets/lock_in_frequency_counter',
            ),
            doc(
              'ロックイン高調波解析',
              'Lock-in Harmonic Analyzer',
              'widgets/lockin_harmonic_analyzer',
            ),
            doc(
              'ロックインスペクトラム検出',
              'Lock-in Spectrum Finder',
              'widgets/lockin_spectrum_finder',
            ),
            doc('ロックインモデラー', 'Lock-in Modeler', 'widgets/lock_in_modeler'),
            doc('周波数カウンター', 'Frequency Counter', 'widgets/frequency_counter'),
            doc(
              '高度歪みメーター',
              'Advanced Distortion Meter',
              'widgets/advanced_distortion_meter',
            ),
            doc('歪み解析', 'Distortion Analyzer', 'widgets/distortion_analyzer'),
            doc('非線形解析', 'Nonlinear Analyzer', 'widgets/nonlinear_analyzer'),
            doc('応答ビューア', 'Response Viewer', 'widgets/response_viewer'),
            doc(
              'フィードフォワード歪み補正',
              'Feedforward Compensator',
              'widgets/feedforward_compensator',
            ),
            doc('直線性解析', 'Linearity Analyzer', 'widgets/linearity_analyzer'),
          ]),
          group('音響・オーディオ解析', 'Acoustic & Audio Analysis', [
            doc(
              '音圧レベルメーター',
              'Sound Level Meter',
              'widgets/sound_level_meter',
            ),
            doc('LUFSメーター', 'LUFS Meter', 'widgets/lufs_meter'),
            doc('音質解析', 'Sound Quality Analyzer', 'widgets/sound_quality_analyzer'),
            doc('ノイズプロファイラー', 'Noise Profiler', 'widgets/noise_profiler'),
            doc('イベント検出器', 'Event Detector', 'widgets/event_detector'),
            doc('過渡解析', 'Transient Analyzer', 'widgets/transient_analyzer'),
            doc('BNIMメーター', 'BNIM Meter', 'widgets/bnim_meter'),
          ]),
          group('デバイス・システム解析', 'Device & System Analysis', [
            doc('インピーダンス解析', 'Impedance Analyzer', 'widgets/impedance_analyzer'),
            doc('ネットワーク解析', 'Network Analyzer', 'widgets/network_analyzer'),
            doc('HRTFプレイヤー', 'HRTF Player', 'widgets/hrtf_player'),
            doc(
              '空間バイノーラルミキサー',
              'Spatial Binaural Mixer',
              'widgets/spatial_binaural_mixer',
            ),
            doc('超音波変調器', 'Ultrasound Modulator', 'widgets/ultrasound_modulator'),
            doc('伝送路解析', 'Transmission Analyzer', 'widgets/transmission_analyzer'),
          ]),
          group('タイミング・基準信号', 'Timing & Reference', [
            doc('1PPSモニター', '1PPS Monitor', 'widgets/one_pps_monitor'),
            doc('タイムコードモニター', 'Timecode Monitor', 'widgets/timecode_monitor'),
            doc('ボックスカー平均器', 'Boxcar Averager', 'widgets/boxcar_averager'),
          ]),
          group('ユーティリティ', 'Utilities', [
            doc(
              '分離ウィンドウラッパー',
              'Detachable Wrapper',
              'widgets/detachable_wrapper',
            ),
            doc(
              '計測コンソール（試験的機能）',
              'Measurement Console (Experimental)',
              'widgets/measurement_console',
            ),
            doc('プロット比較器', 'Plot Comparer', 'widgets/plot_comparer'),
            doc(
              'プロセッサーベンチマーク',
              'Processor Benchmark',
              'widgets/processor_benchmark',
            ),
            doc(
              '波形ループプレイヤー',
              'Waveform Loop Player',
              'widgets/waveform_loop_player',
            ),
            doc('ログビューアー', 'Log Viewer', 'widgets/log_viewer'),
          ]),
        ]),
        group('測定レシピ', 'Measurement Recipes', [
          doc('概要', 'Overview', 'measurement_recipes'),
          doc('ノイズ測定', 'Noise Measurement', 'measurement_recipes/noise_measurement'),
          doc(
            '歪み測定',
            'Distortion Measurement',
            'measurement_recipes/distortion_measurement',
          ),
          doc(
            'スピーカーインピーダンス',
            'Speaker Impedance',
            'measurement_recipes/speaker_impedance',
          ),
          doc(
            'ロックインアンプ',
            'Lock-in Amplifier',
            'measurement_recipes/lockin_amplifier',
          ),
        ]),
        group('リファレンス', 'Reference', [
          doc('用語集', 'Glossary', 'glossary'),
          doc('付録', 'Appendix', 'appendix'),
          doc('開発情報', 'Development', 'development'),
          doc('提案機能', 'Proposed Features', 'PROPOSED_FEATURES'),
          {
            label: 'リリースページ',
            translations: { en: 'Release Page' },
            link: 'https://github.com/youtube-at-vach/MeasureLab/releases/',
          },
        ]),
        {
          label: 'ダウンロード',
          translations: { en: 'Download' },
          link: 'https://youtube-at-vach.github.io/MeasureLab/download/',
        },
      ],
    }),
  ],
  markdown: {
    processor: unified({
      remarkPlugins: [remarkHeadingId, remarkMath],
      rehypePlugins: [rehypeKatex, [rehypeClassNames, { '.katex': 'not-content' }]],
    }),
  },
  vite: {
    ssr: { noExternal: ['katex'] },
  },
});
