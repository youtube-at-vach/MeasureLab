"""Generate/verify MIG-003-C FIR, polyphase and representative SOS references.

Generation requires a new directory. Verification only consumes saved bytes.
Product functions run source-pinned without a GUI or audio device. FIR streaming
is a new-contract oracle, not an implementation of the existing AudioEngine.
"""

from __future__ import annotations

import argparse
from fractions import Fraction
import math
from pathlib import Path
import sys
import time

import numpy as np
from scipy import signal

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import migration_core_reference as exchange  # noqa: E402
from scripts import migration_fft_reference as fft  # noqa: E402
from scripts import migration_filter_cases as cases  # noqa: E402
from scripts import migration_filter_oracle as oracle  # noqa: E402

DEFAULT_FIXTURES = ROOT / "migration/fixtures/filter-v1"
GENERATOR_PATHS = (
    "scripts/migration_filter_reference.py",
    "scripts/migration_filter_oracle.py",
    "scripts/migration_filter_cases.py",
    *exchange.GENERATOR_PATHS,
)
TOLERANCES = {
    "fir": {"atol": 1e-12, "rtol": 1e-12},
    "poly": {"atol": 1e-10, "rtol": 1e-8},
    "sos": {"atol": 1e-10, "rtol": 1e-8},
}
FREQUENCIES = np.array([0, 1000, 4000, 12000, 20000], dtype="<f8")


def environment():
    result = fft.environment()
    result["fft"] = {"backend": "numpy", "use": "polyphase output peak-frequency diagnostic only"}
    return result


def header():
    return {
        "schema_version": 1,
        "contract": "MIG-002-numerics-v0.1",
        "reference_commit": fft.REFERENCE_COMMIT,
        "source_sha256": fft.source_hashes(),
        "generator_sha256": exchange.hashes(GENERATOR_PATHS),
        "contract_sha256": exchange.hashes(exchange.CONTRACT_PATHS),
        "environment": environment(),
        "tolerances": TOLERANCES,
        "rate_cases": cases.RATE_CASES,
        "limitations": [
            "FIR streaming and validity are new-contract oracles; no candidate core or shared graph",
            "Legacy AudioCalc.resample and lowpass_filter operate on complete arrays, not streams",
            "Causal SOS uses scipy.signal.sosfilt with product coefficients, not a legacy streaming API",
            "No IIR gap recovery contract, other filters/rates, physical I/O, GUI or other OS validation",
            "Timing and RSS cover verification, not a protocol-compliant performance benchmark",
        ],
    }


def ratio(spec):
    divisor = math.gcd(spec["source_rate"], spec["target_rate"])
    return spec["target_rate"] // divisor, spec["source_rate"] // divisor


