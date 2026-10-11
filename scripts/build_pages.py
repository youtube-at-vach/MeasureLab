"""Build one Pages tree without replacing the final Python manual's URLs."""

import json
from html.parser import HTMLParser
from pathlib import Path
import shutil
import subprocess
import sys
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parent.parent


class PageLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        self.urls.extend(attributes[key] for key in ("href", "src") if key in attributes)


def verify_local_links(site):
    for page in site.rglob("*.html"):
        parser = PageLinks()
        parser.feed(page.read_text(encoding="utf-8"))
        for link in parser.urls:
            url = urlsplit(link)
            if url.scheme or url.netloc or not url.path:
                continue
            path = unquote(url.path)
            target = site / path.removeprefix("/MeasureLab/") if path.startswith("/MeasureLab/") else page.parent / path
            if target.is_dir():
                target /= "index.html"
            if not target.is_file():
                raise SystemExit(f"Broken local URL in {page.relative_to(site)}: {link}")


def main():
    npm = shutil.which("npm")
    if npm is None:
        raise SystemExit("npm is required; activate .tools/env.sh or install Node.js.")
    # MkDocs cleans its output directory. Build the root first, then its children.
    subprocess.run([sys.executable, "-m", "mkdocs", "build", "--strict"], cwd=ROOT, check=True)
    subprocess.run(
        [sys.executable, "-m", "mkdocs", "build", "--strict", "--config-file", "mkdocs-rust.yml"],
        cwd=ROOT,
        check=True,
    )
    # Fixed repository command; npm is resolved from the developer's toolchain PATH.
    subprocess.run([npm, "--prefix", "download-site", "run", "build"], cwd=ROOT, check=True)  # noqa: S603
    site = ROOT / "site"
    shutil.copytree(ROOT / "download-site/dist", site / "download")
    shutil.copy2(ROOT / "version.json", site / "version.json")
    (site / ".nojekyll").touch()

    # Every legacy page remains at its current route in both languages, including
    # pages that use the i18n plugin's fallback rather than a translated source.
    for source in (ROOT / "docs").rglob("*.md"):
        relative = source.relative_to(ROOT / "docs")
        if relative.name.endswith(".en.md"):
            continue
        route = relative.with_suffix("")
        if route.name == "index":
            route = route.parent
        for prefix in ("", "en"):
            output = site / prefix / route / "index.html"
            if not output.is_file():
                raise SystemExit(f"Missing legacy manual page: {output.relative_to(site)}")

    # Also verify key entry points, shared assets and the separate Rust search.
    for route in (
        "index.html",
        "en/index.html",
        "quickstart/index.html",
        "en/quickstart/index.html",
        "widgets/oscilloscope/index.html",
        "en/widgets/oscilloscope/index.html",
        "assets/welcome.png",
        "assets/js/katex.min.js",
        "search/search_index.json",
        "rust/index.html",
        "rust/en/index.html",
        "rust/quickstart/index.html",
        "rust/en/quickstart/index.html",
        "rust/search/search_index.json",
        "download/index.html",
        "download/favicon.png",
        "version.json",
    ):
        if not (site / route).is_file():
            raise SystemExit(f"Missing published route: {route}")
    for route in ("widgets/oscilloscope/index.html", "en/widgets/oscilloscope/index.html"):
        if "Python v0.9.1" not in (site / route).read_text(encoding="utf-8"):
            raise SystemExit(f"Missing Python edition label: {route}")
    source_version = json.loads((ROOT / "version.json").read_text(encoding="utf-8"))
    if json.loads((site / "version.json").read_text(encoding="utf-8")) != source_version:
        raise SystemExit("Published download version differs from version.json")
    verify_local_links(site)
    print("Pages ready: Python manual at /, Rust manual at /rust/, downloads at /download/.")


if __name__ == "__main__":
    main()
