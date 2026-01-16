import os
import re
import urllib.parse

def get_anchors(file_path):
    anchors = set()
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    for line in lines:
        if line.lstrip().startswith('#'):
            # Basic slugification strategy for Python-Markdown
            # This is an approximation. 
            # 1. Lowercase
            # 2. Remove non-alphanumeric (except - and _)
            # 3. Spaces to hyphens
            # Note: Python-Markdown handles unicode, but often non-ascii characters are kept or processed.
            # However, user links might be pointing to English slugs that no longer exist for Japanese headers.
            # We are mainly looking for links that point to potential English terms that were removed.
            pass

            # Since exact slug generation is complex, we will just collect the raw header text for loose matching
            # and maybe the header line itself.
            header_text = line.lstrip('#').strip()
            anchors.add(header_text)

    return anchors

def validate_links(root_dir):
    # regex for [text](link)
    link_pattern = re.compile(r'\]\(([^)]+)\)')

    # Store all headers for each file
    file_headers = {}

    # First pass: collect all files and headers
    for root, dirs, files in os.walk(root_dir):
        for file in files:
            if file.endswith('.md'):
                path = os.path.join(root, file)
                # Store relative path from doc root
                rel_path = os.path.relpath(path, root_dir)
                file_headers[rel_path] = get_anchors(path)

    # Second pass: check links
    for root, dirs, files in os.walk(root_dir):
        for file in files:
            if not file.endswith('.md'):
                continue

            current_file_path = os.path.join(root, file)
            rel_current_path = os.path.relpath(current_file_path, root_dir)

            with open(current_file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            links = link_pattern.findall(content)
            for link in links:
                # Ignore external links
                if link.startswith('http') or link.startswith('mailto:'):
                    continue

                # Parse link
                parts = link.split('#')
                target = parts[0]
                anchor = parts[1] if len(parts) > 1 else None

                # Resolve target file
                if not target:
                    target_file = rel_current_path
                else:
                    # Handle relative paths, e.g. ../foo.md
                    # This is tricky without full path resolution logic, 
                    # but we can try basic resolution relative to current file dir
                    target_dir = os.path.dirname(rel_current_path)
                    try:
                        resolved_target = os.path.normpath(os.path.join(target_dir, target))
                    except:
                        resolved_target = target # Fallback

                    target_file = resolved_target

                # Check if file exists in our map
                if target_file in file_headers:
                    if anchor:
                        # Check if anchor looks like it might be missing
                        # This is fuzzy because we don't have the exact slug implementation
                        # But if the anchor is "troubleshooting" and no header contains "Troubleshooting", it's suspicious.

                        # Heuristic: Check if anchor (or parts of it) exist in any header
                        # If anchor is "troubleshooting" and we removed "(Troubleshooting)" from header, 
                        # the new header is "トラブルシューティング". The slug for that will be completely different (unicode).
                        # So if we find an ASCII anchor to a Japanese file, it's likely broken now.

                        # Skip this check for English files
                        if target_file.endswith('.en.md'):
                            continue

                        # If target is Japanese file (no .en.md)
                        # and anchor contains english letters
                        # and anchor is NOT found in the headers (fuzzy match)
                        if re.search(r'[a-zA-Z]', anchor):
                            # It's an English anchor pointing to a Japanese file. 
                            # Suspicious if the English text was removed.
                            print(f"[POTENTIAL BROKEN LINK] in {rel_current_path}")
                            print(f"  Link: {link}")
                            print(f"  Target: {target_file}")
                            print(f"  Anchor: {anchor}")
                            # print(f"  Available headers: {file_headers[target_file]}") -- too verbose

if __name__ == '__main__':
    validate_links('/home/hotstaff/github-vach/MeasureLab/docs')
