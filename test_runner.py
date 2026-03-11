import pytest
import sys
sys.path.insert(0, ".")
pytest.main(["-v", "tests/logic_verification/instruments/test_timecode_monitor_ltc.py"])
