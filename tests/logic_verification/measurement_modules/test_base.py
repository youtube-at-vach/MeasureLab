import unittest
from src.measurement_modules.base import MeasurementModule

class TestMeasurementModule(unittest.TestCase):
    """Tests for the MeasurementModule base class."""

    def test_abstract_instantiation(self):
        """Test that MeasurementModule cannot be instantiated directly."""
        with self.assertRaises(TypeError) as context:
            MeasurementModule()

        self.assertIn("Can't instantiate abstract class MeasurementModule", str(context.exception))

    def test_concrete_implementation(self):
        """Test that a valid concrete implementation can be instantiated."""

        class ValidModule(MeasurementModule):
            @property
            def name(self) -> str:
                return "Valid Module"

            @property
            def description(self) -> str:
                return "Valid Description"

        module = ValidModule()

        self.assertEqual(module.name, "Valid Module")
        self.assertEqual(module.description, "Valid Description")

    def test_get_widget_default(self):
        """Test that get_widget returns None by default."""
        class ValidModule(MeasurementModule):
            @property
            def name(self) -> str:
                return "Valid Module"

            @property
            def description(self) -> str:
                return "Valid Description"

        module = ValidModule()
        self.assertIsNone(module.get_widget())

if __name__ == '__main__':
    unittest.main()
