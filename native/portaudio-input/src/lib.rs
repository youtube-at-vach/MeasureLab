//! Evaluation-only input callback -> common typed queue. The stream, callback
//! context and library live on the analysis owner; no Python/pipe/blocking input.
//! Unsafe code is isolated here; graph, display and audio-probe stay safe Rust.
#![deny(unsafe_op_in_unsafe_fn)]
use audio_core::backend::{Backend, InputBinding, InputWriter, SampleFormat};
use audio_core::{Consumer, IoFormat, MAX_CALLBACK_FRAMES};
use serde_json::{Value, json};
use std::ffi::{CStr, c_int, c_ulong, c_void};
use std::path::Path;
use std::ptr;
use std::sync::{
    Arc, Mutex, MutexGuard,
    atomic::{AtomicU64, Ordering::Relaxed},
};
use std::time::Instant;

mod ffi;
// The evaluation permits one native PA input owner per process. A second owner
// fails immediately; initialization/termination must never race another owner.
static OWNER: Mutex<()> = Mutex::new(());
#[derive(Default)]
struct Counters {
    callbacks: AtomicU64,
    frames: AtomicU64,
    rejected: AtomicU64,
    errors: AtomicU64,
    xruns: AtomicU64,
}
struct Context {
    writer: InputWriter<f32>,
    channels: usize,
    counters: Arc<Counters>,
}
impl Context {
    fn deliver(&mut self, values: &[f32], flags: c_ulong) -> c_int {
        self.counters.callbacks.fetch_add(1, Relaxed);
        // Backend loss has no verified absolute sample position. Abort before
        // publishing any affected block, instead of pretending continuity.
        if flags != 0 {
            self.counters.xruns.fetch_add(1, Relaxed);
            return 2; // paAbort
        }
        if self.writer.write_next(values, None, 0).is_err() {
            self.counters.rejected.fetch_add(1, Relaxed);
            return 2;
        }
        self.counters
            .frames
            .fetch_add((values.len() / self.channels) as u64, Relaxed);
        0 // paContinue
    }
}
/// Called only by PortAudio for this input-only, interleaved f32 stream. Context
/// is stable in its Box and accessed exclusively by the serial input callback.
unsafe extern "C" fn callback(
    input: *const c_void,
    _output: *mut c_void,
    frames: c_ulong,
    _time: *const ffi::CallbackTime,
    flags: c_ulong,
    user: *mut c_void,
) -> c_int {
    // SAFETY: user is the Box<Context> retained until Pa_CloseStream succeeds.
    let context = unsafe { &mut *user.cast::<Context>() };
    if flags != 0 {
        return context.deliver(&[], flags);
    }
    if input.is_null() || frames == 0 || frames > MAX_CALLBACK_FRAMES as c_ulong {
        context.counters.rejected.fetch_add(1, Relaxed);
        return 2;
    }
    // SAFETY: paFloat32/interleaved, validated channel count, bounded frame count;
    // PortAudio owns this buffer for the duration of this callback.
    let values = unsafe {
        std::slice::from_raw_parts(input.cast::<f32>(), frames as usize * context.channels)
    };
    context.deliver(values, 0)
}
struct Session {
    api: ffi::Api,
    _owner: MutexGuard<'static, ()>,
    context: Box<Context>,
    stream: *mut c_void,
    started: bool,
}
/// Not Send/Sync: open/start/close/terminate stay on the same analysis thread.
pub struct PortAudioInput {
    session: Option<Session>,
    counters: Arc<Counters>,
    terminated: bool,
    version: c_int,
    reported_rate: Option<f64>,
    stream_info_version: Option<c_int>,
}
pub fn validate(path: &Path, name: &str, channels: usize, format: &IoFormat) -> Result<(), String> {
    if !path.is_absolute() || format.rate != [48000, 1] {
        return Err("live_portaudio_configuration".into());
    }
    InputBinding {
        backend: Backend::PortAudio,
        device: name.into(),
        device_channels: channels,
        sample_format: SampleFormat::F32,
        format: format.clone(),
    }
    .validate()
    .map_err(String::from)
}
impl PortAudioInput {
    pub fn open(
        path: &Path,
        name: &str,
        channels: usize,
        format: &IoFormat,
    ) -> Result<(Self, Consumer), String> {
        validate(path, name, channels, format)?;
        let owner = OWNER.try_lock().map_err(|_| "live_portaudio_owner_busy")?;
        let binding = InputBinding {
            backend: Backend::PortAudio,
            device: name.into(),
            device_channels: channels,
            sample_format: SampleFormat::F32,
            format: format.clone(),
        };
        // Validation/capacity are fixed before initialization; this queue is bounded.
        let (writer, rx) = binding.queue::<f32>(8192)?;
        let api = ffi::Api::load(path)?;
        // SAFETY: exclusive owner, resolved ABI; no callbacks exist yet.
        check("initialize", unsafe { (api.initialize)() })?;
        let counters = Arc::new(Counters::default());
        let mut input = Self {
            version: api.version,
            session: Some(Session {
                api,
                _owner: owner,
                context: Box::new(Context {
                    writer,
                    channels,
                    counters: counters.clone(),
                }),
                stream: ptr::null_mut(),
                started: false,
            }),
            counters,
            terminated: false,
            reported_rate: None,
            stream_info_version: None,
        };
        // All subsequent failures run the same close/terminate path via Drop.
        input.open_stream(name, channels)?;
        Ok((input, rx))
    }
    fn open_stream(&mut self, name: &str, channels: usize) -> Result<(), String> {
        let session = self.session.as_mut().unwrap();
        // SAFETY: initialized library and exclusive owner. DeviceInfo/string
        // pointers are borrowed only while initialization is held.
        unsafe {
            let count = (session.api.device_count)();
            if count < 0 {
                return Err(format!("portaudio_device_count: {count}"));
            }
            let mut matches = Vec::new();
            for device in 0..count {
                let info = (session.api.device_info)(device);
                if let Some(info) = info.as_ref()
                    && !info.name.is_null()
                    && CStr::from_ptr(info.name).to_bytes() == name.as_bytes()
                    && info.input_channels as usize == channels
                {
                    matches.push((device, info.low_input_latency));
                }
            }
            if matches.len() != 1 {
                return Err("live_exact_device_not_unique".into());
            }
            let (device, latency) = matches[0];
            if !latency.is_finite() || latency < 0. {
                return Err("live_portaudio_latency".into());
            }
            #[cfg(target_os = "macos")]
            let mut mac = ffi::MacInfo {
                size: 0,
                host_api_type: 0,
                version: 0,
                flags: 0,
                channel_map: ptr::null(),
                channel_map_size: 0,
            };
            #[cfg(target_os = "macos")]
            (session.api.mac_setup)(&mut mac, 3); // change parameters + reject rate conversion
            let parameters = ffi::Parameters {
                device,
                channels: channels as c_int,
                sample_format: 1,
                latency,
                #[cfg(target_os = "macos")]
                host_info: ptr::from_mut(&mut mac).cast(),
                #[cfg(not(target_os = "macos"))]
                host_info: ptr::null_mut(),
            };
            check(
                "format",
                (session.api.supported)(&parameters, ptr::null(), 48000.),
            )?;
            check(
                "open",
                (session.api.open)(
                    &mut session.stream,
                    &parameters,
                    ptr::null(),
                    48000.,
                    256,
                    3,
                    callback,
                    ptr::from_mut(session.context.as_mut()).cast(),
                ),
            )?;
            if session.stream.is_null() {
                return Err("live_portaudio_null_stream".into());
            }
            let info = (session.api.info)(session.stream)
                .as_ref()
                .ok_or("live_portaudio_stream_info")?;
            // v19.7 CoreAudio leaves structVersion zero (pa_stream.c initializes
            // latency/rate only). Verify the API major via Pa_GetVersion, retain
            // this diagnostic field, and check the actual reported sample rate.
            self.stream_info_version = Some(info.version);
            self.reported_rate = Some(info.rate);
            if info.rate != 48000. {
                return Err("live_explicit_format_unsupported".into());
            }
        }
        Ok(())
    }
    pub fn start(&mut self) -> Result<(), String> {
        let session = self.session.as_mut().ok_or("live_input_closed")?;
        // SAFETY: open stream with retained context/library, called by its owner.
        check("start", unsafe { (session.api.start)(session.stream) })?;
        session.started = true;
        Ok(())
    }
    pub fn failed(&self) -> bool {
        if self.counters.errors.load(Relaxed) != 0
            || self.counters.rejected.load(Relaxed) != 0
            || self.counters.xruns.load(Relaxed) != 0
        {
            return true;
        }
        self.session.as_ref().is_some_and(|session| {
            // SAFETY: stream is open while session is retained on its owner.
            session.started && unsafe { (session.api.active)(session.stream) } != 1
        })
    }
    pub fn stop(&mut self) -> Result<f64, String> {
        let started = Instant::now();
        let Some(session) = self.session.as_mut() else {
            return Ok(0.);
        };
        let mut error = None;
        // SAFETY: exclusive owner; callback state/library remain alive until
        // close succeeds. Close is attempted even after abort failure.
        unsafe {
            if !session.stream.is_null() {
                if session.started {
                    let code = (session.api.abort)(session.stream);
                    if code != 0 && code != -9983 {
                        error = Some(format!("portaudio_abort: {code}"));
                    }
                }
                check("close", (session.api.close)(session.stream))?;
                session.stream = ptr::null_mut();
            }
            let code = (session.api.terminate)();
            self.terminated = code == 0;
            if code != 0 {
                error = Some(format!("portaudio_terminate: {code}"));
            }
        }
        if self.terminated {
            self.session = None;
        }
        if let Some(error) = error {
            self.counters.errors.fetch_add(1, Relaxed);
            return Err(error);
        }
        Ok(started.elapsed().as_secs_f64() * 1000.)
    }
    pub fn report(&self) -> Value {
        json!({"callbacks": self.counters.callbacks.load(Relaxed),
            "frames": self.counters.frames.load(Relaxed),
            "rejected": self.counters.rejected.load(Relaxed),
            "errors": self.counters.errors.load(Relaxed),
            "xruns": self.counters.xruns.load(Relaxed),
            "closed": self.session.as_ref().is_none_or(|s| s.stream.is_null()), "terminated": self.terminated,
            "api_version": self.version, "reported_rate": self.reported_rate,
            "stream_info_version": self.stream_info_version,
            "transport": "native PortAudio callback -> common f32 input queue"})
    }
}
impl Drop for PortAudioInput {
    fn drop(&mut self) {
        if self.stop().is_err()
            && let Some(session) = self.session.take()
        {
            // Failed close/terminate does not prove native activity ended. Retain
            // the library, context and exclusive lease rather than freeing pointers.
            // The explicit stop error and report mark a failed recovery trial.
            std::mem::forget(session);
        }
    }
}
fn check(operation: &str, code: c_int) -> Result<(), String> {
    if code == 0 {
        Ok(())
    } else {
        Err(format!("portaudio_{operation}: {code}"))
    }
}

#[cfg(test)]
mod tests;
