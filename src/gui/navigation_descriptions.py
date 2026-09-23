"""Short task descriptions shared by the welcome page and navigation."""

from src.core.localization import tr


PAGE_DESCRIPTIONS = {
    "Settings": "Choose your input and output devices.",
    "Remote Audio I/O": "Use audio from another MeasureLab computer.",
    "Signal Generator": "Generate a test tone.",
    "Spectrum Analyzer": "See which frequencies are present.",
    "Oscilloscope": "Inspect the waveform over time.",
    "Distortion Analyzer": "Measure harmonic distortion.",
}


def translated_page_descriptions() -> dict[str, str]:
    """Keep literal tr() calls visible to the translation-key checker."""
    return {
        "Settings": tr("Choose your input and output devices."),
        "Remote Audio I/O": tr("Use audio from another MeasureLab computer."),
        "Signal Generator": tr("Generate a test tone."),
        "Spectrum Analyzer": tr("See which frequencies are present."),
        "Oscilloscope": tr("Inspect the waveform over time."),
        "Distortion Analyzer": tr("Measure harmonic distortion."),
    }
