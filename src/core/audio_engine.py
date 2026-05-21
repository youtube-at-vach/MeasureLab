import logging
import threading

import numpy as np
import sounddevice as sd

from src.core.calibration import CalibrationManager


import time


class _DummyTime:
    """Helper class to mock sounddevice time object in virtual stream."""

    def __init__(self, t, interval):
        self.inputBufferAdcTime = t
        self.outputBufferDacTime = t + interval
        self.currentTime = t


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
        self.logger = logging.getLogger(__name__)

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
                self._stop_event.wait(to_sleep)

            next_call_time += interval

            # Call callback
            try:
                # status=0 for all good
                # We need a proper CData struct for time if we strictly follow sd type,
                # but usually python callbacks just access attributes.
                # Let's mock a simple object if needed, or just pass an object.
                # sd.Stream callback signature: (indata, outdata, frames, time, status)
                # time is CData {inputBufferAdcTime, outputBufferDacTime, ...}
                # For virtual, we can pass a dummy object or None if the app handles it safely.
                # AudioEngine uses `time`? Checking... `cb(logical_in, client_out, frames, time, status)`
                # The callback in AudioEngine is `master_callback`. It passes `time` through to clients.
                # Let's pass a dummy object.

                status = sd.CallbackFlags()

                self.callback(indata, outdata, self.blocksize, _DummyTime(t, interval), status)

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
                self.logger.error(f"VirtualStream Error: {e}")
                # Don't crash thread, just log
                pass


