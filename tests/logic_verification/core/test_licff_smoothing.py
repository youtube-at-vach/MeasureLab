import numpy as np
from src.gui.widgets.feedforward_compensator import LICFFEngine


def test_licff_smoothing_effect():
    # 鋭いディップを持つ linear impulse response (h1) を設計する
    # h = [1.0, 0.0, ..., -0.9] -> これにより特定の周波数で深いノッチ（打消し）が発生する
    N_taps = 256
    h1 = np.zeros(N_taps)
    h1[0] = 1.0
    h1[10] = -0.9  # 深いディップを発生させる反射成分
    
    # 2次以降のカーネル（LICFFEngineに必要なモックデータ）
    h2 = np.zeros(N_taps)
    h3 = np.zeros(N_taps)
    h4 = np.zeros(N_taps)
    h5 = np.zeros(N_taps)
    
    mock_model_data = {
        "metadata": {
            "sample_rate": 48000,
            "g_ref": 1.0,
        },
        "time_domain": {
            "kernels": {
                "h1": h1.tolist(),
                "h2": h2.tolist(),
                "h3": h3.tolist(),
                "h4": h4.tolist(),
                "h5": h5.tolist(),
            }
        }
    }
    
    # 1. スムージングなしのエンジン
    engine_no_smooth = LICFFEngine(
        mock_model_data,
        f_min=20.0,
        f_max=20000.0,
        reg_mode="manual_tikhonov",
        reg_val=1e-5,
        out_of_band_mode="cut",
        linear_smoothing_fraction=0.0
    )
    
    # 2. スムージングありのエンジン (1/12 オクターブ平滑化)
    engine_smooth = LICFFEngine(
        mock_model_data,
        f_min=20.0,
        f_max=20000.0,
        reg_mode="manual_tikhonov",
        reg_val=1e-5,
        out_of_band_mode="cut",
        linear_smoothing_fraction=12.0
    )
    
    # バッファの準備と逆フィルターの取得
    Q_fft_no, F_inv_no, _, _ = engine_no_smooth._prepare_buffers_for_length(N_taps)
    Q_fft_sm, F_inv_sm, _, _ = engine_smooth._prepare_buffers_for_length(N_taps)
    
    # 振幅特性의 比較
    mag_no = np.abs(F_inv_no)
    mag_sm = np.abs(F_inv_sm)
    
    # スムージングありのほうが、急峻なディップを補うための極端な逆フィルターブーストが抑えられていることを検証
    assert np.max(mag_sm) < np.max(mag_no)
    
    # 位相が正確に保存されていることを検証 (元の位相特性と一致すること)
    phase_no = np.angle(F_inv_no)
    phase_sm = np.angle(F_inv_sm)
    np.testing.assert_allclose(phase_sm, phase_no, rtol=1e-5, atol=1e-5)
