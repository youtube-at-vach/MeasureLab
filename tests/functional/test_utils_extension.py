import unittest
from src.core.utils import ensure_extension

class TestEnsureExtension(unittest.TestCase):
    def test_basic_append(self):
        # Basic case: append extension
        self.assertEqual(ensure_extension("test", "WAV Files (*.wav)"), "test.wav")

    def test_already_has_extension(self):
        # Extension exists and matches
        self.assertEqual(ensure_extension("test.wav", "WAV Files (*.wav)"), "test.wav")

    def test_wrong_extension(self):
        # Extension exists but does not match -> append default
        self.assertEqual(ensure_extension("test.mp3", "WAV Files (*.wav)"), "test.mp3.wav")

    def test_multiple_extensions_default(self):
        # multiple allowed, none present -> use first
        self.assertEqual(ensure_extension("test", "Audio (*.wav *.mp3)"), "test.wav")

    def test_multiple_extensions_match_secondary(self):
        # multiple allowed, secondary present -> keep
        self.assertEqual(ensure_extension("test.mp3", "Audio (*.wav *.mp3)"), "test.mp3")

    def test_case_insensitivity(self):
        self.assertEqual(ensure_extension("test.WAV", "WAV (*.wav)"), "test.WAV")

    def test_all_files(self):
        self.assertEqual(ensure_extension("test", "All Files (*)"), "test")
        self.assertEqual(ensure_extension("test.txt", "All Files (*)"), "test.txt")

    def test_complex_filter_string(self):
        # Qt filter string with ;;
        # Usually QFileDialog returns ONE selected filter string, not the whole list.
        # But ensure_extension takes 'selected_filter'.
        self.assertEqual(ensure_extension("test", "JSON Files (*.json)"), "test.json")

    def test_no_filter(self):
        self.assertEqual(ensure_extension("test", ""), "test")
        self.assertEqual(ensure_extension("test", None), "test")

    def test_path_traversal_behavior(self):
        # It should just work on the string end
        self.assertEqual(ensure_extension("/tmp/test", "WAV (*.wav)"), "/tmp/test.wav")
