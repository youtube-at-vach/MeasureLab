//! Input channel IDs are zero-based frame indices; display names are separate.
//! Unavailable assignments stay unavailable, including after a device change.

pub type ChannelId = usize;

pub fn available(channel: ChannelId, channels: usize) -> bool {
    channel < channels && channel < crate::signal::MAX_CHANNELS
}

pub fn name(channel: ChannelId) -> String {
    format!("CH {}", channel.saturating_add(1))
}

/// Ordered input assignments, independent of selection and display visibility.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Channels<const N: usize = 2>(pub [ChannelId; N]);

pub const SCOPE_CHANNELS: usize = 4;
pub use Channels as Pair;
pub type ScopeChannels = Channels<SCOPE_CHANNELS>;

impl<const N: usize> Default for Channels<N> {
    fn default() -> Self {
        Self(std::array::from_fn(|i| i))
    }
}

impl<const N: usize> serde::Serialize for Channels<N> {
    fn serialize<S: serde::Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        serde::Serialize::serialize(self.0.as_slice(), serializer)
    }
}

impl<'de, const N: usize> serde::Deserialize<'de> for Channels<N> {
    fn deserialize<D: serde::Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        let ids = <Vec<ChannelId> as serde::Deserialize>::deserialize(deserializer)?;
        if ids.len() != N {
            return Err(serde::de::Error::custom("Invalid channel assignment count"));
        }
        let mut result = Self::default();
        result.0[..ids.len()].copy_from_slice(&ids);
        Ok(result)
    }
}

impl Channels<2> {
    /// Preserve old two-trace routing while adding the default CH 3/4 inputs.
    pub fn scope(self) -> ScopeChannels {
        let mut channels = ScopeChannels::default();
        channels.0[..2].copy_from_slice(&self.0);
        channels
    }
}

impl<const N: usize> Channels<N> {
    pub fn available(self, channels: usize) -> bool {
        self.0.into_iter().all(|id| available(id, channels))
    }

    /// All values come from this exact frame, without a channel fallback.
    pub fn values(self, frame: &[f64]) -> Option<[f64; N]> {
        self.available(frame.len())
            .then(|| self.0.map(|id| frame[id]))
    }
}
