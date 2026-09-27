# GUI robustness layer

Run from the repository root:

```bash
./.venv/bin/pytest -q tests/gui
MEASURELAB_GUI_FUZZ_SEED=24681357 ./.venv/bin/pytest -q tests/gui/test_widget_interactions.py
```

The tests instantiate widgets through the runtime module registry and use Qt control APIs. `FuzzAudioEngine` executes the production `AudioEngine._master_callback` and registered module callbacks with synthetic stereo blocks. It never opens a sound device. The fixture blocks PortAudio access and process launch; Remote Audio discovery and Welcome update checks are replaced for shell page smoke tests.

The suite has three layers: smoke for every registered module and shell page, a seeded stateful control walk for measurement pages, and Hypothesis state machines for Spectrum Analyzer and Oscilloscope. The explorer chooses from currently visible, enabled controls. It only clicks the declared primary Start/Stop button or benign Reset/Clear buttons. File dialogs, network connection, benchmark execution, VST scanning, real recording, and destructive actions need separate integration tests.

Every scenario writes its current operation trace to `artifacts/gui_fuzz/<widget>_<seed>/trace.json`, including the state before the next operation. Failures also write `failure.json` with traceback, Qt messages, Python stdout/stderr, logs, seed, current state, and `last.png` when grabbing the widget succeeds. Hypothesis prints a reproduction blob for failures and runs with deterministic examples. The default artifact directory is ignored by Git and retained locally for replay; copy a specific report to a deliberate tracked location if it needs to be shared. Set `MEASURELAB_GUI_FUZZ_ARTIFACTS` to change the artifact directory. A custom path inside the repository is not automatically ignored.

Replaying a scenario clears its previous `failure.json` and `last.png` before writing a new trace, so those files describe only the current run.

The only allowed Qt warnings are the known Qt offscreen plugin capability messages and its one-time font fallback notice. Other Qt warnings and all critical messages fail the scenario. LUFS histogram curves intentionally use N+1 bin edges for N heights; LUFS history and event curves use `connect="finite"` with NaN gaps. All other plotted values must be finite.