def metadata(spec):
    up, down = ratio(spec)
    n_out = (spec["n"] * up + down - 1) // down
    common = {
        "channel_ids": cases.CHANNEL_IDS,
        "dtype": "<f8",
        "layout": "C/frame-major",
        "input_shape": [spec["n"], 2],
        "output_shape": [n_out, 2],
        "unit": "FS",
        "route_revision": "identity-v1",
        "tap": "fixture.input",
        "calibration": {"revision": None, "state": "uncalibrated"},
        "input_formula": spec["signal"],
        "input_parameters": {
            "amplitudes": [0.25, 0.125],
            "phases_rad": [0, 0.375],
            "tone_hz": [1000, 12000] if spec["kind"] == "sos" else [1000, 1000],
            "impulse_amplitudes": [1, -0.5],
            "dc_levels": [0.25, -0.125],
        },
        "seed": None,
        "source_rate_hz": spec["source_rate"],
        "output_rate_hz": spec["target_rate"],
        "generation": 0,
        "input_interval": [0, spec["n"]],
        "output_interval": [0, n_out],
    }
    if spec["kind"] == "fir":
        return {
            **common,
            **oracle.fir_metadata(spec["n"], spec["gaps"]),
            "acceptance": ["AC10"],
            "origin": "independent finite sum vs new-contract state model",
            "chunks": oracle.CHUNKS,
        }
    if spec["kind"] == "poly":
        half = 10 * max(up, down)
        pre_pad = down - half % down
        return {
            **common,
            "acceptance": ["AC14"],
            "origin": "AudioCalc.resample vs centered finite sum",
            "coefficient_origin": "_get_resample_filter vs normalized sinc/Kaiser formula",
            "up": up,
            "down": down,
            "kaiser_beta": 5.0,
            "half_len": half,
            "coefficient_scale": up,
            "padtype": "constant",
            "cval": 0,
            "coefficient_pre_pad": pre_pad,
            "pre_remove_outputs": (half + pre_pad) // down,
            "signal_delay_before_compensation_output": oracle.fraction(Fraction(half, down)),
            "delay_compensated": True,
            "axis": 0,
            "validity": "legacy API provides no validity metadata; endpoint zero padding is explicit",
            "initial_state": "independent whole-array call",
        }
    return {
        **common,
        "acceptance": ["AC14"],
        "origin": "AudioCalc.lowpass_filter vs scalar direct-form-I forward/backward recurrence",
        "coefficient_origin": "_get_butter_sos(8, 4000/24000, lowpass)",
        "causal_origin": "scipy.signal.sosfilt with product SOS; scalar direct-form-I oracle",
        "causal_initial_state": "all zero",
        "offline_initial_state": "steady DC state scaled by each extended endpoint",
        "padtype": "odd",
        "padlen": 27,
        "axis_adapter": "call product separately for each named channel",
        "causal_warmup": "zero state transient retained; no arbitrary valid-after cutoff",
        "offline_phase": "zero phase; magnitude is squared causal magnitude",
        "chunks": oracle.CHUNKS,
    }


def current_rates(audio_calc):
    x = np.array([[1.0, -0.5], [0.25, 0.125]])
    rows = []
    for case in cases.RATE_CASES:
        rates = case["rates"]
        actual = audio_calc.resample(x, *rates)
        if actual is not x or not np.array_equal(actual, x):
            raise fft.ReferenceError("Legacy invalid/identity rate behavior changed")
        try:
            oracle.valid_rates(*rates)
            contract = "valid_rate_pair"
        except ValueError as error:
            contract = str(error)
        row = {"rates": rates, "legacy": "same_object", "contract": contract}
        if row != case:
            raise fft.ReferenceError("New-contract rate rejection mismatch")
        rows.append(row)
    return rows


