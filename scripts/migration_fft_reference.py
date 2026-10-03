"""Generate or verify versioned FFT reference files without Qt or audio devices.

Generation is an explicit command into a new directory. Verification never writes
fixtures. The product methods are source-pinned; Spectrum's exact method AST is
executed with explicit state rather than importing its GUI/audio module.
"""

from __future__ import annotations

import argparse
import ast
from contextlib import contextmanager
import hashlib
from importlib.metadata import distributions
import json
import os
from pathlib import Path
import platform
import sys
import tempfile
import time
from types import SimpleNamespace

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import migration_fft_oracle as oracle  # noqa: E402

REFERENCE_COMMIT = "9fd79958f6a8bbae6808813d3704617612e6d26c"
SCHEMA_VERSION = 1
CONTRACT = "MIG-002-numerics-v0.1"
# SHA-256 of `git show 9fd79958:<path>`, also usable from shallow CI checkouts.
PINNED_SOURCE_SHA256 = {
    "src/__init__.py": "9c302e24d402a6668fe8c5fd2d76de9fb18045c5a0beaa6c3a761b7e49f4582c",
    "src/core/__init__.py": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "src/core/fft_manager.py": "307a4c95130fed46e25afd9730fd8669cdd9fd8fbaee97c0d0a2c12aaafcaef6",
    "src/core/analysis.py": "6afa44940331814323bdd794ae076c63d014148a6dcd0a122ee7fceb39df3e2c",
    "src/core/localization.py": "37f0b9bd2e00539f245057e3b584d26815c90f75c466f2c50c39ec8376ad5617",
    "src/core/utils.py": "89639b5654fcf8a8196005e945d4dec2a970ca761fbf5d8e43e07838346269d5",
    "src/gui/widgets/spectrum_analyzer.py": "0829288791037f4c5b1e2c49ba8c5593d645b4bc623cf6989279b50ff6d49c0a",
}
GENERATOR_PATHS = ("scripts/migration_fft_reference.py", "scripts/migration_fft_oracle.py")
DEFAULT_FIXTURES = ROOT / "migration/fixtures/fft-v1"
TOLERANCES = {
    "window": {"atol": 1e-12, "rtol": 1e-12},
    "f64": {"atol": 2e-11, "rtol": 1e-9},
    "f32": {"atol": 2e-6, "rtol": 2e-5},
    "phase_f64": {"atol": 1e-7, "rtol": 0},
    "phase_f32": {"atol": 1e-4, "rtol": 0},
    "db_f64": {"atol": 1e-5, "rtol": 0},
    "db_f32": {"atol": 1e-3, "rtol": 0},
}


class ReferenceError(ValueError):
    """Invalid provenance, fixture bytes, schema or numerical result."""


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def source_hashes(root: Path = ROOT) -> dict[str, str]:
    result = {}
    for name, baseline in PINNED_SOURCE_SHA256.items():
        data = (root / name).read_bytes()
        if digest(data) != baseline:
            raise ReferenceError(f"Reference source differs from {REFERENCE_COMMIT}: {name}")
        result[name] = digest(data)
    return result


def generator_hashes() -> dict[str, str]:
    return {name: digest((ROOT / name).read_bytes()) for name in GENERATOR_PATHS}


def environment() -> dict:
    return {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "os": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "logical_cpus": os.cpu_count(),
        "packages": dict(sorted((d.metadata["Name"], d.version) for d in distributions() if d.metadata["Name"])),
        "fft": {"backend": "pyfftw", "plan": "FFTW_ESTIMATE", "threads": 1, "wisdom": "empty temporary directory"},
    }


@contextmanager
def reference_backend():
    """Import once in a standalone process, with isolated and empty FFT wisdom."""
    if "src.core.fft_manager" in sys.modules:
        raise ReferenceError("Run the reference in a fresh process (FFT singleton already imported)")
    old_env = {key: os.environ.get(key) for key in ("XDG_DATA_HOME", "MEASURELAB_TESTING")}
    with tempfile.TemporaryDirectory(prefix="measurelab-fft-") as temporary:
        os.environ.update(XDG_DATA_HOME=temporary, MEASURELAB_TESTING="0")
        try:
            from src.core.fft_manager import HAS_PYFFTW, fft_manager
            from src.core.analysis import get_cached_window

            if not HAS_PYFFTW:
                raise ReferenceError("pyfftw is required; silently changing the reference backend is not allowed")
            import pyfftw

            pyfftw.forget_wisdom()
            pyfftw.config.NUM_THREADS = 1
            fft_manager.threads = 1
            yield fft_manager, get_cached_window
        finally:
            for key, value in old_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


