
import re
import os
from mkdocs.structure.pages import Page
from mkdocs.config.defaults import MkDocsConfig

try:
    from py_mini_racer import MiniRacer
except ImportError:
    MiniRacer = None

def on_page_content(html: str, page: Page, config: MkDocsConfig, **kwargs):
    if MiniRacer is None:
        print("Warning: py_mini_racer not installed. Math rendering skipped.")
        return html

    # Initialize JS environment logic
    # We load the JS file from the docs assets
    # Note: during build, docs/assets might be source or destination. 
    # We should look in the project docs dir.
    js_path = os.path.join(config['docs_dir'], 'assets', 'js', 'katex.min.js')

    if not os.path.exists(js_path):
        print(f"Warning: Katex JS not found at {js_path}")
        return html

    ctx = MiniRacer()
    with open(js_path, "r", encoding="utf-8") as f:
        js_content = f.read()
        ctx.eval(js_content)

    def replace_math(match):
        tag = match.group(1) # span or div
        content = match.group(2) # content inside tags including delimiters

        # Arithmatex generic output wraps content in \(...\) or \[...\]
        # We need to extract the raw TeX.

        tex = content.strip()
        display_mode = False

        # Check for delimiters
        if tex.startswith(r"\(") and tex.endswith(r"\)"):
            tex = tex[2:-2]
        elif tex.startswith(r"\[") and tex.endswith(r"\]"):
            tex = tex[2:-2]
            display_mode = True
        else:
            # Fallback or unknown format
            return match.group(0)

        # Unescape HTML entities if necessary? 
        # Markdown parsing might convert & to &amp;, < to &lt;, etc.
        # KaTeX expects raw TeX. 
        # Simple unescape for common issues:
        tex = tex.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')

        try:
            # Render using KaTeX
            # We construct a JS call
            # options: { displayMode: true/false, throwOnError: false }
            options = {
                "displayMode": display_mode,
                "throwOnError": False
            }
            # MiniRacer call handles basic types
            rendered = ctx.call("katex.renderToString", tex, options)
            return rendered
        except Exception as e:
            print(f"Math rendering error in {page.file.src_path}: {e}")
            return match.group(0)

    # Regex to find arithmatex blocks
    # Matches <span class="arithmatex">...</span> or <div class="arithmatex">...</div>
    # Non-greedy match for content
    pattern = re.compile(r'<(span|div) class="arithmatex">(.*?)</\1>', re.DOTALL)

    new_html = pattern.sub(replace_math, html)
    return new_html
