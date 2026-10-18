//! Bounded, copyable card list. Only its occupied prefix crosses serialization.
use super::{Error, SIGNALS, Signal};

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Signals {
    entries: [Signal; SIGNALS],
    len: usize,
}

impl Signals {
    pub fn empty() -> Self {
        Self {
            entries: [Signal::default(); SIGNALS],
            len: 0,
        }
    }

    pub fn push(&mut self, signal: Signal) -> Result<(), Error> {
        if self.len == SIGNALS {
            return Err(Error::SignalCount);
        }
        self.entries[self.len] = signal;
        self.len += 1;
        Ok(())
    }

    pub fn remove(&mut self, index: usize) {
        self.entries.copy_within(index + 1..self.len, index);
        self.len -= 1;
        self.entries[self.len] = Signal::default();
    }
}

impl std::ops::Deref for Signals {
    type Target = [Signal];
    fn deref(&self) -> &Self::Target {
        &self.entries[..self.len]
    }
}
impl std::ops::DerefMut for Signals {
    fn deref_mut(&mut self) -> &mut Self::Target {
        &mut self.entries[..self.len]
    }
}
impl<'a> IntoIterator for &'a Signals {
    type Item = &'a Signal;
    type IntoIter = std::slice::Iter<'a, Signal>;
    fn into_iter(self) -> Self::IntoIter {
        self.iter()
    }
}
impl<'a> IntoIterator for &'a mut Signals {
    type Item = &'a mut Signal;
    type IntoIter = std::slice::IterMut<'a, Signal>;
    fn into_iter(self) -> Self::IntoIter {
        self.iter_mut()
    }
}
impl serde::Serialize for Signals {
    fn serialize<S: serde::Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        serde::Serialize::serialize(&**self, serializer)
    }
}
impl<'de> serde::Deserialize<'de> for Signals {
    fn deserialize<D: serde::Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        struct Visitor;
        impl<'de> serde::de::Visitor<'de> for Visitor {
            type Value = Signals;
            fn expecting(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
                f.write_str("at most 16 generator cards")
            }
            fn visit_seq<A: serde::de::SeqAccess<'de>>(
                self,
                mut seq: A,
            ) -> Result<Signals, A::Error> {
                let mut signals = Signals::empty();
                while let Some(mut signal) = seq.next_element::<Signal>()? {
                    // Legacy two-tone files have no ID or waveform fields.
                    if signal.id == 0 {
                        signal.id = signals.len as u64 + 1;
                    }
                    signals.push(signal).map_err(serde::de::Error::custom)?;
                }
                Ok(signals)
            }
        }
        deserializer.deserialize_seq(Visitor)
    }
}

/// Legacy results contain two clock entries; new results contain sixteen.
pub(crate) fn clock_array<'de, D, T>(deserializer: D) -> Result<[T; SIGNALS], D::Error>
where
    D: serde::Deserializer<'de>,
    T: serde::Deserialize<'de> + Default + Copy,
{
    struct Visitor<T>(std::marker::PhantomData<T>);
    impl<'de, T: serde::Deserialize<'de> + Default + Copy> serde::de::Visitor<'de> for Visitor<T> {
        type Value = [T; SIGNALS];
        fn expecting(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
            f.write_str("two legacy or sixteen generator clock entries")
        }
        fn visit_seq<A: serde::de::SeqAccess<'de>>(
            self,
            mut seq: A,
        ) -> Result<Self::Value, A::Error> {
            let mut result = [T::default(); SIGNALS];
            let mut len = 0;
            while let Some(value) = seq.next_element()? {
                if len == SIGNALS {
                    return Err(serde::de::Error::custom("too many generator clock entries"));
                }
                result[len] = value;
                len += 1;
            }
            if len != 2 && len != SIGNALS {
                return Err(serde::de::Error::custom(
                    "invalid generator clock array length",
                ));
            }
            Ok(result)
        }
    }
    deserializer.deserialize_seq(Visitor(std::marker::PhantomData))
}
