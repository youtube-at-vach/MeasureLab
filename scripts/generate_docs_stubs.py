
import os
import yaml
from pathlib import Path

# Configuration
WIDGETS_DIR = Path("src/gui/widgets")
DOCS_DIR = Path("docs")
WIDGETS_DOCS_DIR = DOCS_DIR / "widgets"
MKDOCS_FILE = Path("mkdocs.yml")

# Ensure directories exist
WIDGETS_DOCS_DIR.mkdir(parents=True, exist_ok=True)
(DOCS_DIR / "measurement_recipes").mkdir(parents=True, exist_ok=True)

def get_widget_files():
    widgets = []
    if not WIDGETS_DIR.exists():
        print(f"Warning: {WIDGETS_DIR} does not exist.")
        return widgets

    for f in sorted(os.listdir(WIDGETS_DIR)):
        if f.endswith(".py") and f != "__init__.py" and "test" not in f:
             widgets.append(f)
    return widgets

def create_markdown_stub(filename, title):
    filepath = WIDGETS_DOCS_DIR / filename
    if not filepath.exists():
        content = f"""# {title}

## 概要
(ここに{title}の概要を記述してください)

## 操作方法
(ここに操作方法を記述してください)

## 設定項目
(ここに設定項目を記述してください)
"""
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"Created {filepath}")
    else:
        print(f"Skipped {filepath} (already exists)")

def create_basic_docs():
    # Helper to create file if not exists
    def create_if_missing(path, title, content_template=""):
        if not path.exists():
            with open(path, "w", encoding="utf-8") as f:
                f.write(f"# {title}\n\n{content_template}")
            print(f"Created {path}")

    create_if_missing(DOCS_DIR / "index.md", "はじめに", "MeasureLabへようこそ。\n\nこのドキュメントでは測定ツールの操作方法を解説します。")
    create_if_missing(DOCS_DIR / "quickstart.md", "クイックスタート", "インストール方法や簡単な使い方を説明します。")
    create_if_missing(DOCS_DIR / "appendix.md", "付録", "用語集や参考文献など。")
    create_if_missing(DOCS_DIR / "measurement_recipes/noise_measurement.md", "ノイズ測定", "ノイズ測定の具体的な手順レシピです。") # Per user request example
    

def generate_mkdocs_yml(widget_files):
    # Prepare widget nav items
    widget_nav = []
    for w in widget_files:
        name = w.replace(".py", "")
        # Convert snake_case to Title Case (simple heuristic)
        title = name.replace("_", " ").title()
        md_file = f"widgets/{name}.md"
        widget_nav.append({title: md_file})
        
        # Create the stub file for this widget
        create_markdown_stub(f"{name}.md", title)

    # Define the full nav structure
    nav = [
        {"はじめに": "index.md"},
        {"クイックスタート": "quickstart.md"},
        {"ウィジット": widget_nav},
        {"測定レシピ": [
            {"ノイズ測定": "measurement_recipes/noise_measurement.md"}
        ]},
        {"付録": "appendix.md"}
    ]

    config = {
        "site_name": "Measurement Tool Manual",
        "site_description": "測定ツールの操作マニュアル",
        "site_author": "Your Name",
        "theme": {
            "name": "material",
            "language": "ja"
        },
        "nav": nav
    }

    # Write mkdocs.yml
    if not MKDOCS_FILE.exists():
        with open(MKDOCS_FILE, "w", encoding="utf-8") as f:
            yaml.dump(config, f, allow_unicode=True, sort_keys=False)
        print(f"Created {MKDOCS_FILE}")
    else:
        print(f"{MKDOCS_FILE} already exists. Skipping overwrite to preserve manual changes. Please update nav manually if needed.")

if __name__ == "__main__":
    create_basic_docs()
    widget_files = get_widget_files()
    generate_mkdocs_yml(widget_files)
    print("Documentation stubs generation complete.")
