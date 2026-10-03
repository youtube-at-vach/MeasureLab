//! Minimal PortAudio v19 C ABI. All symbols borrow the retained, explicitly loaded
//! library. Definitions follow portaudio.h and pa_mac_core.h (see callback-input.md).
use libloading::Library;
use std::ffi::{c_char, c_double, c_int, c_ulong, c_void};
use std::path::Path;

#[repr(C)]
pub(crate) struct DeviceInfo {
    pub version: c_int,
    pub name: *const c_char,
    pub host_api: c_int,
    pub input_channels: c_int,
    pub output_channels: c_int,
    pub low_input_latency: c_double,
    pub low_output_latency: c_double,
    pub high_input_latency: c_double,
    pub high_output_latency: c_double,
    pub default_rate: c_double,
}
#[repr(C)]
pub(crate) struct Parameters {
    pub device: c_int,
    pub channels: c_int,
    pub sample_format: c_ulong,
    pub latency: c_double,
    pub host_info: *mut c_void,
}
#[repr(C)]
pub(crate) struct StreamInfo {
    pub version: c_int,
    pub input_latency: c_double,
    pub output_latency: c_double,
    pub rate: c_double,
}
#[repr(C)]
pub(crate) struct CallbackTime {
    pub input: c_double,
    pub current: c_double,
    pub output: c_double,
}
#[cfg(target_os = "macos")]
#[repr(C)]
pub(crate) struct MacInfo {
    pub size: c_ulong,
    pub host_api_type: c_int,
    pub version: c_ulong,
    pub flags: c_ulong,
    pub channel_map: *const i32,
    pub channel_map_size: c_ulong,
}
pub(crate) type Callback = unsafe extern "C" fn(
    *const c_void,
    *mut c_void,
    c_ulong,
    *const CallbackTime,
    c_ulong,
    *mut c_void,
) -> c_int;
pub(crate) type Open = unsafe extern "C" fn(
    *mut *mut c_void,
    *const Parameters,
    *const Parameters,
    c_double,
    c_ulong,
    c_ulong,
    Callback,
    *mut c_void,
) -> c_int;
pub(crate) struct Api {
    // Retain the library until all streams and their callbacks are gone.
    pub _library: Option<Library>,
    pub version: c_int,
    pub initialize: unsafe extern "C" fn() -> c_int,
    pub terminate: unsafe extern "C" fn() -> c_int,
    pub device_count: unsafe extern "C" fn() -> c_int,
    pub device_info: unsafe extern "C" fn(c_int) -> *const DeviceInfo,
    pub supported: unsafe extern "C" fn(*const Parameters, *const Parameters, c_double) -> c_int,
    pub open: Open,
    pub start: unsafe extern "C" fn(*mut c_void) -> c_int,
    pub abort: unsafe extern "C" fn(*mut c_void) -> c_int,
    pub close: unsafe extern "C" fn(*mut c_void) -> c_int,
    pub active: unsafe extern "C" fn(*mut c_void) -> c_int,
    pub info: unsafe extern "C" fn(*mut c_void) -> *const StreamInfo,
    #[cfg(target_os = "macos")]
    pub mac_setup: unsafe extern "C" fn(*mut MacInfo, c_ulong),
}
impl Api {
    pub fn load(path: &Path) -> Result<Self, String> {
        // SAFETY: the explicit path must contain a trusted PortAudio v19 library.
        // Each symbol has the documented C ABI, and the Library is retained in Api.
        unsafe {
            let library = Library::new(path).map_err(|e| format!("portaudio_library: {e}"))?;
            macro_rules! symbol {
                ($name:literal) => {
                    *library
                        .get(concat!($name, "\0").as_bytes())
                        .map_err(|e| format!("portaudio_symbol: {e}"))?
                };
            }
            let version: unsafe extern "C" fn() -> c_int = symbol!("Pa_GetVersion");
            let version = version();
            if version >> 16 != 19 {
                return Err(format!("portaudio_v19_required: {version}"));
            }
            Ok(Self {
                version,
                initialize: symbol!("Pa_Initialize"),
                terminate: symbol!("Pa_Terminate"),
                device_count: symbol!("Pa_GetDeviceCount"),
                device_info: symbol!("Pa_GetDeviceInfo"),
                supported: symbol!("Pa_IsFormatSupported"),
                open: symbol!("Pa_OpenStream"),
                start: symbol!("Pa_StartStream"),
                abort: symbol!("Pa_AbortStream"),
                close: symbol!("Pa_CloseStream"),
                active: symbol!("Pa_IsStreamActive"),
                info: symbol!("Pa_GetStreamInfo"),
                #[cfg(target_os = "macos")]
                mac_setup: symbol!("PaMacCore_SetupStreamInfo"),
                _library: Some(library),
            })
        }
    }
}