def spectrum_method(manager, get_window):
    """Compile the unchanged method, not a reimplementation or a Qt stub."""
    path = ROOT / "src/gui/widgets/spectrum_analyzer.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "SpectrumAnalyzer")
    method = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == "_compute_standard")
    namespace = {"np": np, "fft_manager": manager, "get_cached_window": get_window}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(path), "exec"), namespace)
    return namespace["_compute_standard"]


def legacy_endpoints(spec, x, manager, get_window) -> list[dict]:
    if spec["signal"] not in ("dc", "nyquist") or spec["window"] != "boxcar":
        return []
    compute = spectrum_method(manager, get_window)
    bin_index = 0 if spec["signal"] == "dc" else spec["n"] // 2
    stereo = np.repeat(x, 2, axis=1)
    rows = []
    # Zero dB calibration offset means 1 V/FS; no real profile/device is loaded.
    calibration = SimpleNamespace(get_input_offset_db=lambda: 0.0)
    for mode, unit, theory_linear, meaning in (
        ("Spectrum", "dBFS", 0.125, "peak_FS"),
        ("Spectrum", "dBV", 0.125, "RMS_V_at_1_V_per_FS"),
        ("PSD", "dBFS", 0.125 * np.sqrt(spec["n"] / spec["rate_hz"]), "ASD_FS_per_sqrt_Hz"),
    ):
        state = SimpleNamespace(
            window_type="rect",
            channel_mode="Left",
            analysis_mode=mode,
            display_unit=unit,
            averaging=0.0,
            _avg_magnitude=None,
            audio_engine=SimpleNamespace(calibration=calibration),
        )
        db, _, _ = compute(state, stereo, spec["rate_hz"])
        rows.append(
            {
                "mode": mode,
                "display_unit": unit,
                "meaning": meaning,
                "bin": bin_index,
                "current_db": float(db[bin_index]),
                "theory_linear": float(theory_linear),
                "theory_db": float(20 * np.log10(theory_linear)),
                "difference_db": float(db[bin_index] - 20 * np.log10(theory_linear)),
                "reason": "all bins doubled" if unit == "dBFS" and mode == "Spectrum" else "endpoint sqrt(2) excess",
            }
        )
    return rows


def current(spec: dict, x: np.ndarray, manager, get_window) -> dict[str, np.ndarray]:
    n = spec["n"]
    w = get_window(spec["window"], n, fftbins=False)
    # f32 transform is explicit; Spectrum's own method promotes its window to f64.
    windowed = np.asarray(x * w.astype(x.dtype)[:, None], dtype=x.dtype)
    raw = np.column_stack([manager.rfft(channel) for channel in windowed.T])
    inverse = np.column_stack([manager.irfft(channel, n=n) for channel in raw.T])
    dtype_name = "float32" if spec["dtype"] == "<f4" else "float64"
    for direction in ("FFTW_FORWARD", "FFTW_BACKWARD"):
        if (n, dtype_name, direction) not in manager._plans:
            raise ReferenceError("FFTManager fell back to NumPy; reference backend changed")
    z = raw.astype(np.complex128) / n
    result = {"window": w, "fft_over_n": z, "inverse_windowed": inverse, **oracle.quantities(z, w, x, spec["rate_hz"])}
    result["frequency_hz"] = manager.rfftfreq(n, 1 / spec["rate_hz"])
    return result


def compare(actual, expected, tolerance: dict, label: str) -> float:
    actual, expected = np.asarray(actual), np.asarray(expected)
    if actual.shape != expected.shape:
        raise ReferenceError(f"{label}: shape mismatch: {actual.shape} != {expected.shape}")
    if not np.isfinite(actual).all() or not np.isfinite(expected).all():
        raise ReferenceError(f"{label}: nonfinite value")
    error = np.abs(actual - expected)
    if np.any(error > tolerance["atol"] + tolerance["rtol"] * np.abs(expected)):
        raise ReferenceError(f"{label}: numerical mismatch (max absolute error {np.max(error)})")
    return float(np.max(error, initial=0))


