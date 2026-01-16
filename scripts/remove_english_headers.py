import os
import re

def process_files(root_dir, dry_run=True):
    # Regex to match headers with parenthesized English text at the end
    # Matches: ^(#+ .*)\s+\([a-zA-Z].*\)\s*$
    # We insist that the content inside parens starts with an alphabet letter to avoid removing (1), (A), etc. if used.
    # Also we want to handle cases where there might be spaces before the parens.
    pattern = re.compile(r'^(#+.*?)\s+\([a-zA-Z0-9\s\-,./&]+\)\s*$')

    for root, dirs, files in os.walk(root_dir):
        for file in files:
            # Skip English files
            if file.endswith('.en.md') or not file.endswith('.md'):
                continue

            path = os.path.join(root, file)
            with open(path, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            new_lines = []
            changed = False
            for i, line in enumerate(lines):
                if line.lstrip().startswith('#'):
                    match = pattern.match(line)
                    if match:
                        new_line = match.group(1).rstrip() + '\n'
                        # Sanity check: don't remove if it results in empty header or weird state
                        if len(new_line.strip()) > 1: 
                            if new_line != line:
                                print(f"[{'DRY' if dry_run else 'FIX'}] {path}:{i+1}")
                                print(f"  - {line.strip()}")
                                print(f"  + {new_line.strip()}")
                                changed = True
                                new_lines.append(new_line)
                            else:
                                new_lines.append(line)
                        else:
                             new_lines.append(line)
                    else:
                        new_lines.append(line)
                else:
                    new_lines.append(line)

            if changed and not dry_run:
                with open(path, 'w', encoding='utf-8') as f:
                    f.writelines(new_lines)

if __name__ == '__main__':
    print("--- DRY RUN ---")
    process_files('/home/hotstaff/github-vach/MeasureLab/docs', dry_run=True)

    print("\n--- APPLYING CHANGES ---")
    process_files('/home/hotstaff/github-vach/MeasureLab/docs', dry_run=False)
