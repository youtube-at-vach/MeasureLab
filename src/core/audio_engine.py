import logging
import threading

import numpy as np
import sounddevice as sd

from src.core.calibration import CalibrationManager


import time

class VirtualStream:
    """
    Simulates a sounddevice.Stream for offline/virtual mode.
    Driven by a timer to approximate real-time processing.
    """

    def __init__(self, samplerate, blocksize, channels, callback):
        self.samplerate = samplerate
        self.blocksize = blocksize
        if isinstance(channels, int):
            self.channels = (channels, channels)
        else:
            self.channels = channels  # (in, out)
        self.callback = callback
        self.active = False
        self.cpu_load = 0.0
        self._stop_event = threading.Event()
        self._thread = None

    def start(self):
        if self.active:
            return
        self.active = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self):
        if not self.active:
            return
        self.active = False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None

    def close(self):
        self.stop()

    def _run_loop(self):
        interval = self.blocksize / self.samplerate
        # Pre-allocate buffers
        indata = np.zeros((self.blocksize, self.channels[0]), dtype="float32")
        outdata = np.zeros((self.blocksize, self.channels[1]), dtype="float32")

        next_call_time = time.time()

        while self.active and not self._stop_event.is_set():
            t = time.time()
            # Drift correction: if we are falling behind, catch up just a bit, but don't spiral
            if t > next_call_time + 0.1:
                next_call_time = t

            # Sleep until next Tick
            to_sleep = next_call_time - t
            if to_sleep > 0:
                time.sleep(to_sleep)

            next_call_time += interval

            # Call callback
            try:
                # status=0 for all good
                getattr(sd, "CallbackTime", lambda: 0)()  # Dummy or approximation
                # We need a proper CData struct for time if we strictly follow sd type, 
                # but usually python callbacks just access attributes. 
                # Let's mock a simple object if needed, or just pass an object.
                # sd.Stream callback signature: (indata, outdata, frames, time, status)
                # time is CData {inputBufferAdcTime, outputBufferDacTime, ...}
                # For virtual, we can pass a dummy object or None if the app handles it safely.
                # AudioEngine uses `time`? Checking... `cb(logical_in, client_out, frames, time, status)`
                # The callback in AudioEngine is `master_callback`. It passes `time` through to clients.
                # Let's pass a dummy object.

                class DummyTime:
                    inputBufferAdcTime = t
                    outputBufferDacTime = t + interval
                    currentTime = t

                status = sd.CallbackFlags()

                self.callback(indata, outdata, self.blocksize, DummyTime(), status)

                # In Virtual Mode, `indata` is usually zeros, UNLESS the callback filled it?
                # master_callback expects indata from "Hardware". 
                # In our loopback logic enforced in master_callback:
                # "If Loopback is enabled, use the last output buffer as input"
                # So master_callback logic handles the copying from outdata -> internal buffer.
                # So we just pass fresh zero indata every time. 
                # BUT, `outdata` is written to by master_callback. 
                # Next iteration `indata` is still zeros. 
                # The Loopback logic in master_callback uses `self.last_output_buffer` which persists on `self`.
                # So we are good.

            except Exception as e:
                print(f"VirtualStream Error: {e}")
                # Don't crash thread, just log
                pass


