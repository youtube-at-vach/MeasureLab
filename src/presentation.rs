//! Display state and navigation only. No acquisition, DSP or output commands.
use serde::{Deserialize, Serialize};

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum InstrumentId {
    Scope,
    Spectrum,
    Spectrogram,
    Xy,
    Lockin,
    Comparison,
    Generator,
}

impl InstrumentId {
    pub const ALL: [Self; 7] = [
        Self::Scope,
        Self::Spectrum,
        Self::Spectrogram,
        Self::Xy,
        Self::Lockin,
        Self::Comparison,
        Self::Generator,
    ];

    pub fn name(self) -> &'static str {
        match self {
            Self::Scope => "Scope",
            Self::Spectrum => "Spectrum",
            Self::Spectrogram => "Spectrogram",
            Self::Xy => "XY",
            Self::Lockin => "Lock-in",
            Self::Comparison => "Synchronous 2ch",
            Self::Generator => "Generator",
        }
    }

    pub fn purpose(self) -> &'static str {
        match self {
            Self::Scope => "Waveform over time",
            Self::Spectrum => "Frequency levels and power",
            Self::Spectrogram => "Frequency changes over time",
            Self::Xy => "Two-channel X/Y relationship",
            Self::Lockin => "Tone amplitude and phase vs REF",
            Self::Comparison => "REF / SIG gain, phase and delay",
            Self::Generator => "Generate signals on output channels",
        }
    }

    pub fn group(self) -> &'static str {
        match self {
            Self::Scope | Self::Spectrum | Self::Spectrogram | Self::Xy => "MONITOR",
            Self::Lockin | Self::Comparison => "ANALYSIS",
            Self::Generator => "SIGNAL",
        }
    }

    pub fn minimum_size(self) -> [f32; 2] {
        match self {
            Self::Comparison => [470.0, 640.0],
            Self::Generator => [420.0, 360.0],
            Self::Scope => [400.0, 390.0],
            Self::Lockin => [380.0, 420.0],
            _ => [380.0, 340.0],
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Screen {
    Single(InstrumentId),
    Console,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Layout {
    #[default]
    Columns,
    Rows,
    Grid,
    Tabs,
}

impl Layout {
    pub const ALL: [Self; 4] = [Self::Columns, Self::Rows, Self::Grid, Self::Tabs];
    pub fn name(self) -> &'static str {
        match self {
            Self::Columns => "Side by side",
            Self::Rows => "Stacked",
            Self::Grid => "2 × 2",
            Self::Tabs => "Tabs",
        }
    }
    pub fn capacity(self) -> usize {
        match self {
            Self::Grid => 4,
            Self::Columns | Self::Rows => 2,
            Self::Tabs => 1,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Console {
    pub instruments: Vec<InstrumentId>,
    pub selected: Option<InstrumentId>,
    #[serde(deserialize_with = "layout_or_tabs")]
    pub layout: Layout,
    #[serde(default = "half", deserialize_with = "split_or_invalid")]
    pub split: f32,
}
fn half() -> f32 {
    0.5
}

fn split_or_invalid<'de, D: serde::Deserializer<'de>>(deserializer: D) -> Result<f32, D::Error> {
    let value = serde_json::Value::deserialize(deserializer)?;
    Ok(serde_json::from_value(value).unwrap_or(f32::NAN))
}

fn layout_or_tabs<'de, D: serde::Deserializer<'de>>(deserializer: D) -> Result<Layout, D::Error> {
    let value = serde_json::Value::deserialize(deserializer)?;
    Ok(serde_json::from_value(value).unwrap_or(Layout::Tabs))
}

impl Default for Console {
    fn default() -> Self {
        Self {
            instruments: Vec::new(),
            selected: None,
            layout: Layout::Columns,
            split: 0.5,
        }
    }
}

impl Console {
    /// Outer pane dimensions, shared by fit checks and rendering. A final grid
    /// pane spans both columns; overflow keeps the selected instrument's group.
    pub fn pane_sizes(&self, layout: Layout, width: f32, height: f32, gap: f32) -> Vec<[f32; 2]> {
        let count = self.displayed(layout).len();
        let share = |first| if first { self.split } else { 1.0 - self.split };
        (0..count)
            .map(|index| match layout {
                Layout::Columns => [(width - gap) * share(index == 0), height],
                Layout::Rows => [width, (height - gap) * share(index == 0)],
                Layout::Grid => [
                    if count == 1 || (index == 2 && count == 3) {
                        width
                    } else {
                        (width - gap) * share(index % 2 == 0)
                    },
                    if count <= 2 {
                        height
                    } else {
                        (height - gap) * share(index < 2)
                    },
                ],
                Layout::Tabs => [width, height],
            })
            .collect()
    }

    pub fn effective_layout(&self, width: f32, height: f32, gap: f32) -> Layout {
        let panes = self.displayed(self.layout);
        if panes.len() < 2 || self.layout == Layout::Tabs {
            return Layout::Tabs;
        }
        let fits = panes
            .iter()
            .zip(self.pane_sizes(self.layout, width, height, gap))
            .all(|(i, [w, h])| {
                let [min_w, min_h] = i.minimum_size();
                w - PANE_CHROME[0] >= min_w && h - PANE_CHROME[1] >= min_h
            });
        if fits { self.layout } else { Layout::Tabs }
    }

    /// Overflow tabs switch the group containing the selected instrument.
    pub fn displayed(&self, layout: Layout) -> &[InstrumentId] {
        let capacity = layout.capacity();
        let index = self
            .selected
            .and_then(|i| self.instruments.iter().position(|p| *p == i))
            .unwrap_or(0);
        let start = index / capacity * capacity;
        &self.instruments
            [start.min(self.instruments.len())..(start + capacity).min(self.instruments.len())]
    }
}

/// Frame margins and the pane title/actions, outside the instrument itself.
pub const PANE_CHROME: [f32; 2] = [12.0, 40.0];

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Presentation {
    pub screen: Screen,
    pub console: Console,
    pub details_visible: bool,
}

impl Default for Presentation {
    fn default() -> Self {
        Self {
            screen: Screen::Single(InstrumentId::Scope),
            console: Console {
                split: 0.5,
                ..Console::default()
            },
            details_visible: true,
        }
    }
}

pub enum Action {
    OpenSingle(InstrumentId),
    OpenConsole,
    PairWith(InstrumentId),
    AddToConsole(InstrumentId),
    FocusPane(InstrumentId),
    RemoveFromConsole(InstrumentId),
    SetLayout(Layout),
}

impl Presentation {
    pub fn selected(&self) -> Option<InstrumentId> {
        match self.screen {
            Screen::Single(i) => Some(i),
            Screen::Console => self.console.selected,
        }
    }
    pub fn contains(&self, instrument: InstrumentId) -> bool {
        match self.screen {
            Screen::Single(i) => i == instrument,
            Screen::Console => self.console.instruments.contains(&instrument),
        }
    }
    pub fn apply(&mut self, action: Action) {
        match action {
            Action::OpenSingle(i) => self.screen = Screen::Single(i),
            Action::OpenConsole => self.screen = Screen::Console,
            Action::PairWith(i) => {
                if let Screen::Single(current) = self.screen {
                    if i == current {
                        return;
                    }
                    self.console = Console {
                        instruments: vec![current, i],
                        selected: Some(i),
                        layout: Layout::Columns,
                        split: 0.5,
                    };
                    self.screen = Screen::Console;
                }
            }
            Action::AddToConsole(i) => {
                if !self.console.instruments.contains(&i) {
                    self.console.instruments.push(i);
                }
                self.console.selected = Some(i);
                self.screen = Screen::Console;
            }
            Action::FocusPane(i) => {
                if self.console.instruments.contains(&i) {
                    self.console.selected = Some(i);
                }
            }
            Action::RemoveFromConsole(i) => {
                if let Some(index) = self.console.instruments.iter().position(|p| *p == i) {
                    self.console.instruments.remove(index);
                    if self.console.selected == Some(i) {
                        self.console.selected = self
                            .console
                            .instruments
                            .get(index.min(self.console.instruments.len().saturating_sub(1)))
                            .copied();
                    }
                }
            }
            Action::SetLayout(layout) => self.console.layout = layout,
        }
    }
    /// Repair display-only preferences without changing measurement conditions.
    pub fn repair(&mut self) {
        let mut unique = Vec::new();
        self.console.instruments.retain(|i| {
            if unique.contains(i) {
                false
            } else {
                unique.push(*i);
                true
            }
        });
        if self
            .console
            .selected
            .is_none_or(|i| !self.console.instruments.contains(&i))
        {
            self.console.selected = self.console.instruments.first().copied();
        }
        if !self.console.split.is_finite() || !(0.2..=0.8).contains(&self.console.split) {
            self.console.split = 0.5;
            self.console.layout = Layout::Tabs;
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn selection_pairing_and_return_preserve_console_and_never_toggle_off() {
        let mut p = Presentation::default();
        p.apply(Action::OpenSingle(InstrumentId::Spectrum));
        p.apply(Action::OpenSingle(InstrumentId::Spectrum));
        assert_eq!(p.screen, Screen::Single(InstrumentId::Spectrum));
        p.apply(Action::PairWith(InstrumentId::Generator));
        let saved = p.console.clone();
        p.apply(Action::OpenSingle(InstrumentId::Scope));
        p.apply(Action::OpenConsole);
        assert_eq!(p.console, saved);
        p.apply(Action::AddToConsole(InstrumentId::Generator));
        assert_eq!(p.console.instruments.len(), 2);
        p.apply(Action::RemoveFromConsole(InstrumentId::Generator));
        assert_eq!(p.selected(), Some(InstrumentId::Spectrum));
        p.apply(Action::RemoveFromConsole(InstrumentId::Spectrum));
        assert!(p.console.instruments.is_empty());
        assert_eq!(p.selected(), None);
    }
    #[test]
    fn overflow_and_narrow_layout_keep_the_requested_configuration() {
        let mut p = Presentation::default();
        for i in InstrumentId::ALL {
            p.apply(Action::AddToConsole(i));
        }
        p.apply(Action::SetLayout(Layout::Grid));
        let saved = p.clone();
        assert_eq!(p.console.effective_layout(700.0, 500.0, 6.0), Layout::Tabs);
        assert_eq!(
            p.console.displayed(Layout::Tabs),
            &[InstrumentId::Generator]
        );
        assert_eq!(
            p.console.effective_layout(1600.0, 1400.0, 6.0),
            Layout::Grid
        );
        assert_eq!(p.console.displayed(Layout::Grid).len(), 3);
        assert_eq!(p, saved);
    }

    #[test]
    fn asymmetric_panes_fit_only_when_every_instrument_has_its_minimum_space() {
        let mut p = Presentation::default();
        for i in [
            InstrumentId::Scope,
            InstrumentId::Spectrum,
            InstrumentId::Comparison,
        ] {
            p.apply(Action::AddToConsole(i));
        }
        p.console.split = 0.4;
        p.apply(Action::SetLayout(Layout::Grid));
        let saved = p.clone();
        let sizes = p.console.pane_sizes(Layout::Grid, 1100.0, 1180.0, 6.0);
        assert_eq!(sizes[2][0], 1100.0);
        assert_eq!(sizes[0][0] + sizes[1][0] + 6.0, 1100.0);
        assert_eq!(sizes[0][1] + sizes[2][1] + 6.0, 1180.0);
        assert_eq!(
            p.console.effective_layout(1100.0, 1180.0, 6.0),
            Layout::Grid
        );
        // Width alone fits, but the Comparison also needs room for three plots.
        assert_eq!(
            p.console.effective_layout(1100.0, 1000.0, 6.0),
            Layout::Tabs
        );
        assert_eq!(p.console.effective_layout(900.0, 1180.0, 6.0), Layout::Tabs);
        assert_eq!(p, saved);
    }
}