def evaluate(spec, observed, expected) -> dict:
    precision = "f32" if spec["dtype"] == "<f4" else "f64"
    tolerance = TOLERANCES[precision]
    errors = {
        key: compare(observed[key], value, TOLERANCES["window"] if key == "window" else tolerance, key)
        for key, value in expected.items()
    }
    errors["parseval"] = compare(
        observed["integrated_power_fs2"], expected["time_window_power_fs2"], tolerance, "PSD integral vs time power"
    )
    # Wrapped phase and dB are judged only where their contract is defined.
    threshold = 1e-4 if precision == "f32" else 1e-8
    phase_mask = expected["peak_fs"] >= threshold
    phase_error = np.angle(observed["fft_over_n"][phase_mask] * np.conj(expected["fft_over_n"][phase_mask]))
    errors["phase_rad"] = compare(phase_error, np.zeros_like(phase_error), TOLERANCES[f"phase_{precision}"], "phase")
    db_mask = expected["peak_fs"] >= (1e-4 if precision == "f32" else 1e-6)
    errors["peak_db"] = compare(
        20 * np.log10(observed["peak_fs"][db_mask]),
        20 * np.log10(expected["peak_fs"][db_mask]),
        TOLERANCES[f"db_{precision}"],
        "peak dB",
    )
    return {
        "max_absolute_errors": errors,
        "phase_tested_bins": int(np.count_nonzero(phase_mask)),
        "phase_below_threshold": {"value": None, "reason": "below phase threshold; compare complex FFT only"},
        "db_tested_bins": int(np.count_nonzero(db_mask)),
        "rms_fs": observed["rms_fs"].tolist(),
        "integrated_power_fs2": observed["integrated_power_fs2"].tolist(),
    }


def store_array(directory: Path, name: str, values, origin: str) -> dict:
    values = np.asarray(values)
    complex_value = np.iscomplexobj(values)
    if complex_value:
        values = np.stack((values.real, values.imag), axis=-1)
    dtype = "<f4" if values.dtype == np.dtype("float32") else "<f8"
    values = np.ascontiguousarray(values, dtype=dtype)
    path = directory / f"{name}.bin"
    data = values.tobytes()
    path.write_bytes(data)
    return {
        "file": path.name,
        "sha256": digest(data),
        "dtype": dtype,
        "shape": list(values.shape),
        "layout": "C/frame-major",
        "byte_order": "little",
        "complex": "real-imag-last-axis" if complex_value else None,
        "origin": origin,
    }


def read_array(directory: Path, entry: dict) -> np.ndarray:
    name = entry["file"]
    if not isinstance(name, str) or Path(name).name != name or not name.endswith(".bin"):
        raise ReferenceError("Invalid array path")
    if entry["dtype"] not in ("<f4", "<f8") or entry["byte_order"] != "little" or entry["layout"] != "C/frame-major":
        raise ReferenceError(f"{name}: unsupported dtype/byte order/layout")
    shape = entry["shape"]
    if not isinstance(shape, list) or not shape or any(type(size) is not int or size <= 0 for size in shape):
        raise ReferenceError(f"{name}: invalid shape")
    data = (directory / name).read_bytes()
    if digest(data) != entry["sha256"]:
        raise ReferenceError(f"{name}: SHA-256 mismatch")
    dtype = np.dtype(entry["dtype"])
    import math

    if math.prod(shape) * dtype.itemsize != len(data):
        raise ReferenceError(f"{name}: shape/byte count mismatch")
    array = np.frombuffer(data, dtype=dtype).reshape(shape)
    if not np.isfinite(array).all():
        raise ReferenceError(f"{name}: nonfinite value")
    if entry["complex"] == "real-imag-last-axis":
        if shape[-1] != 2:
            raise ReferenceError(f"{name}: complex shape mismatch")
        return array[..., 0] + 1j * array[..., 1]
    if entry["complex"] is not None:
        raise ReferenceError(f"{name}: unknown complex encoding")
    return array


def metadata(spec) -> dict:
    channels = len(spec["tones"]) if spec["tones"] else 1
    ids = ["input.alpha", "input.beta"][:channels]
    return {
        "channel_ids": ids,
        "interval": [0, spec["n"]],
        "timebase": {"clock": "fixture.nominal", "generation": 0, "sample_rate_hz": spec["rate_hz"], "origin_frame": 0},
        "route": {"revision": "identity-v1", "inputs": ids, "outputs": ids},
        "tap": "fixture.input",
        "calibration": {"revision": None, "state": "uncalibrated", "unit": "FS"},
        "validity": {"state": "valid", "invalid_intervals": []},
        "window_symmetry": "symmetric",
        "input_formula": "A*cos(2*pi*k*n/N+phase)" if spec["signal"] == "cosine" else spec["signal"],
        "seed": None,
        "theory_fft_origin": "analytic finite geometric sum; ideal input before f32 quantization",
        "time_quantities_origin": "finite sums over saved input; independent analytic window",
        "current_fft_origin": "FFTManager.rfft/irfft, get_cached_window",
        "normalization_origin": "contract adapter; not a product peak/PSD/RMS function",
    }


