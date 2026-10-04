//! Bounded STFT history and sample-clock coordinates, independent of GUI/GPU.
//! dBFS is display data; raw samples and FFT calculations remain elsewhere.
use crate::stft::{Config, RowInfo};

pub const ROWS: usize = 512;
// Pack all 16,385 bins into <= 5 scanlines, below default GPU size limits.
pub const TEXTURE_WIDTH: usize = 4096;

#[derive(Clone, Copy, Debug)]
pub struct Placement {
    /// None marks a missing interval between two known window-end timestamps.
    pub slot: Option<usize>,
    pub top: f32,
    pub bottom: f32,
}

pub struct History {
    config: Option<Config>,
    generation: u64,
    rows: Vec<Option<RowInfo>>,
    db: Vec<f32>,
    versions: Vec<u64>,
    next: usize,
    len: usize,
    revision: u64,
}

impl Default for History {
    fn default() -> Self {
        Self {
            config: None,
            generation: 0,
            rows: vec![None; ROWS],
            db: Vec::new(),
            versions: vec![0; ROWS],
            next: 0,
            len: 0,
            revision: 0,
        }
    }
}

impl History {
    pub fn reset(&mut self, generation: u64, config: Config) {
        config.validate().expect("valid STFT configuration");
        self.config = Some(config);
        self.generation = generation;
        let stride = (config.size / 2 + 1).div_ceil(TEXTURE_WIDTH) * TEXTURE_WIDTH;
        self.db.resize(stride * ROWS, 0.0);
        self.rows.fill(None);
        self.next = 0;
        self.len = 0;
        self.revision = self.revision.wrapping_add(1);
        self.versions.fill(self.revision);
    }

    pub fn push(&mut self, info: RowInfo, db: &[f32]) -> bool {
        if self.config != Some(info.config)
            || self.generation != info.generation
            || db.len() != info.config.size / 2 + 1
            || info.end.checked_sub(info.start) != Some(info.config.size as u64)
            || self
                .latest()
                .is_some_and(|previous| info.end <= previous.end)
        {
            return false;
        }
        let offset = self.next * self.stride();
        self.db[offset..offset + db.len()].copy_from_slice(db);
        self.rows[self.next] = Some(info);
        self.revision = self.revision.wrapping_add(1);
        self.versions[self.next] = self.revision;
        self.next = (self.next + 1) % ROWS;
        self.len = (self.len + 1).min(ROWS);
        true
    }

    pub fn config(&self) -> Option<Config> {
        self.config
    }
    pub fn revision(&self) -> u64 {
        self.revision
    }
    pub fn len(&self) -> usize {
        self.len
    }
    pub fn is_empty(&self) -> bool {
        self.len == 0
    }
    pub fn stride(&self) -> usize {
        self.db.len() / ROWS
    }
    pub fn version(&self, slot: usize) -> u64 {
        self.versions[slot]
    }
    pub fn row(&self, slot: usize) -> Option<(RowInfo, &[f32])> {
        self.rows[slot].map(|info| {
            let offset = slot * self.stride();
            (info, &self.db[offset..offset + self.stride()])
        })
    }
    pub fn latest(&self) -> Option<RowInfo> {
        self.rows[(self.next + ROWS - 1) % ROWS]
    }
    pub fn retained_seconds(&self) -> f64 {
        let Some(latest) = self.latest() else {
            return 0.0;
        };
        let oldest = self.rows[(self.next + ROWS - self.len) % ROWS].unwrap();
        (latest.end - oldest.end + latest.config.hop as u64) as f64
            / latest.config.sample_rate as f64
    }
    pub fn storage_bytes(&self) -> usize {
        self.db.capacity() * std::mem::size_of::<f32>()
    }