def evaluate(spec, x, analysis):
    tolerance = TOLERANCES[spec["kind"]]
    errors, diagnostics = {}, {}

    def compare(a, b, label):
        errors[label] = fft.compare(a, b, tolerance, label)

    if spec["kind"] == "fir":
        theory = oracle.fir_sum(x, spec["gaps"])
        for name, pattern in oracle.CHUNKS.items():
            output, reasons = oracle.stream_fir(x, spec["gaps"], pattern)
            compare(output, theory, f"chunk-{name}")
            if reasons != oracle.fir_metadata(len(x), spec["gaps"])["invalid_intervals"]:
                raise fft.ReferenceError("FIR gap/warmup mismatch")
        # Exact trigger/rate mapping is not inferred from a waveform peak.
        mapping = oracle.map_position(1024, spec["source_rate"], spec["target_rate"])
        delay = oracle.map_position(1, spec["source_rate"], spec["target_rate"])
        if (oracle.fraction(mapping), oracle.fraction(delay), oracle.fraction(mapping + delay)) != (
            [512, 1],
            [1, 2],
            [1025, 2],
        ):
            raise fft.ReferenceError("Trigger/delay mapping mismatch")
        return {"coefficients": oracle.FIR, "theory.output": theory, "model.output": output}, errors, diagnostics

    if spec["kind"] == "poly":
        up, down = ratio(spec)
        coefficients = analysis._get_resample_filter(up, down).copy()
        theoretical_coefficients = oracle.kaiser_coefficients(up, down)
        compare(coefficients, theoretical_coefficients, "coefficients")
        output = analysis.AudioCalc.resample(x, spec["source_rate"], spec["target_rate"])
        theory = oracle.polyphase_sum(x, coefficients, up, down)
        compare(output, theory, "finite-sum")
        chunks = [
            analysis.AudioCalc.resample(x[left:right], spec["source_rate"], spec["target_rate"])
            for left, right in oracle.slices(len(x), [127])
        ]
        restarted = np.concatenate(chunks)
        shared_length = min(len(output), len(restarted))
        diagnostics["legacy_restarted_chunks"] = {
            "chunk_size": 127,
            "whole_frames": len(output),
            "restarted_frames": len(restarted),
            "max_abs_difference_prefix": float(np.max(np.abs(output[:shared_length] - restarted[:shared_length]))),
            "meaning": "independent calls reset endpoint/phase; not streaming equivalence",
        }
        if spec["signal"] == "tone":
            rms = np.sqrt(np.mean(output**2, axis=0))
            expected_rms = np.array([0.25, 0.125]) / np.sqrt(2)
            fft.compare(rms, expected_rms, {"atol": 0.01, "rtol": 0}, "passband RMS")
            frequencies = np.fft.rfftfreq(len(output), 1 / spec["target_rate"])
            peak = frequencies[
                np.argmax(np.abs(np.fft.rfft(output * np.hanning(len(output))[:, None], axis=0)), axis=0)
            ]
            fft.compare(peak, np.full(2, 1000), {"atol": 1, "rtol": 0}, "passband peak frequency")
            diagnostics["passband"] = {
                "rms_error_fs": (rms - expected_rms).tolist(),
                "peak_frequency_hz": peak.tolist(),
            }
        return (
            {
                "coefficients": coefficients,
                "theory.coefficients": theoretical_coefficients,
                "current.output": output,
                "theory.output": theory,
            },
            errors,
            diagnostics,
        )

    sos = analysis._get_butter_sos(spec["order"], spec["cutoff_hz"] / (spec["source_rate"] / 2), "lowpass").copy()
    zero_state = np.zeros((len(sos), 2, x.shape[1]))
    causal, final_state = signal.sosfilt(sos, x, axis=0, zi=zero_state)
    theoretical_causal, theoretical_final_state = oracle.sos_recurrence(x, sos)
    compare(causal, theoretical_causal, "causal-recurrence")
    compare(final_state, theoretical_final_state, "final-state")
    for name, pattern in oracle.CHUNKS.items():
        state = zero_state.copy()
        chunks = []
        for left, right in oracle.slices(len(x), pattern):
            out, state = signal.sosfilt(sos, x[left:right], axis=0, zi=state)
            chunks.append(out)
        compare(np.concatenate(chunks), causal, f"causal-chunk-{name}")
        compare(state, final_state, f"state-chunk-{name}")
    offline = np.column_stack(
        [analysis.AudioCalc.lowpass_filter(channel, spec["source_rate"], cutoff=spec["cutoff_hz"]) for channel in x.T]
    )
    theoretical_offline = oracle.sos_forward_backward(x, sos)
    compare(offline, theoretical_offline, "forward-backward-recurrence")
    restarted = np.concatenate(
        [
            np.column_stack(
                [
                    analysis.AudioCalc.lowpass_filter(channel, spec["source_rate"], cutoff=spec["cutoff_hz"])
                    for channel in x[left:right].T
                ]
            )
            for left, right in oracle.slices(len(x), [256])
        ]
    )
    diagnostics["legacy_restarted_chunks"] = {
        "chunk_size": 256,
        "max_abs_difference": float(np.max(np.abs(offline - restarted))),
        "meaning": "offline forward/backward calls re-pad endpoints; not streaming equivalence",
    }
    _, response = signal.freqz_sos(sos, worN=FREQUENCIES, fs=spec["source_rate"])
    theoretical_response = oracle.sos_response(sos, FREQUENCIES, spec["source_rate"])
    compare(response, theoretical_response, "complex-response")
    expected_magnitude = 1 / np.sqrt(
        1
        + (np.tan(np.pi * FREQUENCIES / spec["source_rate"]) / np.tan(np.pi * spec["cutoff_hz"] / spec["source_rate"]))
        ** (2 * spec["order"])
    )
    compare(np.abs(response), expected_magnitude, "butterworth-magnitude")
    compare(np.angle(response * np.conj(theoretical_response)), np.zeros(len(response)), "phase-radians")
    if spec["signal"] == "tone":
        # End transients excluded explicitly; compare actual amplitude AND phase.
        n = np.arange(len(x))
        causal_expected, offline_expected = np.zeros_like(x), np.zeros_like(x)
        for channel, (frequency, amplitude, phase) in enumerate(((1000, 0.25, 0), (12000, 0.125, 0.375))):
            transfer = oracle.sos_response(sos, [frequency], spec["source_rate"])[0]
            carrier = amplitude * np.exp(1j * (2 * np.pi * frequency * n / spec["source_rate"] + phase))
            causal_expected[:, channel] = (transfer * carrier).real
            offline_expected[:, channel] = abs(transfer) ** 2 * carrier.real
        compare(causal[1024:-1024], causal_expected[1024:-1024], "steady-causal-tone")
        compare(offline[1024:-1024], offline_expected[1024:-1024], "steady-zero-phase-tone")
    return (
        {
            "coefficients": sos,
            "initial.state": zero_state,
            "current.causal": causal,
            "theory.causal": theoretical_causal,
            "current.final_state": final_state,
            "theory.final_state": theoretical_final_state,
            "current.output": offline,
            "theory.output": theoretical_offline,
            "frequency_hz": FREQUENCIES,
            "current.response": response,
            "theory.response": theoretical_response,
            "theory.magnitude": expected_magnitude,
        },
        errors,
        diagnostics,
    )