def generate(directory: Path, suite: str) -> dict:
    sources = source_hashes()
    if directory.exists():
        raise ReferenceError("Generation requires a new directory; existing expectations are never overwritten")
    directory.mkdir(parents=True)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "contract": CONTRACT,
        "reference_commit": REFERENCE_COMMIT,
        "source_sha256": sources,
        "generator_sha256": generator_hashes(),
        "environment": environment(),
        "tolerances": TOLERANCES,
        "suite": suite,
        "cases": [],
    }
    with reference_backend() as (manager, get_window):
        for spec in oracle.cases(suite):
            x = oracle.make_input(spec)
            expected = oracle.theory(spec, x)
            observed = current(spec, x, manager, get_window)
            summary = evaluate(spec, observed, expected)
            case_dir = directory / spec["id"]
            case_dir.mkdir()
            arrays = {"input": store_array(case_dir, "input", x, "fixed-input")}
            for origin, values in (("theory", expected), ("current", observed)):
                for key, value in values.items():
                    name = f"{origin}.{key}"
                    arrays[name] = store_array(case_dir, name, value, origin)
            manifest["cases"].append(
                dict(
                    spec=spec,
                    metadata=metadata(spec),
                    arrays=arrays,
                    summary=summary,
                    known_differences=legacy_endpoints(spec, x, manager, get_window),
                )
            )
            manager._plans.clear()
            get_window.cache_clear()
            del x, expected, observed, values, value
    assert_headless()
    write_json(directory / "manifest.json", manifest)
    return manifest


