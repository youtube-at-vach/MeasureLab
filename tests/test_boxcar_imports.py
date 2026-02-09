
import sys
from PyQt6.QtWidgets import QApplication

# Mock QApplication to avoid "QWidget: Must construct a QApplication before a QWidget"
app = QApplication(sys.argv)


def test_imports_exist():
    """Verify that QFileDialog and QMessageBox are available in the module namespace."""
    import src.gui.widgets.boxcar_averager as module
    assert hasattr(module, 'QFileDialog')
    assert hasattr(module, 'QMessageBox')
    print("Imports verified.")

if __name__ == "__main__":
    test_imports_exist()
