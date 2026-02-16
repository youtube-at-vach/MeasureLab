# GitHub Repository Information
GITHUB_REPO_OWNER = "youtube-at-vach"
GITHUB_REPO_NAME = "MeasureLab"
GITHUB_REPO_FULL_NAME = f"{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}"

# Update Check URL (used by UpdateChecker)
UPDATE_CHECK_URL = f"https://api.github.com/repos/{GITHUB_REPO_FULL_NAME}/releases/latest"

# Release Page URL Template (used by WelcomeWidget)
# Usage: RELEASE_PAGE_URL_TEMPLATE.format(tag=version_tag)
RELEASE_PAGE_URL_TEMPLATE = f"https://github.com/{GITHUB_REPO_FULL_NAME}/releases/tag/{{tag}}"