def array_schema(spec):
    up, down = ratio(spec)
    shape = [(spec["n"] * up + down - 1) // down, 2]
    result = {"input": ([spec["n"], 2], "fixed-input", False)}
    if spec["kind"] == "fir":
        result.update(
            {
                "coefficients": ([3], "contract", False),
                "theory.output": (shape, "theory", False),
                "model.output": (shape, "model", False),
            }
        )
    elif spec["kind"] == "poly":
        result.update(
            {
                "coefficients": ([20 * max(up, down) + 1], "current", False),
                "theory.coefficients": ([20 * max(up, down) + 1], "theory", False),
                "theory.output": (shape, "theory", False),
                "current.output": (shape, "current", False),
            }
        )
    else:
        result.update(
            {
                "coefficients": ([4, 6], "current", False),
                "initial.state": ([4, 2, 2], "contract", False),
                "frequency_hz": ([5], "contract", False),
                "theory.magnitude": ([5], "theory", False),
            }
        )
        for origin in ("current", "theory"):
            result.update(
                {
                    f"{origin}.{key}": (dimensions, origin, key == "response")
                    for key, dimensions in (
                        ("causal", shape),
                        ("output", shape),
                        ("final_state", [4, 2, 2]),
                        ("response", [5, 2]),
                    )
                }
            )
    return result


def generate(directory):
    manifest = header()
    if directory.exists():
        raise fft.ReferenceError("Generation requires a new directory; expectations are never overwritten")
    directory.mkdir(parents=True)
    manifest["cases"] = []
    with fft.reference_backend():
        from src.core import analysis

        current_rates(analysis.AudioCalc)
        for spec in cases.specs():
            x = cases.make_input(spec)
            arrays, _, _ = evaluate(spec, x, analysis)
            folder = directory / spec["id"]
            folder.mkdir()
            schema = array_schema(spec)
            entries = {
                name: fft.store_array(folder, name, array, schema[name][1])
                for name, array in {"input": x, **arrays}.items()
            }
            manifest["cases"].append({"spec": spec, "metadata": metadata(spec), "arrays": entries})
    fft.assert_headless()
    fft.write_json(directory / "manifest.json", manifest)
    return manifest


def validate_manifest(manifest, portable=False):
    expected = header()
    if set(manifest) != set(expected) | {"cases"}:
        raise fft.ReferenceError("Manifest keys mismatch")
    for key, value in expected.items():
        if key == "environment" and portable:
            continue
        if exchange.json_bytes(manifest[key]) != exchange.json_bytes(value):
            raise fft.ReferenceError(f"Manifest {key} mismatch")
    if exchange.json_bytes([case["spec"] for case in manifest["cases"]]) != exchange.json_bytes(cases.specs()):
        raise fft.ReferenceError("Case inventory/spec mismatch")
    for case in manifest["cases"]:
        if set(case) != {"spec", "metadata", "arrays"} or exchange.json_bytes(case["metadata"]) != exchange.json_bytes(
            metadata(case["spec"])
        ):
            raise fft.ReferenceError("Case metadata mismatch")


def load_case(directory, case):
    schema = array_schema(case["spec"])
    if set(case["arrays"]) != set(schema):
        raise fft.ReferenceError("Array inventory mismatch")
    result = {}
    for name, (shape, origin, complex_value) in schema.items():
        entry = case["arrays"][name]
        expected = {
            "file": f"{name}.bin",
            "shape": shape,
            "origin": origin,
            "dtype": "<f8",
            "byte_order": "little",
            "layout": "C/frame-major",
            "complex": "real-imag-last-axis" if complex_value else None,
        }
        if set(entry) != set(expected) | {"sha256"} or any(
            exchange.json_bytes(entry[key]) != exchange.json_bytes(value) for key, value in expected.items()
        ):
            raise fft.ReferenceError(f"{name}: array schema mismatch")
        result[name] = fft.read_array(directory / case["spec"]["id"], entry)
    return result


def verify(directory, portable=False, baseline=None):
    started = time.perf_counter()
    manifest = exchange.read_json((directory / "manifest.json").read_bytes())
    validate_manifest(manifest, portable)
    if baseline and exchange.json_bytes(manifest) != exchange.json_bytes(exchange.read_json(baseline.read_bytes())):
        raise fft.ReferenceError("Manifest differs from saved baseline")
    results = []
    with fft.reference_backend():
        from src.core import analysis

        rates = current_rates(analysis.AudioCalc)
        for case in manifest["cases"]:
            spec = case["spec"]
            saved = load_case(directory, case)
            arrays, errors, diagnostics = evaluate(spec, saved["input"], analysis)
            for key, value in arrays.items():
                errors[f"saved.{key}"] = fft.compare(value, saved[key], TOLERANCES[spec["kind"]], key)
            results.append(
                {
                    "id": spec["id"],
                    "acceptance": metadata(spec)["acceptance"],
                    "status": "pass",
                    "max_absolute_errors": errors,
                    "diagnostics": diagnostics,
                }
            )
    fft.assert_headless()
    return {
        "status": "pass",
        "mode": "portable-comparison" if portable else "pinned-reference",
        "manifest_sha256": fft.digest((directory / "manifest.json").read_bytes()),
        "environment": environment(),
        "generator_sha256": exchange.hashes(GENERATOR_PATHS),
        "elapsed_seconds": time.perf_counter() - started,
        "process_peak_rss_bytes": fft.peak_rss_bytes(),
        "cases": results,
        "rate_cases": rates,
        "limitations": manifest["limitations"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("generate")
    create.add_argument("--output", type=Path, required=True)
    check = commands.add_parser("verify")
    check.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    check.add_argument("--portable", action="store_true")
    check.add_argument("--baseline", type=Path)
    check.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "generate":
            generate(args.output)
            print(f"Generated filter fixture: {args.output}")
        else:
            if args.report and (args.report.exists() or args.report.resolve().is_relative_to(args.fixtures.resolve())):
                raise fft.ReferenceError("Report must be a new file outside the fixture directory")
            report = verify(args.fixtures, args.portable, args.baseline)
            if args.report:
                fft.write_json(args.report, report)
            print(
                f"Filter reference OK: {len(report['cases'])} cases, {len(report['rate_cases'])} rate cases ({report['mode']}); no GUI/device imports"
            )
    except (ValueError, KeyError, TypeError, OSError) as error:
        print(f"Filter reference failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
