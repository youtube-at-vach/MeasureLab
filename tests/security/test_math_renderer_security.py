import pytest
from unittest.mock import patch, mock_open

pytest.importorskip("mkdocs")

from mkdocs.structure.pages import Page
from mkdocs.structure.files import File
from mkdocs.config.defaults import MkDocsConfig
import docs.hooks.render_math as render_math

# A valid dummy hash for testing
DUMMY_HASH = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"  # SHA-256 of empty string


@pytest.fixture
def dummy_page():
    file = File(path="index.md", src_dir="docs", dest_dir="site", use_directory_urls=False)
    page = Page(title="Test", file=file, config=MkDocsConfig())
    return page


@pytest.fixture
def dummy_config():
    config = MkDocsConfig()
    config["docs_dir"] = "docs"
    return config


def test_math_renderer_hash_mismatch(dummy_page, dummy_config):
    html_input = '<span class="arithmatex">\\( 1+1 \\)</span>'

    # We simulate reading a file that hashes to DUMMY_HASH
    # It won't match EXPECTED_KATEX_HASH
    m = mock_open(read_data=b"")

    with patch("os.path.exists", return_value=True):
        with patch("builtins.open", m):
            with patch("docs.hooks.render_math.EXPECTED_KATEX_HASH", "some_other_hash"):
                result = render_math.on_page_content(html_input, dummy_page, dummy_config)

    # Since the hash mismatches, the original HTML should be returned
    assert result == html_input


def test_math_renderer_hash_match(dummy_page, dummy_config):
    html_input = '<span class="arithmatex">\\( 1+1 \\)</span>'

    # Empty string bytes has hash e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
    m = mock_open(read_data=b"")

    # We patch MiniRacer to prevent actual JS evaluation issues in tests
    with patch("os.path.exists", return_value=True):
        with patch("builtins.open", m):
            with patch("docs.hooks.render_math.EXPECTED_KATEX_HASH", DUMMY_HASH):
                with patch("docs.hooks.render_math.MiniRacer") as mock_racer:
                    mock_racer_instance = mock_racer.return_value
                    # We expect `ctx.call` to return the modified HTML for the math block
                    mock_racer_instance.call.return_value = "rendered_math"

                    result = render_math.on_page_content(html_input, dummy_page, dummy_config)

    # It should have called the replace logic, since the hash matched
    assert result == "rendered_math"


def test_math_renderer_memory_limit_set(dummy_page, dummy_config):
    html_input = '<span class="arithmatex">\\( 1+1 \\)</span>'

    m = mock_open(read_data=b"")

    with patch("os.path.exists", return_value=True):
        with patch("builtins.open", m):
            with patch("docs.hooks.render_math.EXPECTED_KATEX_HASH", DUMMY_HASH):
                with patch("docs.hooks.render_math.MiniRacer") as mock_racer:
                    mock_racer_instance = mock_racer.return_value
                    mock_racer_instance.call.return_value = "rendered_math"

                    render_math.on_page_content(html_input, dummy_page, dummy_config)

                    # Verify memory limit was called
                    mock_racer_instance.set_hard_memory_limit.assert_called_once_with(50 * 1024 * 1024)
