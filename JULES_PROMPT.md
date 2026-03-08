# Handoff to Jules: Power Noise Sonification for Lock-in Spectrum Finder

## Context
We are implementing a "Sonification" feature for the Lock-in Spectrum Finder module. This feature will convert detected spectral peaks and scan results into audible sound.

- **GitHub Issue**: #873
- **Implementation Plan**: [implementation_plan.md](file:///home/hotstaff/.gemini/antigravity/brain/396cb133-fcc6-44f6-9a7a-e72ff13f24d9/implementation_plan.md)
- **Task List**: [task.md](file:///home/hotstaff/.gemini/antigravity/brain/396cb133-fcc6-44f6-9a7a-e72ff13f24d9/task.md)

## Requirements
- **Separate Tab**: The UI for sonification settings must be in a dedicated tab (e.g., "Audio Sonification").
- **Sonification Logic**: The user has left the specific implementation of how noise is represented as sound to the developer's discretion. The current plan suggests three modes:
    1. **Level Monitor**: Fixed pitch beep whose volume follows the signal level.
    2. **Frequency Mapping**: Sine wave pitch following the scan frequency.
    3. **Manual Tuner**: Continuous monitoring at a specific frequency.
- **Audio Precision**: Use the existing `AudioEngine` callback system. Ensure low latency and no glitches during scans.
- **Localization**: Implement translations via `tr()` and update language files.

## Technical Details
- Core files to modify/created:
    - `src/core/sonifier.py` [NEW]
    - `src/gui/widgets/lockin_spectrum_finder.py` [MODIFY]
    - `src/assets/lang/*.json` [MODIFY]

## Goal
Implement the full feature as described in the implementation plan and verify through tests and manual checks.

---
🚀 Powered by Antigravity Jules Bridge
