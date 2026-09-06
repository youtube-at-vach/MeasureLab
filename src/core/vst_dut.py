"""Isolated VST3 effect host for the virtual audio device.

The child main thread owns native windows and plugin resets; a separate thread
serves audio requests. Normal audio needs no optional VST dependency.
"""

import atexit
import multiprocessing
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess
from multiprocessing.synchronize import Event
from pathlib import Path
from queue import Queue
import threading
from typing import Any, Iterable

import numpy as np
from numpy.typing import NDArray


class _EditorInterrupt:
    """Let main-thread jobs briefly suspend a window without ending its session."""

    def __init__(self, close_event: Event, jobs: Queue[tuple[str, Any]]):
        self.close_event, self.jobs = close_event, jobs
        self.interrupted = False

    def is_set(self) -> bool:
        if self.close_event.is_set():
            return True
        if not self.jobs.empty():
            self.interrupted = True
            return True
        return False


def _plugin_worker(
    connection: Connection, path: str, plugin_name: str | None, close_editor: Event, editor_events: Connection
) -> None:
    jobs: Queue[tuple[str, Any]] = Queue()
    receiver = None
    try:
        from pedalboard import VST3Plugin

        plugin: Any = VST3Plugin(path, plugin_name=plugin_name)
        if not plugin.is_effect:
            raise ValueError("The DUT must accept audio input (VST3 effect).")

        def values() -> dict[str, float]:
            return {name: float(param.raw_value) for name, param in plugin.parameters.items()}

        def reset_on_main() -> None:
            # Some plugins are reinstantiated by Pedalboard.reset(). Their
            # editor must be released first, and reinstantiation requires main.
            finished = threading.Event()
            errors: list[Exception] = []
            jobs.put(("reset", (finished, errors)))
            finished.wait()
            if errors:
                raise errors[0]

        def receive() -> None:
            current_format = None
            result: Any
            try:
                while True:
                    command, payload = connection.recv()
                    if command == "close":
                        return
                    if command == "editor":
                        jobs.put(("editor", None))
                        result = None
                    elif command == "reset":
                        reset_on_main()
                        current_format = None
                        result = None
                    elif command == "parameter":
                        name, value = payload
                        plugin.parameters[name].raw_value = value
                        result = values()
                    elif command == "process":
                        audio, rate, block_size = payload
                        audio_format = (rate, block_size, audio.shape[0])
                        if audio_format != current_format:
                            reset_on_main()
                            current_format = audio_format
                        result = plugin.process(audio, rate, buffer_size=block_size, reset=False)
                    else:
                        raise ValueError("Unknown VST host command")
                    connection.send((True, result))
            except EOFError:
                pass  # Parent closed the host.
            except Exception as exc:
                try:
                    connection.send((False, f"{type(exc).__name__}: {exc}"))
                except (BrokenPipeError, EOFError, OSError):
                    pass  # Parent may already have timed out.
            finally:
                jobs.put(("close", None))

        connection.send((True, {"name": plugin.name, "parameters": values()}))
        receiver = threading.Thread(target=receive, name="VST audio", daemon=True)
        receiver.start()
        editor_requested = False
        interrupt = _EditorInterrupt(close_editor, jobs)
        while True:
            if editor_requested and jobs.empty():
                interrupt.interrupted = False
                editor_error = ""
                try:
                    plugin.show_editor(interrupt)
                except Exception as exc:
                    editor_error = f"{type(exc).__name__}: {exc}"
                if editor_error or not interrupt.interrupted:
                    editor_requested = False
                    # Completion never shares the audio reply channel. It may
                    # arrive at any time, including during a measurement block.
                    editor_events.send((True, {"parameters": values(), "error": editor_error}))
                continue
            command, payload = jobs.get()
            if command == "close":
                break
            if command == "editor":
                editor_requested = True
            elif command == "reset":
                finished, errors = payload
                try:
                    plugin.reset()
                except Exception as exc:
                    errors.append(exc)
                finally:
                    finished.set()
    except Exception as exc:
        try:
            target = connection if receiver is None else editor_events
            target.send((False, f"{type(exc).__name__}: {exc}"))
        except (BrokenPipeError, EOFError, OSError):
            pass  # Parent disconnected.
    finally:
        connection.close()
        editor_events.close()
        if receiver is not None:
            receiver.join(timeout=0.2)


