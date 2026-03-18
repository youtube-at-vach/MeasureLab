import re

from src.core.version import __version__


def test_version():
    """Verify that __version__ is a string and follows semantic versioning."""
    assert isinstance(__version__, str), "__version__ must be a string"
    assert re.match(r"^\d+\.\d+\.\d+(?:[a-zA-Z0-9-.]+)?$", __version__), "__version__ must be a semantic version"
