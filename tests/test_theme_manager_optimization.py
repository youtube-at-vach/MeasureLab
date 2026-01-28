
from unittest.mock import MagicMock, patch
from src.core.theme_manager import ThemeManager

def test_theme_manager_caches_styles():
    mock_app = MagicMock()
    mock_app.style.return_value.objectName.return_value = "Windows"
    mock_app.styleHints.return_value = MagicMock()

    # Mock QStyleFactory.keys to return a fixed list so we are consistent
    with patch('PyQt6.QtWidgets.QStyleFactory.keys', return_value=['Windows', 'Fusion', 'Macintosh']) as mock_keys:

        # Instantiate ThemeManager
        manager = ThemeManager(mock_app)

        # PRE-OPTIMIZATION CHECK (This part will fail/pass depending on implementation state)
        # If optimization is implemented:
        # mock_keys.assert_called_once()

        # Reset mock to track subsequent calls clearly
        mock_keys.reset_mock()

        # Trigger _ensure_fusion_style_on_windows
        # We need to ensure we are on Windows for the method to proceed
        with patch('platform.system', return_value='Windows'):
            # Force current style to NOT be Fusion
            mock_app.style.return_value.objectName.return_value = "Windows"

            manager._ensure_fusion_style_on_windows()

        # Trigger _restore_platform_style_if_needed
        with patch('platform.system', return_value='Windows'):
            # We need original style name to be set
            manager._original_style_name = "Windows"
            # We need current style to be Fusion
            mock_app.style.return_value.objectName.return_value = "Fusion"

            manager._restore_platform_style_if_needed()

        # ASSERTION
        # With optimization, mock_keys should NOT have been called in these methods
        # (because it was cached in __init__, which we reset above).
        # Without optimization, it would be called twice (once for each method).

        assert mock_keys.call_count == 0, f"QStyleFactory.keys() was called {mock_keys.call_count} times, expected 0 (cached)"

def test_theme_manager_init_calls_keys():
    """Test that __init__ populates the cache."""
    mock_app = MagicMock()

    with patch('PyQt6.QtWidgets.QStyleFactory.keys', return_value=['Windows', 'Fusion']) as mock_keys:
        manager = ThemeManager(mock_app)

        # Verify it was called during init
        mock_keys.assert_called_once()

        # Verify cache is populated (accessing private member for testing)
        assert hasattr(manager, '_available_styles')
        assert 'fusion' in manager._available_styles
        assert manager._available_styles['fusion'] == 'Fusion'
