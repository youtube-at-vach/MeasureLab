import os
import re
import sys


def extract_changelog(version, changelog_path="CHANGELOG.md"):
    """
    Extracts the changelog section for a specific version.

    Accepts headers like:
      ## [v0.1.3] - 2025-11-27
      ## v0.1.3
      ## [0.1.3]
      ## 0.1.3 - yyyy-mm-dd
    """
    # Normalize whitespace; keep original for fallback attempts
    original_version = version.strip()

    if not os.path.exists(changelog_path):
        print(f"Error: {changelog_path} not found.", file=sys.stderr)
        return None

    try:
        with open(changelog_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        print(f"Error reading {changelog_path}: {e}", file=sys.stderr)
        return None

    # Try both tag-style and plain versions without falling back for normal headers.
    v_stripped = original_version.lstrip("vV")
    candidates = list(dict.fromkeys([original_version, v_stripped, "v" + v_stripped]))

    # Build a flexible regex that allows:
    #  - optional brackets [ ... ] around version
    #  - optional whitespace between ## and version
    #  - versions with or without a 'v' prefix through the candidates above
    #  - consume header line (which may include date) then capture until next "## " or EOF
    pattern_template = r"^##[ \t]*\[?[ \t]*{ver}(?![\w.])[ \t]*\]?[^\n]*\n(.*?)(?=^##[ \t]|\Z)"

    for cand in candidates:
        pat = pattern_template.format(ver=re.escape(cand))
        pattern = re.compile(pat, re.MULTILINE | re.DOTALL | re.IGNORECASE)
        match = pattern.search(content)
        if match:
            return match.group(1).strip()

    # as a last resort, try a looser search: header that contains the version anywhere on the header line
    loose_pattern = re.compile(
        r"^##[^\n]*(?<![\w.])v?" + re.escape(v_stripped) + r"(?![\w.])[^\n]*\n(.*?)(?=^##[ \t]|\Z)",
        re.MULTILINE | re.DOTALL | re.IGNORECASE,
    )
    loose_match = loose_pattern.search(content)
    if loose_match:
        return loose_match.group(1).strip()

    return None


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python extract_changelog.py <version> [changelog_path]", file=sys.stderr)
        sys.exit(1)

    version = sys.argv[1]
    changelog_path = sys.argv[2] if len(sys.argv) > 2 else "CHANGELOG.md"

    content = extract_changelog(version, changelog_path)

    if content:
        # Ensure UTF-8 output on Windows
        if sys.platform == "win32":
            import io

            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
        print(content)
    else:
        # no output (workflow can detect empty)
        pass
