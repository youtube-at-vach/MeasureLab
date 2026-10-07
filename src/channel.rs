//! Input channel IDs are zero-based frame indices; display names are separate.
//! Unavailable assignments stay unavailable, including after a device change.

pub type ChannelId = usize;

pub fn available(channel: ChannelId, channels: usize) -> bool {
    channel < channels && channel < crate::signal::MAX_CHANNELS
}

pub fn name(channel: ChannelId) -> String {
    format!("CH {}", channel.saturating_add(1))
}

/// Scope trace slots or XY axes, in order. Repeated IDs are allowed.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Pair(pub [ChannelId; 2]);

impl Default for Pair {
    fn default() -> Self {
        Self([0, 1])
    }
}

impl Pair {
    pub fn available(self, channels: usize) -> bool {
        self.0.into_iter().all(|id| available(id, channels))
    }

    /// Both values come from this exact frame, without a channel fallback.
    pub fn values(self, frame: &[f64]) -> Option<[f64; 2]> {
        self.available(frame.len())
            .then(|| [frame[self.0[0]], frame[self.0[1]]])
    }
}
