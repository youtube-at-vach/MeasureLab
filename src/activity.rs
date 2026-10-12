//! OS scheduling activity scoped independently to live input and output.
#[cfg(target_os = "macos")]
pub(crate) struct Activity {
    process: objc2::rc::Retained<objc2_foundation::NSProcessInfo>,
    token:
        objc2::rc::Retained<objc2::runtime::ProtocolObject<dyn objc2::runtime::NSObjectProtocol>>,
}
#[cfg(not(target_os = "macos"))]
pub(crate) struct Activity;
impl Activity {
    pub(crate) fn new(reason: &str) -> Self {
        #[cfg(target_os = "macos")]
        {
            use objc2_foundation::{NSActivityOptions, NSProcessInfo, NSString};
            let process = NSProcessInfo::processInfo();
            let token = process.beginActivityWithOptions_reason(
                NSActivityOptions::UserInitiated | NSActivityOptions::LatencyCritical,
                &NSString::from_str(reason),
            );
            Self { process, token }
        }
        #[cfg(not(target_os = "macos"))]
        {
            let _ = reason;
            Self
        }
    }
}
#[cfg(target_os = "macos")]
impl Drop for Activity {
    fn drop(&mut self) {
        // SAFETY: this is the activity token returned by this process above.
        unsafe { self.process.endActivity(&self.token) };
    }
}
