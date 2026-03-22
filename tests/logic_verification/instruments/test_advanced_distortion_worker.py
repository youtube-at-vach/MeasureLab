import numpy as np
from src.gui.widgets.advanced_distortion_meter import AnalysisWorker


def test_analysis_worker_mim():
    # Setup
    sr = 48000
    buffer_size = 8192  # Smaller for test speed
    data = np.random.normal(0, 0.1, buffer_size)

    # Generate 3 tones
    freqs_mim = np.array([1000.0, 2000.0, 5000.0])
    t = np.arange(buffer_size) / sr
    for f in freqs_mim:
        data += 0.5 * np.sin(2 * np.pi * f * t)

    params = {"mim_freqs": freqs_mim}
    mode = "MIM"

    worker = AnalysisWorker(data, sr, mode, params)

    # Capture results
    results = []

    def on_result(res):
        results.append(res)

    worker.signals.result_ready.connect(on_result)

    # Run
    worker.run()

    # Assert
    assert len(results) == 1
    res = results[0]
    assert res["mode"] == "MIM"
    assert "mim" in res["metrics"]
    assert "tdn" in res["metrics"]["mim"]
    assert "tdn_db" in res["metrics"]["mim"]

    # Check if correct keys are present
    assert len(res["freqs"]) == buffer_size // 2 + 1
    assert len(res["mag_db"]) == buffer_size // 2 + 1


def test_analysis_worker_spdr():
    sr = 48000
    buffer_size = 4096
    t = np.arange(buffer_size) / sr
    data = 0.8 * np.sin(2 * np.pi * 1000.0 * t)  # Fundamental
    data += 0.001 * np.sin(2 * np.pi * 2500.0 * t)  # Spur

    params = {}
    mode = "SPDR"

    worker = AnalysisWorker(data, sr, mode, params)

    results = []
    worker.signals.result_ready.connect(lambda r: results.append(r))

    worker.run()

    assert len(results) == 1
    res = results[0]
    assert res["mode"] == "SPDR"
    assert "spdr" in res["metrics"]
    assert res["metrics"]["spdr"]["spdr_db"] > 0


def test_analysis_worker_pim():
    sr = 48000
    buffer_size = 4096
    t = np.arange(buffer_size) / sr
    f1 = 1800.0
    f2 = 2100.0

    data = 0.4 * np.sin(2 * np.pi * f1 * t) + 0.4 * np.sin(2 * np.pi * f2 * t)
    # Add PIM product (IM3: 2f1 - f2 = 3600 - 2100 = 1500)
    data += 0.001 * np.sin(2 * np.pi * 1500.0 * t)

    params = {"f1": f1, "f2": f2}
    mode = "PIM"

    worker = AnalysisWorker(data, sr, mode, params)

    results = []
    worker.signals.result_ready.connect(lambda r: results.append(r))

    worker.run()

    assert len(results) == 1
    res = results[0]
    assert res["mode"] == "PIM"
    assert "pim" in res["metrics"]
    assert res["metrics"]["pim"]["pim_db"] > -140
    # Should detect products
    assert len(res["metrics"]["pim"]["products"]) > 0
