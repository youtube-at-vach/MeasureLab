import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../')))

import sys
import pytest
from unittest.mock import MagicMock, patch

@pytest.fixture
def pid_controller_class():
    """
    Fixture to provide the PIDController class with mocked dependencies.
    Patches sys.modules to mock external dependencies like numpy and PyQt6
    before importing the module under test.
    """
    # Create a mock for numpy that has a bool_ type so isinstance works
    mock_numpy = MagicMock()
    mock_numpy.bool_ = bool

    modules_to_patch = {
        "numpy": mock_numpy,
        "pyqtgraph": MagicMock(),
        "PyQt6": MagicMock(),
        "PyQt6.QtCore": MagicMock(),
        "PyQt6.QtWidgets": MagicMock(),
        "src.core.audio_engine": MagicMock(),
        "src.core.localization": MagicMock(),
        "src.measurement_modules.base": MagicMock(),
    }

    with patch.dict(sys.modules, modules_to_patch):
        # If the module is already imported, remove it so it gets re-imported with mocks
        if "src.gui.widgets.lock_in_frequency_counter" in sys.modules:
            del sys.modules["src.gui.widgets.lock_in_frequency_counter"]

        from src.gui.widgets.lock_in_frequency_counter import PIDController
        yield PIDController

        # Cleanup: Remove the module from sys.modules to avoid pollution
        if "src.gui.widgets.lock_in_frequency_counter" in sys.modules:
            del sys.modules["src.gui.widgets.lock_in_frequency_counter"]

class TestPIDController:
    """Test suite for the PIDController class."""

    def test_initialization_defaults(self, pid_controller_class):
        """Verify default parameters and initial state."""
        pid = pid_controller_class()
        assert pid.kp == 0.5
        assert pid.ki == 0.2
        assert pid.kd == 0.0
        assert pid.prev_error == 0.0
        assert pid.integral == 0.0

    def test_initialization_custom(self, pid_controller_class):
        """Verify initialization with custom parameters."""
        pid = pid_controller_class(kp=1.0, ki=0.5, kd=0.1)
        assert pid.kp == 1.0
        assert pid.ki == 0.5
        assert pid.kd == 0.1
        assert pid.prev_error == 0.0
        assert pid.integral == 0.0

    def test_reset(self, pid_controller_class):
        """Verify reset clears state variables."""
        pid = pid_controller_class()
        pid.prev_error = 10.0
        pid.integral = 5.0
        pid.reset()
        assert pid.prev_error == 0.0
        assert pid.integral == 0.0

    def test_proportional_control(self, pid_controller_class):
        """Verify proportional term calculation."""
        pid = pid_controller_class(kp=2.0, ki=0.0, kd=0.0)
        output = pid.update(error=1.5, dt=0.1)
        # P = Kp * error = 2.0 * 1.5 = 3.0
        assert output == 3.0
        # Verify state update
        assert pid.prev_error == 1.5

    def test_integral_control(self, pid_controller_class):
        """Verify integral term accumulation."""
        pid = pid_controller_class(kp=0.0, ki=0.5, kd=0.0)

        # First update
        # Integral += error * dt = 2.0 * 0.1 = 0.2
        # I = Ki * Integral = 0.5 * 0.2 = 0.1
        output1 = pid.update(error=2.0, dt=0.1)
        assert output1 == pytest.approx(0.1)
        assert pid.integral == pytest.approx(0.2)

        # Second update
        # Integral += error * dt = 0.2 + (1.0 * 0.1) = 0.3
        # I = Ki * Integral = 0.5 * 0.3 = 0.15
        output2 = pid.update(error=1.0, dt=0.1)
        assert output2 == pytest.approx(0.15)
        assert pid.integral == pytest.approx(0.3)

    def test_derivative_control(self, pid_controller_class):
        """Verify derivative term calculation."""
        pid = pid_controller_class(kp=0.0, ki=0.0, kd=0.1)

        # First update (prev_error is 0.0)
        # Derivative = (error - prev_error) / dt = (1.0 - 0.0) / 0.1 = 10.0
        # D = Kd * Derivative = 0.1 * 10.0 = 1.0
        output1 = pid.update(error=1.0, dt=0.1)
        assert output1 == pytest.approx(1.0)
        assert pid.prev_error == 1.0

        # Second update
        # Derivative = (2.0 - 1.0) / 0.1 = 10.0
        # D = Kd * Derivative = 0.1 * 10.0 = 1.0
        output2 = pid.update(error=2.0, dt=0.1)
        assert output2 == pytest.approx(1.0)
        assert pid.prev_error == 2.0

        # Third update (constant error -> zero derivative)
        # Derivative = (2.0 - 2.0) / 0.1 = 0.0
        output3 = pid.update(error=2.0, dt=0.1)
        assert output3 == 0.0

    def test_dt_zero_or_negative(self, pid_controller_class):
        """Verify behavior when dt <= 0."""
        pid = pid_controller_class(kp=1.0, ki=1.0, kd=1.0)

        # dt = 0
        output = pid.update(error=1.0, dt=0.0)
        assert output == 0.0
        # State should not change
        assert pid.prev_error == 0.0
        assert pid.integral == 0.0

        # dt < 0
        output = pid.update(error=1.0, dt=-0.1)
        assert output == 0.0
        assert pid.prev_error == 0.0
        assert pid.integral == 0.0

    def test_combined_response(self, pid_controller_class):
        """Verify combined P, I, D response."""
        pid = pid_controller_class(kp=1.0, ki=0.5, kd=0.1)

        # Error step 0 -> 1.0, dt=0.1
        # P = 1.0 * 1.0 = 1.0
        # Integral += 1.0 * 0.1 = 0.1
        # I = 0.5 * 0.1 = 0.05
        # Derivative = (1.0 - 0.0) / 0.1 = 10.0
        # D = 0.1 * 10.0 = 1.0
        # Total = 1.0 + 0.05 + 1.0 = 2.05
        output = pid.update(error=1.0, dt=0.1)
        assert output == pytest.approx(2.05)
