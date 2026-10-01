"""MIG-007-C: isolated QML Canvas vs wgpu readback/image-provider feasibility.

The PyQt host is only a spike adapter. No product widget, real audio, shared
Metal texture, or renderer adoption is implemented by this experiment.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
from pathlib import Path
import platform
import plistlib
import resource
import statistics
import subprocess
import sys
import threading
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
BINARY = ROOT / "native/renderer-spike/target/release/renderer-spike"
QML = ROOT / "native/renderer-spike/Spike.qml"
WIDTH, HEIGHT, ROWS = 1024, 256, 32


def values(points, frame):
    k = np.arange(points, dtype=np.uint32)
    result = np.float32(0.001) + ((k * 37 + frame * 101) % 4096).astype(np.float32) / np.float32(4096) * np.float32(
        0.09
    )
    result[(points // 3 + frame * 13) % points] = np.float32(0.8)
    return result


def digest(data):
    return hashlib.sha256(data).hexdigest()


def gpu_samples(stop, output):
    """Read whole-device Intel macOS counters; no elevated permissions or attribution."""
    if sys.platform != "darwin":
        return
    while not stop.is_set():
        try:
            raw = subprocess.check_output(["ioreg", "-a", "-r", "-c", "IOAccelerator"], timeout=2)  # noqa: S607
            for item in plistlib.loads(raw):
                stats = item.get("PerformanceStatistics", {})
                value = stats.get("Device Utilization %")
                if isinstance(value, (int, float)) and 0 <= value <= 100:
                    output.append({"monotonic_s": time.monotonic(), "device_utilization_percent": value})
        except (OSError, ValueError, subprocess.SubprocessError):
            return
        stop.wait(0.25)


def expected_cursor(points, low, high, fraction=0.5):
    return min(points - 1, int((low + (high - low) * fraction) * (points - 1) + 0.5))


class Worker:
    def __init__(self, kind, points, log):
        self.log = log.open("wb")
        self.process = subprocess.Popen(  # noqa: S603 - explicit local spike executable
            [str(BINARY)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.log, cwd=ROOT
        )
        self.closed = False
        try:
            self.send({"kind": kind, "points": points, "width": WIDTH, "height": HEIGHT})
            self.adapter = self.read_json()
        except Exception:
            self.abort()
            raise

    def abort(self):
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait(timeout=10)
        self.process.stdin.close()
        self.process.stdout.close()
        self.log.close()
        self.closed = True

    def send(self, document):
        self.process.stdin.write((json.dumps(document, separators=(",", ":")) + "\n").encode())
        self.process.stdin.flush()

    def read_json(self):
        line = self.process.stdout.readline()
        if not line:
            raise RuntimeError(f"GPU worker exited; inspect {self.log.name}")
        return json.loads(line)

    def receive(self):
        metadata = self.read_json()
        size = metadata["rgba_bytes"]
        if size != WIDTH * HEIGHT * 4:
            raise RuntimeError("unexpected GPU image size")
        data = self.process.stdout.read(size)
        if len(data) != size:
            raise RuntimeError("truncated GPU image")
        return metadata, data

    def render(self, frame, low, high):
        self.send({"frame": frame, "low": low, "high": high, "cursor": 0.5})
        return self.receive()

    def close(self):
        if self.closed:
            return None
        try:
            if self.process.poll() is None:
                self.send({"stop": True})
                result = self.read_json()
                if result != {"stopped": True, "gpu_owner_dropped": True}:
                    raise RuntimeError("GPU owner teardown missing")
                self.process.stdin.close()
                if self.process.wait(timeout=10):
                    raise RuntimeError("GPU worker failed during teardown")
                return result
            raise RuntimeError("GPU worker ended before stop")
        finally:
            self.abort()


def check_gpu(metadata, rgba, points, frame, low, high, kind):
    """Check actual pixels and original-data lookup against a CPU oracle."""
    data = values(points, frame)
    if metadata["input_sha256"] != digest(data.tobytes()):
        raise RuntimeError("GPU/baseline synthetic input bytes differ")
    bin_index = expected_cursor(points, low, high)
    if metadata["cursor_bin"] != bin_index or metadata["cursor_value"] != float(data[bin_index]):
        raise RuntimeError("cursor does not refer to original data")
    if abs(metadata["cursor_hz"] - bin_index * 24000 / (points - 1)) > 1e-7:
        raise RuntimeError("data-to-frequency mapping differs")
    pixels = np.frombuffer(rgba, dtype=np.uint8).reshape(HEIGHT, WIDTH, 4)
    if not np.all(pixels[:, :, 3] == 255):
        raise RuntimeError("unwritten GPU pixels")
    if kind == "spectrum":
        # A narrow moving peak must survive the screen-column reduction.
        peak = (points // 3 + frame * 13) % points
        fraction = peak / (points - 1)
        if low <= fraction < high:
            x = int((fraction - low) / (high - low) * WIDTH)
            y = int(-20 * np.log10(0.8) / 120 * (HEIGHT - 1))
            if not np.any(np.all(pixels[max(0, y - 2) : y + 3, max(0, x - 2) : x + 3, :3] == [98, 216, 233], axis=2)):
                raise RuntimeError("GPU reduction lost the narrow peak")
    else:
        # After wrap, every retained row must contain the correct historical frame.
        retained = min(frame + 1, ROWS)
        for age in range(retained):
            old = values(points, frame - age)
            # Use the exact pixel's fraction, rather than assuming a center column.
            x = WIDTH // 2
            k = int((low + (high - low) * x / (WIDTH - 1)) * (points - 1))
            level = np.clip((20 * np.log10(old[k]) + 100) / 100, 0, 1)
            expected = np.array([220 * level, 170 * level, 210 * (1 - level)])
            if np.max(np.abs(pixels[age * HEIGHT // ROWS, x, :3].astype(float) - expected)) > 2:
                raise RuntimeError(f"rolling image row {age} differs after frame {frame}")
    return {"input_sha256": metadata["input_sha256"], "cursor_bin": bin_index, "rgba_sha256": digest(rgba)}


def qt_run(args):
    # Keep the parent/oracle import path independent of Qt.
    from PyQt6.QtCore import QObject, QUrl, pyqtProperty, pyqtSignal, pyqtSlot, qVersion
    from PyQt6.QtGui import QGuiApplication, QImage
    from PyQt6.QtQml import QQmlApplicationEngine
    from PyQt6.QtQuick import QQuickImageProvider

    directory = args.output.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    worker = None
    app = QGuiApplication(["renderer-spike"])

    class Provider(QQuickImageProvider):
        def __init__(self):
            super().__init__(QQuickImageProvider.ImageType.Image)
            self.image = QImage()
            self.requests = 0

        def requestImage(self, _id, _size):
            self.requests += 1
            return self.image, self.image.size()

    class Backend(QObject):
        payloadChanged = pyqtSignal()
        serialChanged = pyqtSignal()

        def __init__(self):
            super().__init__()
            self.text = ""
            self.sequence = 0
            self.subscribers = 0
            self.cursor = None
            self.latest = None
            self.frame_index = 0

        @pyqtProperty(str, constant=True)
        def mode(self):
            return args.mode

        @pyqtProperty(str, constant=True)
        def kind(self):
            return args.kind

        @pyqtProperty(str, notify=payloadChanged)
        def payload(self):
            return self.text

        @pyqtProperty(int, notify=serialChanged)
        def serial(self):
            return self.sequence

        @pyqtSlot(result=float)
        def subscribe(self):
            self.subscribers += 1
            return float(self.subscribers)

        @pyqtSlot(float, result=bool)
        def unsubscribe(self, _token):
            self.subscribers -= 1
            return True

        @pyqtSlot(int, float, float)
        def recordCursor(self, index, hz, value):
            self.cursor = (index, hz, value)

        @pyqtSlot(float)
        def pick(self, fraction):
            index = expected_cursor(args.points, 0, 1, fraction)
            data = values(args.points, self.frame_index)
            window.setProperty(
                "cursorText", f"{index * 24000 / (args.points - 1):.2f} Hz · {float(data[index]):.6f} FS"
            )

    provider, backend = Provider(), Backend()
    engine = QQmlApplicationEngine()
    engine.addImageProvider("spike", provider)
    engine.rootContext().setContextProperty("backend", backend)
    engine.load(QUrl.fromLocalFile(str(QML)))
    if not engine.rootObjects():
        raise RuntimeError("spike QML did not load")
    window = engine.rootObjects()[0]
    swaps = [0]
    window.frameSwapped.connect(lambda: swaps.__setitem__(0, swaps[0] + 1))

    def pump_until(predicate, timeout=30):
        deadline = time.monotonic() + timeout
        while not predicate():
            app.processEvents()
            if time.monotonic() > deadline:
                raise RuntimeError("QML paint/presentation timeout")
            time.sleep(0.001)
        app.processEvents()

    def invoke(name):
        from PyQt6.QtCore import QMetaObject

        if not QMetaObject.invokeMethod(window, name):
            # PyQt returns None on successful void invocations.
            app.processEvents()

    evidence, samples, pending = [], [], []
    oracle_seconds = [0.0]
    adapter = None
    total_start = time.monotonic()
    self_start = resource.getrusage(resource.RUSAGE_SELF)
    child_start = resource.getrusage(resource.RUSAGE_CHILDREN)
    try:
        pump_until(lambda: swaps[0] > 0)
        if args.mode == "baseline":
            window.setProperty("height", window.height() + int(HEIGHT - window.property("dataHeight")))
            app.processEvents()
            pump_until(lambda: abs(window.property("dataHeight") - HEIGHT) < 1)
        if abs(window.property("dataWidth") - WIDTH) > 1 or abs(window.property("dataHeight") - HEIGHT) > 1:
            raise RuntimeError("renderer plot dimensions differ")
        if args.mode == "wgpu":
            worker = Worker(args.kind, args.points, directory / "gpu.log")
            adapter = worker.adapter

        def update(frame):
            low, high = window.property("viewLow"), window.property("viewHigh")
            before_swaps, before_paints, before_requests = swaps[0], window.property("paints"), provider.requests
            started = time.perf_counter()
            metadata = None
            backend.frame_index = frame
            if worker:
                metadata, rgba = worker.render(frame, low, high)
                provider.image = QImage(rgba, WIDTH, HEIGHT, WIDTH * 4, QImage.Format.Format_RGBA8888).copy()
                backend.sequence += 1
                backend.serialChanged.emit()
            else:
                backend.latest = values(args.points, frame)
                document = {
                    "result_id": str(frame),
                    "interval": [frame * args.points, (frame + 1) * args.points],
                    "frequency_hz": np.linspace(0, 24000, args.points).tolist(),
                    "source": {
                        "generation": 1,
                        "channel_ids": ["synthetic"],
                        "timebase": {"rate": {"numerator": 48000, "denominator": 1}},
                    },
                    "peak_fs": {"values": backend.latest.tolist(), "reasons": {}},
                }
                backend.text = json.dumps(document, separators=(",", ":"))
                if frame == 0:
                    print(
                        f"BASELINE_JSON frame=0 points={args.points} bytes={len(backend.text)} input_sha256={digest(backend.latest.tobytes())}",
                        flush=True,
                    )
                backend.payloadChanged.emit()
            pump_until(
                lambda: (
                    swaps[0] > before_swaps
                    and (provider.requests > before_requests if worker else window.property("paints") > before_paints)
                )
            )
            present_ms = (time.perf_counter() - started) * 1000
            if worker:
                pending.append((metadata, rgba, frame, low, high))
            else:
                evidence.append({"input_sha256": digest(backend.latest.tobytes()), "json_bytes": len(backend.text)})
            return {"present_ms": present_ms, "gpu": metadata}

        def verify_pending():
            check_start = time.perf_counter()
            for metadata, rgba, frame, low, high in pending:
                evidence.append(check_gpu(metadata, rgba, args.points, frame, low, high, args.kind))
            pending.clear()
            oracle_seconds[0] += time.perf_counter() - check_start

        for frame in range(args.warmup):
            update(frame)
        started = time.monotonic()
        for frame in range(args.warmup, args.warmup + args.frames):
            frame_start = time.monotonic()
            samples.append(update(frame))
            while time.monotonic() - frame_start < 1 / args.hz:
                app.processEvents()
                time.sleep(0.001)
        wall = time.monotonic() - started
        verify_pending()
        invoke("zoomIn")
        invoke("panRight")
        if (window.property("viewLow"), window.property("viewHigh")) != (0.375, 0.875):
            raise RuntimeError("QML zoom/pan mapping failed")
        frame = args.warmup + args.frames
        update(frame)
        verify_pending()
        invoke("readCursor")
        index = expected_cursor(args.points, 0.375, 0.875)
        if worker:
            data = values(args.points, frame)
            expected_text = f"{index * 24000 / (args.points - 1):.2f} Hz · {float(data[index]):.6f} FS"
            if window.property("cursorText") != expected_text:
                raise RuntimeError("QML cursor text does not reference original data")
        else:
            if (
                backend.cursor is None
                or backend.cursor[0] != index
                or backend.cursor[2] != float(backend.latest[index])
            ):
                raise RuntimeError("baseline cursor/coordinate conversion failed")
        screenshot = window.grabWindow()
        rgb = screenshot.convertToFormat(QImage.Format.Format_RGBA8888)
        pixels = np.frombuffer(rgb.bits().asstring(rgb.sizeInBytes()), dtype=np.uint8).reshape(
            rgb.height(), rgb.width(), 4
        )
        rgb_values = pixels[:, :, :3].astype(int)
        visible = int(np.count_nonzero((np.ptp(rgb_values, axis=2) > 50) & (np.max(rgb_values, axis=2) > 100)))
        if visible < 100:
            raise RuntimeError("QML did not present the colored plot")
        if not screenshot.save(str(directory / "qml.png")):
            raise RuntimeError("QML screenshot failed")
        if worker:
            if not provider.image.save(str(directory / "gpu.png")):
                raise RuntimeError("GPU evidence image failed")
        window.setProperty("loaded", False)
        app.processEvents()
        if args.mode == "baseline":
            pump_until(lambda: backend.subscribers == 0)
        window.setProperty("loaded", True)
        app.processEvents()
        update(frame + 1)
        verify_pending()
        if args.mode == "baseline" and backend.subscribers != 1:
            raise RuntimeError("QML view subscription was not recreated")
        lifecycle = {"view_destroy_recreate": True}
        if worker:
            lifecycle["first_worker_stop"] = worker.close()
            worker = Worker(args.kind, args.points, directory / "gpu-recreate.log")
            invoke("reset")
            # A recreated GPU owner must not reuse the preceding image's ring history.
            update(0)
            verify_pending()
            if evidence[-1]["input_sha256"] != evidence[0]["input_sha256"]:
                raise RuntimeError("GPU recreation input mismatch")
            worker.send({"frame": 1, "low": 0.0, "high": 1.0, "cursor": 0.5})
            window.close()
            window = None
            del engine
            gc.collect()
            app.processEvents()
            metadata, rgba = worker.receive()
            check_gpu(metadata, rgba, args.points, 1, 0, 1, args.kind)
            lifecycle["qml_destroy_during_gpu_update"] = True
            lifecycle["final_worker_stop"] = worker.close()
            worker = None
        else:
            window.close()
            window = None
            del engine
            gc.collect()
            app.processEvents()
            if backend.subscribers != 0:
                raise RuntimeError("final QML subscription leaked")
        self_end = resource.getrusage(resource.RUSAGE_SELF)
        child_end = resource.getrusage(resource.RUSAGE_CHILDREN)
        cpu_self = self_end.ru_utime + self_end.ru_stime - self_start.ru_utime - self_start.ru_stime
        cpu_child = child_end.ru_utime + child_end.ru_stime - child_start.ru_utime - child_start.ru_stime
        total_wall = time.monotonic() - total_start
        latencies = [row["present_ms"] for row in samples]
        gpu = [row["gpu"]["gpu_ms"] for row in samples if row["gpu"] and row["gpu"]["gpu_ms"] is not None]
        report = {
            "mode": args.mode,
            "kind": args.kind,
            "points": args.points,
            "qt": qVersion(),
            "platform": app.platformName(),
            "qt_backend": os.environ.get("QT_QUICK_BACKEND"),
            "dimensions": [WIDTH, HEIGHT],
            "visible_colored_pixels": visible,
            "target_hz": args.hz,
            "warmup": args.warmup,
            "frames": args.frames,
            "wall_s": wall,
            "present_hz": args.frames / wall,
            "median_present_ms": statistics.median(latencies),
            "p95_present_ms": float(np.percentile(latencies, 95)),
            "measurement_monotonic_s": [started, started + wall],
            "oracle_seconds": oracle_seconds[0],
            "timing_scope": "presentation includes generation/transport/paint; full GPU pixel oracle runs after timed update loop",
            "missed_frame_budget": sum(v > 1000 / args.hz for v in latencies),
            "adapter": adapter,
            "dtype": "f32 source; f64 frequency axis in baseline JSON",
            "copy_operations": {
                "input_upload_calls": 1 if args.mode == "wgpu" else 0,
                "uniform_upload_calls": 1 if args.mode == "wgpu" else 0,
                "gpu_readback_copy_calls": 1 if args.mode == "wgpu" else 0,
                "readback_to_vec_copies": 1 if args.mode == "wgpu" else 0,
                "qimage_copy_calls": 1 if args.mode == "wgpu" else 0,
                "ipc_rgba_bytes": WIDTH * HEIGHT * 4 if args.mode == "wgpu" else 0,
                "baseline_array_boxing_calls": 2 if args.mode == "baseline" else 0,
                "baseline_json_encode_decode": args.mode == "baseline",
                "scope": "explicit code operations per update; IPC/kernel/Qt/driver internal copies and physical UMA transfers unknown",
            },
            "median_gpu_ms": statistics.median(gpu) if gpu else None,
            "cpu_self_s": cpu_self,
            "cpu_child_s": cpu_child,
            "cpu_full_run_percent": (cpu_self + cpu_child) / total_wall * 100,
            "cpu_scope": "warmup, measurement, interaction, lifecycle; GPU worker init is included in child CPU",
            "self_peak_rss_raw": self_end.ru_maxrss,
            "child_peak_rss_raw": child_end.ru_maxrss,
            "rss_unit": "bytes" if sys.platform == "darwin" else "KiB",
            "lifecycle": lifecycle,
            "evidence": evidence,
            "samples": samples,
        }
        (directory / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        print(f"RENDERER_PASS {args.mode} {args.kind} {args.points}: {report['present_hz']:.2f} Hz", flush=True)
    finally:
        if worker is not None:
            worker.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--frames", type=int, default=30)
    parser.add_argument("--warmup", type=int, default=3)
    parser.add_argument("--hz", type=float, default=30)
    parser.add_argument("--qt-run", action="store_true")
    parser.add_argument("--mode", choices=("baseline", "wgpu"))
    parser.add_argument("--kind", choices=("spectrum", "spectrogram"))
    parser.add_argument("--points", type=int)
    args = parser.parse_args()
    if not (1 <= args.repeat <= 10 and 1 <= args.frames <= 120 and 1 <= args.warmup <= 100 and 0 < args.hz <= 120):
        parser.error("invalid benchmark bounds")
    if args.qt_run:
        if args.mode is None or args.kind is None or args.points is None:
            parser.error("Qt child requires mode/kind/points")
        qt_run(args)
        return
    if not BINARY.is_file():
        parser.error("build the isolated release renderer first")
    args.output.mkdir(parents=True, exist_ok=False)
    reports, failures = [], []
    env = {**os.environ, "QT_QUICK_CONTROLS_STYLE": "Basic"}
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    env.setdefault("QT_QUICK_BACKEND", "software")
    for mode in ("baseline", "wgpu"):
        for kind, points in (("spectrum", 100_000), ("spectrum", 1_000_000), ("spectrogram", 1024)):
            for repeat in range(args.repeat):
                path = args.output / f"{mode}-{kind}-{points}-{repeat}"
                command = [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    "--qt-run",
                    "--output",
                    str(path),
                    "--mode",
                    mode,
                    "--kind",
                    kind,
                    "--points",
                    str(points),
                    "--frames",
                    str(max(40, args.frames) if kind == "spectrogram" else args.frames),
                    "--warmup",
                    str(args.warmup),
                    "--hz",
                    str(args.hz),
                ]
                stop_monitor = threading.Event()
                counters = []
                monitor = threading.Thread(target=gpu_samples, args=(stop_monitor, counters), daemon=True)
                monitor.start()
                run_start = time.monotonic()
                try:
                    result = subprocess.run(  # noqa: S603 - bounded local diagnostic process
                        command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=240, check=False
                    )
                    output, code = result.stdout + result.stderr, result.returncode
                except subprocess.TimeoutExpired as error:
                    output, code = f"timeout: {error}", None
                finally:
                    stop_monitor.set()
                    monitor.join(timeout=3)
                path.mkdir(parents=True, exist_ok=True)
                (path / "command.log").write_text(output)
                errors = ("RENDERER_FAIL", "Traceback", "Error:", "ReferenceError", "failed to load component")
                if (
                    code != 0
                    or "RENDERER_PASS" not in output
                    or any(e in output for e in errors)
                    or not (path / "report.json").is_file()
                ):
                    failures.append(
                        {
                            "path": str(path),
                            "code": code,
                            "mode": mode,
                            "kind": kind,
                            "points": points,
                            "repeat": repeat,
                            "wall_s": time.monotonic() - run_start,
                        }
                    )
                    print(f"RENDERER_FAIL {path.name}: {code}", flush=True)
                else:
                    report = json.loads((path / "report.json").read_text())
                    report["system_gpu_samples"] = counters
                    report["system_gpu_scope"] = (
                        "whole-device counter, 250ms polling; measured interval only; other applications included"
                    )
                    report["child_process_wall_s"] = time.monotonic() - run_start
                    a, b = report["measurement_monotonic_s"]
                    measured = [c["device_utilization_percent"] for c in counters if a <= c["monotonic_s"] <= b]
                    report["median_system_gpu_percent"] = statistics.median(measured) if measured else None
                    report["gpu_measurement_sample_count"] = len(measured)
                    (path / "report.json").write_text(json.dumps(report, indent=2) + "\n")
                    reports.append(report)
                    print(next(line for line in output.splitlines() if line.startswith("RENDERER_PASS")), flush=True)
    sources = [
        QML,
        ROOT / "native/qml/SpectrumView.qml",
        Path(__file__).resolve(),
        *sorted((ROOT / "native/renderer-spike/src").glob("*")),
        ROOT / "native/renderer-spike/Cargo.toml",
        ROOT / "native/renderer-spike/Cargo.lock",
        BINARY,
    ]
    summary = {
        "date": "2026-10-01",
        "host": platform.platform(),
        "python": sys.version,
        "runs": reports,
        "failures": failures,
        "source_hashes": {str(p.relative_to(ROOT)): digest(p.read_bytes()) for p in sources},
        "limits": [
            "feasibility only; no adoption or individual widget implementation",
            "PyQt image-provider bridge, no CXX-Qt/Qt Bridge shared GPU texture",
            "Qt software/offscreen presentation; GPU pass timings are not device utilization",
            "synthetic data; no actual acquisition/analysis or 10-minute performance/other OS verification",
        ],
    }
    (args.output / "report.json").write_text(json.dumps(summary, indent=2) + "\n")
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