class AudioEngine:
    """
    Handles audio I/O operations using sounddevice.
    Implements a mixer to support multiple simultaneous clients.
    """

    def __init__(self):
        self.input_device = None
        self.output_device = None
        self.sample_rate = 48000
        self.block_size = 1024
        self.stream = None
        self.logger = logging.getLogger(__name__)

        # PipeWire/JACK resident mode: keep PortAudio stream open for the app lifetime.
        self.pipewire_jack_resident = False
        self.jack_client_name = "MeasureLab"

        # Offline / Virtual Mode
        self.offline_mode = False

        # Calibration
        self.calibration = CalibrationManager()

        # Channel Configuration
        # 'stereo', 'left', 'right'
        self.input_channel_mode = "stereo"
        self.output_channel_mode = "stereo"

        # Mixer State
        self.callbacks = {}  # id -> callback
        self._cached_callbacks = []  # Cached list of values(self.callbacks)
        self.next_callback_id = 0
        self.lock = threading.Lock()

        # Status Monitoring
        # Loopback State
        self.loopback = False
        self.mute_output = False
        self.last_output_buffer = None

        # Accumulate callback status flags between UI polls.
        self.accumulated_status = sd.CallbackFlags()

        # Pre-allocated buffers to reduce GC pressure
        self._mix_buffer = None
        self._client_buffer = None
        self._logical_in_buffer = None

        # Error tracking
        self.last_callback_error = None
        self.callback_error_count = 0

    def set_pipewire_jack_resident(self, enabled: bool):
        """Enable/disable resident stream mode (useful for PipeWire/JACK routing persistence)."""
        enabled = bool(enabled)
        self.pipewire_jack_resident = enabled
        self.logger.info(f"Set PipeWire/JACK resident mode: {enabled}")

        if enabled:
            # Ensure master stream is open even with zero clients.
            self._start_master_stream()
            return

        # Disabled: revert to legacy behavior (only keep stream open while clients exist).
        with self.lock:
            has_clients = bool(self.callbacks)
        if not has_clients:
            self.stop_stream()

    def set_offline_mode(self, enabled: bool):
        """Enable/disable offline (virtual) mode."""
        if self.offline_mode == enabled:
            return

        self.offline_mode = enabled
        self.logger.info(f"Set offline mode: {enabled}")

        # Restart stream if active to switch backend
        if self.is_active():
            self._restart_stream()

    def set_loopback(self, enabled):
        self.loopback = enabled
        self.logger.info(f"Set software loopback: {enabled}")

    def set_mute_output(self, enabled):
        self.mute_output = enabled
        self.logger.info(f"Set mute output: {enabled}")

    def list_devices(self):
        """Returns a list of available audio devices.

        We enrich PortAudio device info with a human-readable host API name
        (e.g. ASIO/WASAPI/DirectSound on Windows) to make UI selection clearer.
        """
        # If offline mode, maybe return a dummy list or let UI handle it?
        # The plan says "Disable/Hide Input and Output Device selectors" in UI.
        # So we can keep this standard for when not in offline mode, 
        # or return a specific virtual device list if needed.
        # For now, let's keep standard behavior so user can see hardware even if offline is checked (though controls disabled).

        devices = sd.query_devices()

        # Try to attach host API names; fall back to raw device dicts on error.
        try:
            hostapis = sd.query_hostapis()
        except Exception:
            hostapis = None

        enriched = []
        for dev in devices:
            d = dict(dev)
            hostapi_name = None
            if hostapis is not None:
                try:
                    hostapi_idx = d.get("hostapi")
                    if hostapi_idx is not None and 0 <= int(hostapi_idx) < len(hostapis):
                        hostapi_name = hostapis[int(hostapi_idx)].get("name")
                except Exception:
                    hostapi_name = None

            if hostapi_name:
                d["hostapi_name"] = str(hostapi_name)

            enriched.append(d)

        return enriched

    def get_host_apis(self):
        """Returns a list of available host APIs."""
        try:
            return list(sd.query_hostapis())
        except Exception:
            return []

    def set_devices(self, input_device_id, output_device_id):
        """Sets the input and output devices."""
        self.input_device = input_device_id
        self.output_device = output_device_id
        self.logger.info(f"Set devices: Input={input_device_id}, Output={output_device_id}")
        # Restart stream if running to apply changes
        if self.is_active():
            self._restart_stream()

    def set_sample_rate(self, rate):
        self.sample_rate = rate
        self.logger.info(f"Set sample rate: {rate}")
        if self.is_active():
            self._restart_stream()

    def set_block_size(self, size):
        self.block_size = size
        self.logger.info(f"Set block size: {size}")
        if self.is_active():
            self._restart_stream()

    def set_channel_mode(self, input_mode, output_mode):
        self.input_channel_mode = input_mode
        self.output_channel_mode = output_mode
        self.logger.info(f"Set channel modes: Input={input_mode}, Output={output_mode}")
        # Note: Changing channel mode might affect active callbacks if they expect specific mapping.
        # For now, we assume global mode applies to the master stream.
        if self.is_active():
            self._restart_stream()

    def register_callback(self, callback):
        """
        Registers a callback for audio processing.
        Returns a callback_id.
        Callback signature: callback(indata, outdata, frames, time, status)
        """
        with self.lock:
            cid = self.next_callback_id
            self.next_callback_id += 1
            self.callbacks[cid] = callback
            self._cached_callbacks = list(self.callbacks.values())

            # Start stream if not running
            if self.stream is None:
                self._start_master_stream()

        self.logger.info(f"Registered callback {cid}")
        return cid

    def unregister_callback(self, callback_id):
        """Unregisters a callback by ID."""
        should_stop = False
        unregistered = False
        with self.lock:
            if callback_id in self.callbacks:
                del self.callbacks[callback_id]
                self._cached_callbacks = list(self.callbacks.values())
                unregistered = True

            # Check if we should stop the stream
            if (not self.callbacks) and (self.stream is not None) and (not self.pipewire_jack_resident):
                should_stop = True

        if unregistered:
            self.logger.info(f"Unregistered callback {callback_id}")

        # Stop stream outside the lock to avoid deadlock with callback
        if should_stop:
            self.stop_stream()

    def _start_master_stream(self):
        """Starts the underlying sounddevice stream or VirtualStream."""
        if self.stream is not None:
            return

        # Determine hardware channels needed based on mode
        in_mode = self.input_channel_mode
        out_mode = self.output_channel_mode

        hw_in_ch = 2 if in_mode in ["right", "stereo"] else 1
        hw_out_ch = 2 if out_mode in ["right", "stereo"] else 1

        # Reset loopback buffer
        self.last_output_buffer = None

        def master_callback(indata, outdata, frames, time, status):
            if status:
                self.accumulated_status |= status

            # Zero out master output buffer first
            outdata.fill(0)

            # Prepare logical input for clients
            # Map Hardware Input -> Logical Input (Stereo usually, or as requested)

            # If Loopback is enabled, use the last output buffer as input
            # Works same for Virtual and Hardware: 
            # Virtual: indata is zeros. loopback copies stored last_out to logical_in.
            # Hardware: indata is mic. loopback copies stored last_out to logical_in (ignoring mic).
            # If Loopback is enabled OR we are in Offline Mode (where there is no other input),
            # use the last output buffer as input.
            # Virtual: indata is zeros. loopback copies stored last_out to logical_in.
            # Hardware: indata is mic. loopback copies stored last_out to logical_in (ignoring mic).
            use_loopback = self.loopback or self.offline_mode
            if use_loopback and self.last_output_buffer is not None and len(self.last_output_buffer) == frames:
                # We use the mixed output from the previous block
                # last_output_buffer is (frames, logical_out_ch)
                # We need to map it to logical_in (frames, 2)

                # Assuming logical_out_ch is 2 (stereo) or 1 (mono)
                # logical_in is usually stereo (2)

                lb_src = self.last_output_buffer
                # Reuse logical input buffer if possible to avoid allocation
                if self._logical_in_buffer is None or self._logical_in_buffer.shape != (frames, 2):
                    # Allocate new buffer (zeros is safer than empty for initial state)
                    self._logical_in_buffer = np.zeros((frames, 2), dtype="float32")

                logical_in = self._logical_in_buffer

                if lb_src.shape[1] >= 2:
                    logical_in[:, :2] = lb_src[:, :2]
                elif lb_src.shape[1] == 1:
                    logical_in[:, 0] = lb_src[:, 0]
                    logical_in[:, 1] = lb_src[:, 0]
                else:
                    # Should not happen, but ensure silence if shape is unexpected
                    logical_in.fill(0)
            else:
                # Standard Hardware Input Mapping
                if in_mode == "left":
                    logical_in = indata[:, 0:1]
                elif in_mode == "right":
                    if indata.shape[1] >= 2:
                        logical_in = indata[:, 1:2]
                    else:
                        logical_in = np.zeros((frames, 1))
                else:  # stereo
                    logical_in = indata[:, 0:2]

            # Create a temp output buffer for clients
            logical_out_ch = 2 if out_mode == "stereo" else 1

            # Use cached callbacks (atomic read)
            active_callbacks = self._cached_callbacks

            if not active_callbacks:
                # Even if no callbacks, we might need to update last_output_buffer (silence)
                if use_loopback:
                    if self.last_output_buffer is None or len(self.last_output_buffer) != frames:
                        self.last_output_buffer = np.zeros((frames, logical_out_ch), dtype="float32")
                    else:
                        self.last_output_buffer.fill(0)
                return

            # Mix buffer
            if self._mix_buffer is not None and self._mix_buffer.shape == (frames, logical_out_ch):
                mix_buffer = self._mix_buffer
                mix_buffer.fill(0)
            else:
                mix_buffer = np.zeros((frames, logical_out_ch), dtype="float32")
                self._mix_buffer = mix_buffer

            for cb in active_callbacks:
                # Temp buffer for this client
                if self._client_buffer is not None and self._client_buffer.shape == (frames, logical_out_ch):
                    client_out = self._client_buffer
                    client_out.fill(0)
                else:
                    client_out = np.zeros_like(mix_buffer)
                    self._client_buffer = client_out

                try:
                    cb(logical_in, client_out, frames, time, status)
                except Exception as e:
                    # Optimization: Use non-blocking error tracking instead of print to avoid audio dropouts
                    self.last_callback_error = e
                    self.callback_error_count += 1
                    continue

                # Sum to mix
                mix_buffer += client_out

            # Store for next loopback cycle
            if use_loopback:
                if self.last_output_buffer is None or self.last_output_buffer.shape != mix_buffer.shape:
                    self.last_output_buffer = np.empty_like(mix_buffer)
                np.copyto(self.last_output_buffer, mix_buffer)

            # Map Logical Output -> Hardware Output
            if not self.mute_output:
                if out_mode == "stereo":
                    outdata[:, 0:2] = mix_buffer
                elif out_mode == "left":
                    outdata[:, 0:1] = mix_buffer
                    if outdata.shape[1] > 1:
                        outdata[:, 1:] = 0
                elif out_mode == "right":
                    if outdata.shape[1] >= 2:
                        outdata[:, 1:2] = mix_buffer
                        outdata[:, 0] = 0
            # If muted, outdata is already 0 filled at start of callback

        try:
            if self.offline_mode:
                self.stream = VirtualStream(
                    samplerate=self.sample_rate,
                    blocksize=self.block_size,
                    channels=(hw_in_ch, hw_out_ch),
                    callback=master_callback
                )
                self.stream.start()
                self.logger.info(f"Virtual (Offline) audio stream started. SR={self.sample_rate}")
            else:
                extra_settings = None
                # If running on JACK (including PipeWire-JACK), attempt to fix the client/node name.
                try:
                    hostapi_name = None
                    dev_id = self.output_device
                    if dev_id is None:
                        # Fallback to default output device.
                        dev_id = sd.default.device[1]
                    if dev_id is not None and dev_id != -1:
                        hostapi_idx = sd.query_devices(dev_id).get("hostapi")
                        if hostapi_idx is not None:
                            hostapi_name = sd.query_hostapis(hostapi_idx).get("name")
                    if hostapi_name and "jack" in str(hostapi_name).lower():
                        extra_settings = sd.JackSettings(client_name=self.jack_client_name)
                except Exception:
                    extra_settings = None

                self.stream = sd.Stream(
                    device=(self.input_device, self.output_device),
                    samplerate=self.sample_rate,
                    blocksize=self.block_size,
                    callback=master_callback,
                    channels=(hw_in_ch, hw_out_ch),
                    dtype="float32",
                    latency="high",
                    extra_settings=extra_settings,
                )
                self.stream.start()
                self.logger.info(f"Master audio stream started. SR={self.sample_rate}, HW_Ch=({hw_in_ch}, {hw_out_ch})")
        except Exception as e:
            self.logger.error(f"Failed to start master stream: {e}")
            # Don't raise, just log. Clients will just not run.
            self.stream = None

    def stop_stream(self):
        """Stops the master audio stream."""
        if self.stream is not None:
            self.stream.stop()
            self.stream.close()
            self.stream = None
            self.logger.info("Master audio stream stopped")

    def _restart_stream(self):
        self.stop_stream()
        if self.callbacks:
            self._start_master_stream()

    def is_active(self):
        """Returns True if the stream is active."""
        return self.stream is not None and self.stream.active

    def get_status(self):
        """Returns a dictionary containing current engine status."""
        active = self.is_active()
        cpu_load = 0.0
        if active and self.stream:
            cpu_load = self.stream.cpu_load

        with self.lock:
            client_count = len(self.callbacks)

        # Get and reset accumulated status
        current_status_flags = self.accumulated_status
        self.accumulated_status = sd.CallbackFlags()

        # Get and reset error stats
        error_count = self.callback_error_count
        last_error = str(self.last_callback_error) if self.last_callback_error else None
        self.callback_error_count = 0
        self.last_callback_error = None

        return {
            "active": active,
            "offline_mode": self.offline_mode,
            "input_channels": self.input_channel_mode,
            "output_channels": self.output_channel_mode,
            "sample_rate": self.sample_rate,
            "cpu_load": cpu_load,
            "active_clients": client_count,
            "input_device": self.input_device,
            "output_device": self.output_device,
            "status_flags": current_status_flags,
            "error_count": error_count,
            "last_error": last_error,
        }