    /// Newest at top; each row occupies one hop ending at its window end.
    /// Integer subtraction happens before float conversion, even past 2^53.
    /// Missing input/result intervals stay at their source-time positions.
    pub fn placements(&self, seconds: f64, output: &mut Vec<Placement>) {
        output.clear();
        let Some(latest) = self.latest() else { return };
        if !seconds.is_finite() || seconds <= 0.0 {
            return;
        }
        let scale = latest.config.sample_rate as f64 * seconds;
        let mut previous = None;
        for index in 0..self.len {
            let slot = (self.next + ROWS - self.len + index) % ROWS;
            let info = self.rows[slot].unwrap();
            let start = info.end.saturating_sub(info.config.hop as u64);
            let top = (latest.end - info.end) as f64 / scale;
            let bottom = (latest.end - start) as f64 / scale;
            if top < 1.0 {
                output.push(Placement {
                    slot: Some(slot),
                    top: top as f32,
                    bottom: bottom.min(1.0) as f32,
                });
            }
            // A loss before the first delivered row is also known from metadata.
            // Include the partial-window warm-up after an input discontinuity.
            let preceding = previous.or_else(|| {
                if info.gap.input_frames > 0 {
                    Some(info.start.saturating_sub(info.gap.input_frames))
                } else if info.gap.result_rows > 0 {
                    Some(start.saturating_sub(
                        info.gap.result_rows.saturating_mul(info.config.hop as u64),
                    ))
                } else {
                    None
                }
            });
            if let Some(end) = preceding
                && end < start
            {
                let gap_bottom = (latest.end - end) as f64 / scale;
                if bottom < 1.0 {
                    output.push(Placement {
                        slot: None,
                        top: bottom as f32,
                        bottom: gap_bottom.min(1.0) as f32,
                    });
                }
            }
            previous = Some(info.end);
        }
    }

    /// Return the analyzed window at this age, or None for missing/unretained data.
    pub fn at_age(&self, age_seconds: f64) -> Option<(RowInfo, &[f32])> {
        let latest = self.latest()?;
        if !age_seconds.is_finite() || age_seconds < 0.0 {
            return None;
        }
        let age = age_seconds * latest.config.sample_rate as f64;
        for index in 0..self.len {
            let slot = (self.next + ROWS - 1 - index) % ROWS;
            let (info, db) = self.row(slot)?;
            let top = (latest.end - info.end) as f64;
            if age >= top && age < top + info.config.hop as f64 {
                return Some((info, &db[..info.config.size / 2 + 1]));
            }
        }
        None
    }