class VstDut:
    """Serialize control/audio requests and latch failures to silence.

    Input routes are logical generator channel indices (0/1), or -1 for silence.
    Return routes are wet1/wet2, dry1/dry2, or silence. Mono generator output is
    duplicated to both logical source channels, matching virtual loopback.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._connection: Connection | None = None
        self._process: BaseProcess | None = None
        self._editor_connection: Connection | None = None
        self._editor_close: Event | None = None
        self.editor_open = False
        self.editor_error = ""
        self.path = ""
        self.name = ""
        self.parameters: dict[str, float] = {}
        self.error = ""
        self.bypassed = False
        self.input_routes: tuple[int, ...] = (0, 1)
        self.return_routes: tuple[str, ...] = ("wet1", "wet2")
        self.padded_samples = 0
        self._format: tuple[float, int, int] | None = None
        atexit.register(self.close)

    @property
    def loaded(self) -> bool:
        # A failed DUT stays selected: never silently substitute an ideal wire.
        return bool(self.path)

    def load(self, path: str, plugin_name: str | None = None) -> None:
        path = str(Path(path).expanduser().resolve())
        if Path(path).suffix.lower() != ".vst3" or not Path(path).exists():
            raise ValueError("Select an existing .vst3 file or bundle.")
        # Build the replacement first so a failed load preserves the current DUT.
        context = multiprocessing.get_context("spawn")
        parent, child = context.Pipe()
        editor_parent, editor_child = context.Pipe(duplex=False)
        editor_close = context.Event()
        process = context.Process(
            target=_plugin_worker, args=(child, path, plugin_name, editor_close, editor_child), daemon=True
        )
        try:
            process.start()
            child.close()
            editor_child.close()
            if not parent.poll(30.0):
                raise TimeoutError("VST3 load timed out (30 s).")
            success, info = parent.recv()
            if not success:
                raise RuntimeError(info)
        except Exception as exc:
            parent.close()
            child.close()
            editor_parent.close()
            editor_child.close()
            if process.pid is not None:
                self._terminate(process)
            if isinstance(exc, EOFError):
                raise RuntimeError(
                    "VST3 host exited while loading. Check plugin compatibility and architecture."
                ) from exc
            raise
        with self._lock:
            self._close_locked()
            self._connection, self._process = parent, process
            self._editor_close = editor_close
            self._editor_connection = editor_parent
            self.path, self.name = path, info["name"]
            self.parameters = info["parameters"]
            self.error = ""
            self.bypassed = False
            self._format = None
            self.padded_samples = 0

    @staticmethod
    def _terminate(process: BaseProcess) -> None:
        if process.is_alive():
            process.terminate()
        process.join(timeout=0.2)
        if process.is_alive():
            process.kill()
            process.join(timeout=0.2)
        if not process.is_alive():
            process.close()

    def _close_locked(self) -> None:
        if self._editor_close is not None:
            self._editor_close.set()
            self._editor_close = None
        self.editor_open = False
        self.editor_error = ""
        if self._editor_connection is not None:
            self._editor_connection.close()
            self._editor_connection = None
        if self._connection is not None:
            self._connection.close()
            self._connection = None
        if self._process is not None:
            self._terminate(self._process)
            self._process = None

    def close(self) -> None:
        with self._lock:
            self._close_locked()
            self.path = self.name = self.error = ""
            self.parameters = {}
            self._format = None
            self.padded_samples = 0

    def _request(self, command: str, payload: Any = None, timeout: float = 1.0) -> Any:
        self.poll_editor()
        if self.error:
            raise RuntimeError(self.error)
        if self._connection is None:
            raise RuntimeError("No VST3 plugin loaded.")
        try:
            self._connection.send((command, payload))
            if not self._connection.poll(timeout):
                raise TimeoutError("VST3 host stopped responding.")
            success, result = self._connection.recv()
            if not success:
                raise RuntimeError(result)
            return result
        except (OSError, EOFError, RuntimeError, TimeoutError) as exc:
            self.error = str(exc) or "VST3 host disconnected."
            self._close_locked()
            raise RuntimeError(self.error) from exc

    def open_editor(self) -> None:
        """Open the loaded instance's native window without blocking the caller."""
        with self._lock:
            self.poll_editor()
            if self.editor_open:
                return
            if self._editor_close is None:
                raise RuntimeError("No VST3 plugin loaded.")
            self._editor_close.clear()
            self.editor_error = ""
            self._request("editor")
            self.editor_open = True

    def poll_editor(self) -> bool:
        """Collect edited values on window close; return whether it completed."""
        with self._lock:
            return self._finish_editor(timeout=0)

    def close_editor(self) -> None:
        with self._lock:
            if self.editor_open and self._editor_close is not None:
                self._editor_close.set()
                self._finish_editor(timeout=5.0)

    def _finish_editor(self, timeout: float) -> bool:
        if not self.editor_open or self._editor_connection is None:
            return False
        try:
            if not self._editor_connection.poll(timeout):
                if timeout == 0:
                    return False
                raise TimeoutError("VST3 editor stopped responding while closing.")
            success, result = self._editor_connection.recv()
            if not success:
                raise RuntimeError(result)
            self.editor_open = False
            self.parameters = result["parameters"]
            self.editor_error = result["error"]
            return True
        except (OSError, EOFError, RuntimeError, TimeoutError) as exc:
            self.error = str(exc) or "VST3 host disconnected."
            self._close_locked()
            raise RuntimeError(self.error) from exc

    def reset(self) -> None:
        with self._lock:
            self._format = None
            self.padded_samples = 0
            if self.loaded and not self.error:
                self._request("reset")

    def set_bypassed(self, bypassed: bool) -> None:
        with self._lock:
            self.reset()
            self.bypassed = bool(bypassed)

    def set_routes(self, inputs: Iterable[int], returns: Iterable[str]) -> None:
        input_routes, return_routes = tuple(inputs), tuple(returns)
        if len(input_routes) not in (1, 2) or any(route not in (-1, 0, 1) for route in input_routes):
            raise ValueError("DUT input routing must have one or two channels.")
        allowed = {"wet1", "dry1", "dry2", "silence"}
        if len(input_routes) == 2:
            allowed.add("wet2")
        if len(return_routes) != 2 or any(route not in allowed for route in return_routes):
            raise ValueError("Invalid DUT return routing.")
        with self._lock:
            self.reset()
            self.input_routes, self.return_routes = input_routes, return_routes

    def set_parameter(self, name: str, value: float) -> None:
        if not np.isfinite(value) or not 0 <= value <= 1:
            raise ValueError("Normalized parameter value must be between 0 and 1.")
        with self._lock:
            if name not in self.parameters:
                raise ValueError("Unknown plugin parameter.")
            self.parameters = self._request("parameter", (name, value))

    def process(self, source: np.ndarray, sample_rate: float, block_size: int) -> NDArray[np.float32]:
        """Return two measurement channels; preserve streaming state and tails."""
        frames = len(source)
        silence = np.zeros((frames, 2), dtype=np.float32)
        with self._lock:
            if self.error:
                return silence
            dry = np.asarray(source, dtype=np.float32)
            if dry.shape[1] == 1:
                dry = np.repeat(dry, 2, axis=1)
            audio = np.zeros((len(self.input_routes), frames), dtype=np.float32)
            for channel, route in enumerate(self.input_routes):
                if route >= 0:
                    audio[channel] = dry[:, route]
            try:
                self.poll_editor()
                audio_format = (sample_rate, block_size, len(self.input_routes))
                if audio_format != self._format:
                    self.padded_samples = 0
                    self._format = audio_format
                wet: NDArray[np.float32]
                if self.bypassed:
                    wet = audio
                else:
                    wet = np.asarray(self._request("process", (audio, sample_rate, block_size)))
                if wet.ndim != 2 or wet.shape[0] != len(self.input_routes) or wet.shape[1] > frames:
                    raise ValueError("VST3 returned an unsupported channel/frame layout.")
                if not np.all(np.isfinite(wet)):
                    raise ValueError("VST3 returned non-finite samples.")
                # Pedalboard can retain startup samples for plugin latency. Pad
                # BEFORE returned samples, never reset/flush between blocks.
                missing = frames - wet.shape[1]
                self.padded_samples += missing
                if missing:
                    wet = np.pad(wet, ((0, 0), (missing, 0)))
                sources = {"wet1": wet[0], "dry1": dry[:, 0], "dry2": dry[:, 1], "silence": 0}
                if len(wet) > 1:
                    sources["wet2"] = wet[1]
                for channel, return_route in enumerate(self.return_routes):
                    silence[:, channel] = sources[return_route]
                return silence
            except Exception as exc:
                self.error = str(exc)
                self._close_locked()
                return np.zeros_like(silence)