class AudioEngine:
    """
    Handles audio I/O operations using sounddevice.
    Implements a mixer to support multiple simultaneous clients.
    """

    MODE_STEREO = 0
    MODE_LEFT = 1
    MODE_RIGHT = 2

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

        # Precision Mode
        self.audio_engine_64bit = False

        # Calibration
        self.calibration = CalibrationManager()

        # Channel Configuration
        # 'stereo', 'left', 'right'
        self.input_channel_mode = "stereo"
        self.output_channel_mode = "stereo"
        self._current_in_mode = self.MODE_STEREO
        self._current_out_mode = self.MODE_STEREO

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

        # Dithering
        self.dithering_enabled = False
        self.dithering_bit_depth = "24"
        self._rng = np.random.default_rng()

        # Caching
        self._device_list_cache = None
        self._host_apis_cache = None
        self._last_cache_time = 0

        # Core Audio macOS Settings
        self.coreaudio_fail_if_conversion_required = True
        self.coreaudio_change_device_parameters = True
        self.coreaudio_conversion_quality = "min"

    def _get_dtype(self):
        """Returns the appropriate numpy dtype based on precision settings."""
        return "float64" if self.audio_engine_64bit else "float32"

    def set_audio_engine_64bit(self, enabled: bool):
        """Enable/disable 64-bit precision."""
        self.audio_engine_64bit = enabled
        self.logger.debug(f"64-bit Audio Engine (float64) setting changed to: {enabled}")
        # Apply instantly by restarting active stream
        self._restart_stream()

    def set_coreaudio_fail_if_conversion_required(self, enabled: bool):
        """Sets whether sample rate conversion failures are enforced on macOS."""
        self.coreaudio_fail_if_conversion_required = bool(enabled)
        self.logger.debug(f"CoreAudio fail_if_conversion_required set to: {enabled}")
        self._restart_stream()

    def set_coreaudio_change_device_parameters(self, enabled: bool):
        """Sets whether CoreAudio device parameters can be modified for latency optimization."""
        self.coreaudio_change_device_parameters = bool(enabled)
        self.logger.debug(f"CoreAudio change_device_parameters set to: {enabled}")
        self._restart_stream()

    def set_coreaudio_conversion_quality(self, quality: str):
        """Sets sample rate conversion quality for CoreAudio streams."""
        self.coreaudio_conversion_quality = str(quality)
        self.logger.debug(f"CoreAudio conversion_quality set to: {quality}")
        self._restart_stream()

    def set_pipewire_jack_resident(self, enabled: bool):
        """Enable/disable resident stream mode (useful for PipeWire/JACK routing persistence)."""
        enabled = bool(enabled)
        self.pipewire_jack_resident = enabled
        self.logger.debug(f"Set PipeWire/JACK resident mode: {enabled}")

        if enabled:
            # Ensure master stream is open even with zero clients.
            with self.lock:
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
        self.logger.debug(f"Set offline mode: {enabled}")

        # Restart stream if active to switch backend
        if self.is_active():
            self._restart_stream()

    def set_loopback(self, enabled):
        self.loopback = enabled
        self.logger.debug(f"Set software loopback: {enabled}")

    def set_mute_output(self, enabled):
        self.mute_output = enabled
        self.logger.debug(f"Set mute output: {enabled}")

    def refresh_backend(self):
        """
        Forces a re-initialization of the PortAudio backend.
        This is useful on Linux/ALSA where device lists are cached.
        """
        self.logger.debug("Refreshing audio backend...")

        # Stop everything first
        self.stop_stream()

        # Terminate PortAudio
        try:
            sd._terminate()
        except Exception as e:
            self.logger.warning(f"Error terminating PortAudio: {e}")

        # Re-initialize PortAudio
        try:
            sd._initialize()
            self._device_list_cache = None
            self._host_apis_cache = None
            self._last_cache_time = 0
            self.logger.debug("Audio backend refreshed successfully.")
        except Exception as e:
            self.logger.error(f"Error re-initializing PortAudio: {e}")

    def _get_cached_audio_info(self):
        now = time.time()
        if (
            self._device_list_cache is not None
            and self._host_apis_cache is not None
            and (now - self._last_cache_time) < 60.0
        ):
            return self._device_list_cache, self._host_apis_cache

        devices = sd.query_devices()
        try:
            hostapis = sd.query_hostapis()
        except Exception:
            hostapis = None
        self._device_list_cache = devices
        self._host_apis_cache = hostapis
        self._last_cache_time = now
        return devices, hostapis

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

        devices, hostapis = self._get_cached_audio_info()

        if hostapis is None:
            return [dict(dev) for dev in devices]

        names = {i: str(name) for i, ha in enumerate(hostapis) if (name := ha.get("name"))}

        res = [dict(dev) for dev in devices]
        for d in res:
            try:
                idx = d.get("hostapi")
                if idx is not None:
                    name = names.get(int(idx))
                    if name is not None:
                        d["hostapi_name"] = name
            except (TypeError, ValueError) as e:
                self.logger.warning(
                    f"Failed to parse hostapi index {idx!r} for device '{d.get('name', 'Unknown')}': {e}"
                )

        return res

    def get_host_apis(self):
        """Returns a list of available host APIs."""
        _, hostapis = self._get_cached_audio_info()
        return list(hostapis) if hostapis is not None else []

    def set_devices(self, input_device_id, output_device_id):
        """Sets the input and output devices."""
        self.input_device = input_device_id
        self.output_device = output_device_id
        self.logger.debug(f"Set devices: Input={input_device_id}, Output={output_device_id}")
        # Restart stream if running to apply changes
        if self.is_active():
            self._restart_stream()

    def set_sample_rate(self, rate):
        self.sample_rate = rate
        self.logger.debug(f"Set sample rate: {rate}")
        if self.is_active():
            self._restart_stream()

    def set_block_size(self, size):
        self.block_size = size
        self.logger.debug(f"Set block size: {size}")
        if self.is_active():
            self._restart_stream()

    def set_channel_mode(self, input_mode, output_mode):
        self.input_channel_mode = input_mode
        self.output_channel_mode = output_mode
        self.logger.debug(f"Set channel modes: Input={input_mode}, Output={output_mode}")
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

        self.logger.debug(f"Registered callback {cid}")
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
            self.logger.debug(f"Unregistered callback {callback_id}")

        # Stop stream outside the lock to avoid deadlock with callback
        if should_stop:
            self.stop_stream()

    def _prepare_logical_input(self, indata, frames, use_loopback):
        """Prepares logical input buffer from hardware input or loopback."""
        if use_loopback and self.last_output_buffer is not None and len(self.last_output_buffer) == frames:
            # Loopback logic: reuse last output
            lb_src = self.last_output_buffer
            if self._logical_in_buffer is None or self._logical_in_buffer.shape != (frames, 2):
                self._logical_in_buffer = np.zeros((frames, 2), dtype=self._get_dtype())

            logical_in = self._logical_in_buffer
            if lb_src.shape[1] >= 2:
                logical_in[:, :2] = lb_src[:, :2]
            elif lb_src.shape[1] == 1:
                logical_in[:, 0] = lb_src[:, 0]
                logical_in[:, 1] = lb_src[:, 0]
            else:
                logical_in.fill(0)
            return logical_in
        else:
            # Hardware Input logic
            in_mode = self._current_in_mode
            req_channels = 1 if in_mode in (self.MODE_LEFT, self.MODE_RIGHT) else 2

            if self._logical_in_buffer is None or self._logical_in_buffer.shape != (frames, req_channels):
                self._logical_in_buffer = np.zeros((frames, req_channels), dtype=self._get_dtype())

            logical_in = self._logical_in_buffer
            if in_mode == self.MODE_LEFT:
                logical_in[:, 0] = indata[:, 0]
            elif in_mode == self.MODE_RIGHT:
                if indata.shape[1] >= 2:
                    logical_in[:, 0] = indata[:, 1]
                else:
                    logical_in.fill(0)
            else:  # stereo
                if indata.shape[1] >= 2:
                    logical_in[:, 0:2] = indata[:, 0:2]
                elif indata.shape[1] == 1:
                    logical_in[:, 0] = indata[:, 0]
                    logical_in[:, 1] = indata[:, 0]
            return logical_in

    def _mix_clients(self, logical_in, frames, time, status, active_callbacks, logical_out_ch):
        """Iterates active clients, executes callbacks, and mixes output."""
        # Initialize or clear mix buffer
        if self._mix_buffer is not None and self._mix_buffer.shape == (frames, logical_out_ch):
            mix_buffer = self._mix_buffer
            mix_buffer.fill(0)
        else:
            mix_buffer = np.zeros((frames, logical_out_ch), dtype=self._get_dtype())
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
                self.last_callback_error = e
                self.callback_error_count += 1
                continue

            mix_buffer += client_out

        return mix_buffer

    def _apply_dithering(self, mix_buffer):
        """Applies TPDF dithering to the mix buffer in-place."""
        depth_str = str(self.dithering_bit_depth)
        if "8" in depth_str:
            bit_depth = 8
        elif "16" in depth_str:
            bit_depth = 16
        else:
            bit_depth = 24
        lsb = 1.0 / (2 ** (bit_depth - 1))

        # Use _client_buffer as temp buffer (guaranteed to be sized correctly here)
        dither_buf = self._client_buffer

        # 1. Generate R1
        self._rng.random(out=dither_buf, dtype=self._get_dtype())
        dither_buf *= lsb
        mix_buffer += dither_buf

        # 2. Generate R2 (subtract)
        self._rng.random(out=dither_buf, dtype=self._get_dtype())
        dither_buf *= lsb
        mix_buffer -= dither_buf

    def _update_loopback_buffer(self, source_buffer, frames, channels):
        """Updates the loopback buffer from the given source (or clears if None)."""
        if source_buffer is None:
            # Fill with silence
            if self.last_output_buffer is None or len(self.last_output_buffer) != frames:
                self.last_output_buffer = np.zeros((frames, channels), dtype=self._get_dtype())
            else:
                self.last_output_buffer.fill(0)
        else:
            if self.last_output_buffer is None or self.last_output_buffer.shape != source_buffer.shape:
                self.last_output_buffer = np.empty_like(source_buffer)
            np.copyto(self.last_output_buffer, source_buffer)

    def _map_logical_to_hardware_output(self, mix_buffer, outdata, out_mode):
        """Maps the logical mix buffer to the hardware output buffer."""
        if self.mute_output:
            return

        if out_mode == self.MODE_STEREO:
            outdata[:, 0:2] = mix_buffer
        elif out_mode == self.MODE_LEFT:
            outdata[:, 0:1] = mix_buffer
            if outdata.shape[1] > 1:
                outdata[:, 1:] = 0
        elif out_mode == self.MODE_RIGHT:
            if outdata.shape[1] >= 2:
                outdata[:, 1:2] = mix_buffer
                outdata[:, 0] = 0

    def _master_callback(self, indata, outdata, frames, time, status):
        if status:
            self.accumulated_status |= status

        # Zero out master output buffer first
        outdata.fill(0)

        # 1. Prepare Inputs
        use_loopback = self.loopback or self.offline_mode
        logical_in = self._prepare_logical_input(indata, frames, use_loopback)

        # 2. Prepare Output Configuration
        out_mode = self._current_out_mode
        logical_out_ch = 2 if out_mode == self.MODE_STEREO else 1
        active_callbacks = self._cached_callbacks

        # 3. Mix Clients
        if not active_callbacks:
            if use_loopback:
                self._update_loopback_buffer(None, frames, logical_out_ch)
            return

        mix_buffer = self._mix_clients(logical_in, frames, time, status, active_callbacks, logical_out_ch)

        # 4. Apply Effects (Dithering)
        if self.dithering_enabled:
            self._apply_dithering(mix_buffer)

        # 5. Update Loopback
        if use_loopback:
            self._update_loopback_buffer(mix_buffer, frames, logical_out_ch)

        # 6. Map to Hardware Output
        self._map_logical_to_hardware_output(mix_buffer, outdata, out_mode)

    def _update_channel_modes(self):
        """
        Updates internal channel mode integers based on string settings.
        Returns the required hardware channel count (in, out).
        """
        in_mode_str = self.input_channel_mode
        out_mode_str = self.output_channel_mode

        if in_mode_str == "left":
            self._current_in_mode = self.MODE_LEFT
        elif in_mode_str == "right":
            self._current_in_mode = self.MODE_RIGHT
        else:
            self._current_in_mode = self.MODE_STEREO

        if out_mode_str == "left":
            self._current_out_mode = self.MODE_LEFT
        elif out_mode_str == "right":
            self._current_out_mode = self.MODE_RIGHT
        else:
            self._current_out_mode = self.MODE_STEREO

        hw_in_ch = 2 if in_mode_str in {"right", "stereo"} else 1
        hw_out_ch = 2 if out_mode_str in {"right", "stereo"} else 1

        return hw_in_ch, hw_out_ch

    def _get_jack_settings(self):
        """
        Returns sd.JackSettings if the output device is JACK/PipeWire, else None.
        """
        # If running on JACK (including PipeWire-JACK), attempt to fix the client/node name.
        try:
            hostapi_name = None
            dev_id = self.output_device
            if dev_id is None:
                # Fallback to default output device.
                dev_id = sd.default.device[1]

            # Use cached devices/hostapis to avoid redundant OS queries
            devices, hostapis = self._get_cached_audio_info()

            if dev_id is not None and 0 <= dev_id < len(devices):
                device_info = devices[dev_id]
                hostapi_idx = device_info.get("hostapi")
                if hostapi_idx is not None and hostapis is not None:
                    if 0 <= int(hostapi_idx) < len(hostapis):
                        hostapi_info = hostapis[int(hostapi_idx)]
                        hostapi_name = hostapi_info.get("name")

            if hostapi_name and "jack" in str(hostapi_name).lower():
                return sd.JackSettings(client_name=self.jack_client_name)
        except Exception as e:
            self.logger.debug(f"Failed to query audio devices for JACK settings: {e}")
        return None

    def _get_coreaudio_settings(self):
        """
        Returns a tuple of (ca_in, ca_out) for CoreAudioSettings if running on macOS, else None.
        """
        import sys

        if sys.platform != "darwin":
            return None
        try:
            ca_in = sd.CoreAudioSettings(
                change_device_parameters=self.coreaudio_change_device_parameters,
                fail_if_conversion_required=self.coreaudio_fail_if_conversion_required,
                conversion_quality=self.coreaudio_conversion_quality,
            )
            ca_out = sd.CoreAudioSettings(
                change_device_parameters=self.coreaudio_change_device_parameters,
                fail_if_conversion_required=self.coreaudio_fail_if_conversion_required,
                conversion_quality=self.coreaudio_conversion_quality,
            )
            return (ca_in, ca_out)
        except Exception as e:
            self.logger.warning(f"Failed to create Core Audio settings: {e}")
        return None

    def _start_master_stream(self):
        """Starts the underlying sounddevice stream or VirtualStream."""
        if self.stream is not None:
            return

        hw_in_ch, hw_out_ch = self._update_channel_modes()

        # Reset loopback buffer
        self.last_output_buffer = None

        try:
            if self.offline_mode:
                self.stream = VirtualStream(
                    samplerate=self.sample_rate,
                    blocksize=self.block_size,
                    channels=(hw_in_ch, hw_out_ch),
                    callback=self._master_callback,
                )
                self.stream.start()
                self.logger.debug(f"Virtual (Offline) audio stream started. SR={self.sample_rate}")
            else:
                import sys

                if sys.platform == "darwin":
                    extra_settings = self._get_coreaudio_settings()
                else:
                    extra_settings = self._get_jack_settings()

                self.stream = sd.Stream(
                    device=(self.input_device, self.output_device),
                    samplerate=self.sample_rate,
                    blocksize=self.block_size,
                    callback=self._master_callback,
                    channels=(hw_in_ch, hw_out_ch),
                    dtype="float32",
                    latency="high",
                    extra_settings=extra_settings,
                )
                self.stream.start()
                self.logger.debug(
                    f"Master audio stream started. SR={self.sample_rate}, HW_Ch=({hw_in_ch}, {hw_out_ch})"
                )
        except Exception as e:
            self.logger.error(f"Failed to start master stream: {e}")
            # Don't raise, just log. Clients will just not run.
            self.stream = None

    def stop_stream(self):
        """Stops the master audio stream."""
        with self.lock:
            if self.stream is not None:
                try:
                    self.stream.stop()
                    self.stream.close()
                except Exception as e:
                    self.logger.error(f"Error stopping stream: {e}")
                finally:
                    self.stream = None
                self.logger.debug("Master audio stream stopped")

    def _restart_stream(self):
        self.stop_stream()
        with self.lock:
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

    def get_input_latency(self):
        """Returns the input latency in seconds."""
        latency = 0.0

        if self.stream is not None:
            # sd.Stream.latency is a tuple (input, output) or float if not available?
            # Documentation says: "The latency of the stream in seconds. This is a tuple (input_latency, output_latency)."
            try:
                # specific check for VirtualStream which might not have latency attr or it is just simulated
                if isinstance(self.stream, VirtualStream):
                    # For virtual stream, latency is essentially one block? Or zero?
                    # Let's say it's 0 for now as it is instantaneous in simulation,
                    # or block_size / sample_rate if we want to simulate buffering.
                    # Logic: VirtualStream reads zeros instantly.
                    return 0.0

                lat = self.stream.latency
                if isinstance(lat, (tuple, list)):
                    latency = float(lat[0])
                else:
                    latency = float(lat)
            except Exception:
                latency = 0.0

        # Fallback if reported latency is effectively zero (common in some backends or if unavailable)
        if latency <= 1e-6:
            # Use block size / sample rate as estimate
            if self.sample_rate > 0:
                latency = float(self.block_size) / float(self.sample_rate)

        return latency