    /// Match the displayed hop interval, rather than any overlapping FFT
    /// window. Missing rows must not borrow a measurement from a neighbour.
    pub fn at_sample(&self, sample: u64) -> Option<(RowInfo, &[f32])> {
        for index in 0..self.len {
            let slot = (self.next + ROWS - 1 - index) % ROWS;
            let (info, db) = self.row(slot)?;
            if (info.end.saturating_sub(info.config.hop as u64)..info.end).contains(&sample) {
                return Some((info, &db[..info.config.size / 2 + 1]));
            }
        }
        None
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{spectrum::Window, stft::Gap};

    #[test]
    fn sample_cursor_matches_displayed_hops_and_never_reads_overlapping_gap_windows() {
        let mut h = History::default();
        h.reset(1, config());
        let origin = 1_u64 << 54;
        let mut db = vec![-80.0; 513];
        for (end, value) in [
            (origin + 1024, -10.0),
            (origin + 1280, -20.0),
            (origin + 2304, -30.0),
        ] {
            db[32] = value;
            assert!(h.push(info(end), &db));
        }
        assert_eq!(h.at_sample(origin + 1023).unwrap().1[32], -10.0);
        assert_eq!(h.at_sample(origin + 1024).unwrap().1[32], -20.0);
        // The last FFT covers this sample, but its displayed row does not.
        assert!(h.at_sample(origin + 1500).is_none());
        assert_eq!(h.at_sample(origin + 2303).unwrap().1[32], -30.0);
        assert!(h.at_sample(origin + 2304).is_none());
        assert!(h.at_sample(origin + 767).is_none());
    }
    fn config() -> Config {
        Config {
            sample_rate: 48000,
            channels: 16,
            channel: 15,
            size: 1024,
            hop: 256,
            window: Window::Hann,
            remove_dc: true,
            precision: crate::spectrum::Precision::F64,
        }
    }
    fn info(end: u64) -> RowInfo {
        RowInfo {
            generation: 1,
            config: config(),
            start: end - 1024,
            end,
            gap: Gap::default(),
        }
    }
    #[test]
    fn wrap_keeps_source_time_bins_and_fixed_storage() {
        let mut h = History::default();
        h.reset(1, config());
        let bytes = h.storage_bytes();
        let mut db = vec![0.0; 513];
        let origin = (1_u64 << 54) + 1024;
        for i in 0..ROWS * 3 {
            db[32] = i as f32;
            assert!(h.push(info(origin + i as u64 * 256), &db));
        }
        assert_eq!(h.len(), ROWS);
        assert_eq!(h.storage_bytes(), bytes);
        assert_eq!(h.at_age(0.0).unwrap().1[32], (ROWS * 3 - 1) as f32);
        assert_eq!(
            h.at_age(256.0 / 48000.0).unwrap().1[32],
            (ROWS * 3 - 2) as f32
        );
        let mut placements = Vec::new();
        h.placements(ROWS as f64 * 256.0 / 48000.0, &mut placements);
        assert_eq!(placements.len(), ROWS);
        assert_eq!(placements.last().unwrap().top, 0.0);
        assert!((placements[0].bottom - 1.0).abs() < 1e-6);
    }
    #[test]
    fn gaps_are_not_compressed_or_connected_and_old_epochs_are_rejected() {
        let mut h = History::default();
        h.reset(1, config());
        let db = vec![-80.0; 513];
        for end in [1024, 1280, 2304, 4096] {
            let mut row = info(end);
            row.gap.result_rows = if end == 2304 { 3 } else { 0 };
            row.gap.input_frames = if end == 4096 { 768 } else { 0 };
            assert!(h.push(row, &db));
        }
        let mut placements = Vec::new();
        h.placements(4096.0 / 48000.0, &mut placements);
        assert_eq!(placements.iter().filter(|p| p.slot.is_none()).count(), 2);
        assert!(h.at_age(512.0 / 48000.0).is_none());
        assert!(h.at_age(0.0).is_some());
        assert!(!h.push(info(4096), &db));
        h.reset(
            2,
            Config {
                sample_rate: 96000,
                channel: 0,
                ..config()
            },
        );
        assert!(!h.push(info(4352), &db));
        assert!(h.is_empty());
    }
    #[test]
    fn largest_fft_keeps_nyquist_in_packed_texture() {
        let cfg = Config {
            size: 32768,
            hop: 8192,
            ..config()
        };
        let mut h = History::default();
        h.reset(1, cfg);
        let mut db = vec![-180.0; 16385];
        db[16384] = -6.0206;
        assert!(h.push(
            RowInfo {
                config: cfg,
                start: 0,
                end: 32768,
                ..info(32768)
            },
            &db
        ));
        assert_eq!(h.stride(), TEXTURE_WIDTH * 5);
        assert_eq!(h.at_age(0.0).unwrap().1[16384], -6.0206);
    }

    #[test]
    fn loss_before_first_delivered_row_is_visible() {
        let mut h = History::default();
        h.reset(1, config());
        let mut row = info(4096);
        row.gap.result_rows = 2;
        assert!(h.push(row, &vec![-80.0; 513]));
        let mut placements = Vec::new();
        h.placements(1024.0 / 48000.0, &mut placements);
        assert_eq!(placements.len(), 2);
        assert_eq!(placements[1].slot, None);
        assert_eq!(placements[1].top, 0.25);
        assert_eq!(placements[1].bottom, 0.75);
    }
}
