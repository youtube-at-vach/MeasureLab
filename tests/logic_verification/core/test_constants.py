from src.core.constants import (
    GITHUB_REPO_OWNER,
    GITHUB_REPO_NAME,
    GITHUB_REPO_FULL_NAME,
    UPDATE_CHECK_URL,
    RELEASE_PAGE_URL_TEMPLATE
)

def test_github_repo_info():
    assert GITHUB_REPO_OWNER == "youtube-at-vach"
    assert GITHUB_REPO_NAME == "MeasureLab"
    assert GITHUB_REPO_FULL_NAME == f"{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}"

def test_update_check_url():
    expected_url = f"https://raw.githubusercontent.com/{GITHUB_REPO_FULL_NAME}/main/version.json"
    assert UPDATE_CHECK_URL == expected_url

def test_release_page_url_template():
    tag = "v1.0.0"
    formatted_url = RELEASE_PAGE_URL_TEMPLATE.format(tag=tag)
    expected_url = f"https://github.com/{GITHUB_REPO_FULL_NAME}/releases/tag/{tag}"
    assert formatted_url == expected_url