def validate_manifest(manifest: dict, *, strict_environment: bool = True) -> None:
    for key, value in {
        "schema_version": SCHEMA_VERSION,
        "contract": CONTRACT,
        "reference_commit": REFERENCE_COMMIT,
        "source_sha256": source_hashes(),
        "generator_sha256": generator_hashes(),
        "tolerances": TOLERANCES,
    }.items():
        if manifest[key] != value:
            raise ReferenceError(f"Manifest {key} mismatch")
    if strict_environment and manifest["environment"] != environment():
        raise ReferenceError("Environment/version mismatch; use --portable for a separately labelled comparison")
    specs = oracle.cases(manifest["suite"])
    if [case["spec"] for case in manifest["cases"]] != specs:
        raise ReferenceError("Fixture case/spec mismatch")
    for case in manifest["cases"]:
        spec = case["spec"]
        if case["metadata"] != metadata(spec):
            raise ReferenceError("Fixture metadata mismatch")
        n = spec["n"]
        channels = len(case["metadata"]["channel_ids"])
        shapes = {
            "window": [n],
            "fft_over_n": [n // 2 + 1, channels, 2],
            "inverse_windowed": [n, channels],
            "frequency_hz": [n // 2 + 1],
            "peak_fs": [n // 2 + 1, channels],
            "psd_fs2_hz": [n // 2 + 1, channels],
            "rms_fs": [channels],
            "integrated_power_fs2": [channels],
            "time_window_power_fs2": [channels],
        }
        required = {"input"} | {f"{origin}.{key}" for origin in ("theory", "current") for key in shapes}
        if set(case["arrays"]) != required:
            raise ReferenceError("Array inventory mismatch")
        for name, entry in case["arrays"].items():
            is_input = name == "input"
            key = name.split(".")[-1]
            shape = [n, channels] if is_input else shapes[key]
            dtype = spec["dtype"] if is_input or name == "current.inverse_windowed" else "<f8"
            encoding = "real-imag-last-axis" if key == "fft_over_n" else None
            origin = "fixed-input" if is_input else name.split(".")[0]
            if (
                entry["shape"] != shape
                or entry["dtype"] != dtype
                or entry["complex"] != encoding
                or entry["origin"] != origin
                or entry["file"] != f"{name}.bin"
            ):
                raise ReferenceError(f"{name}: array schema/shape/dtype mismatch")


def verify(directory: Path, *, portable=False, baseline: Path | None = None) -> dict:
    started = time.perf_counter()
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    validate_manifest(manifest, strict_environment=not portable)
    if baseline is not None:
        saved = json.loads(baseline.read_text(encoding="utf-8"))
        if manifest != saved:
            raise ReferenceError("Materialized manifest differs from the versioned baseline")
    results = []
    with reference_backend() as (manager, get_window):
        for case in manifest["cases"]:
            case_started = time.perf_counter()
            spec = case["spec"]
            case_dir = directory / spec["id"]
            arrays = {key: read_array(case_dir, entry) for key, entry in case["arrays"].items()}
            x = arrays["input"]
            channels = len(case["metadata"]["channel_ids"])
            if x.shape != (spec["n"], channels) or x.dtype.str != spec["dtype"]:
                raise ReferenceError("Input shape/dtype mismatch")
            # Recompute from the saved bytes, never from sin/seed generation.
            expected = oracle.theory(spec, x)
            observed = current(spec, x, manager, get_window)
            wanted_keys = {"input"} | {f"{origin}.{key}" for origin in ("theory", "current") for key in expected}
            if set(arrays) != wanted_keys:
                raise ReferenceError("Array inventory mismatch")
            precision = "f32" if spec["dtype"] == "<f4" else "f64"
            for origin, values in (("theory", expected), ("current", observed)):
                for key, value in values.items():
                    compare(
                        value, arrays[f"{origin}.{key}"], TOLERANCES["window" if key == "window" else precision], key
                    )
            summary = evaluate(spec, observed, expected)
            legacy = legacy_endpoints(spec, x, manager, get_window)
            saved_legacy = case["known_differences"]
            if len(legacy) != len(saved_legacy):
                raise ReferenceError("Known difference inventory mismatch")
            for actual, saved in zip(legacy, saved_legacy, strict=True):
                for key, value in actual.items():
                    if isinstance(value, float):
                        tolerance = TOLERANCES["f64" if key == "theory_linear" else "db_f64"]
                        compare(value, saved[key], tolerance, f"legacy {key}")
                    elif saved[key] != value:
                        raise ReferenceError(f"Legacy {key} mismatch")
            results.append(
                {
                    "id": spec["id"],
                    **summary,
                    "known_differences": legacy,
                    "elapsed_seconds": time.perf_counter() - case_started,
                }
            )
            manager._plans.clear()
            get_window.cache_clear()
            del arrays, x, expected, observed, values, value
    assert_headless()
    return {
        "status": "pass",
        "mode": "portable-numerical-comparison" if portable else "pinned-reference",
        "suite": manifest["suite"],
        "fixture_manifest_sha256": digest((directory / "manifest.json").read_bytes()),
        "reference_commit": REFERENCE_COMMIT,
        "generator_sha256": generator_hashes(),
        "environment": environment(),
        "elapsed_seconds": time.perf_counter() - started,
        "process_peak_rss_bytes": peak_rss_bytes(),
        "cases": results,
        "limitations": ["No candidate implementation, GUI, audio device, performance or 4/8-channel validation"],
    }


def peak_rss_bytes() -> int | None:
    # Process high-water mark, not a per-transform or steady-state benchmark.
    if sys.platform not in ("darwin", "linux"):
        return None
    import resource

    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * (1 if sys.platform == "darwin" else 1024)


def assert_headless() -> None:
    forbidden = ("PyQt6", "PySide6", "pyqtgraph", "sounddevice", "src.core.audio_engine", "src.gui")
    loaded = [
        name for name in sys.modules if any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden)
    ]
    if loaded:
        raise ReferenceError(f"GUI/device modules imported: {loaded}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("generate", help="Explicitly create a new corpus")
    create.add_argument("--output", type=Path, required=True)
    create.add_argument("--suite", choices=("small", "extended"), default="small")
    check = commands.add_parser("verify", help="Read-only verification using saved input bytes")
    check.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    check.add_argument(
        "--portable", action="store_true", help="Allow a different environment, recording it in the result"
    )
    check.add_argument("--baseline", type=Path, help="Require exact agreement with a separately versioned manifest")
    check.add_argument("--report", type=Path, help="Write a new run report outside the fixture directory")
    args = parser.parse_args()
    try:
        if args.command == "generate":
            manifest = generate(args.output, args.suite)
            print(f"Generated {len(manifest['cases'])} cases: {args.output / 'manifest.json'}")
        else:
            if args.report and (args.report.exists() or args.report.resolve().is_relative_to(args.fixtures.resolve())):
                raise ReferenceError("Report must be a new file outside the fixture directory")
            report = verify(args.fixtures, portable=args.portable, baseline=args.baseline)
            if args.report:
                write_json(args.report, report)
            print(f"FFT reference OK: {len(report['cases'])} cases ({report['mode']}); no GUI/device imports")
    except (ReferenceError, OSError, KeyError, TypeError, ValueError) as exc:
        print(f"FFT reference failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
