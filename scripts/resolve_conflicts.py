import glob
import os
import re

def resolve_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Regex to capture the conflict block
    # We look for <<<<<<< HEAD ... ======= ... >>>>>>> ...
    # dotall=True allows . to match newlines
    pattern = re.compile(r'<<<<<<< HEAD\n(.*?)\n=======\n(.*?)\n>>>>>>> [^\n]*', re.DOTALL)

    match = pattern.search(content)
    if not match:
        print(f"No conflict markers found in {filepath}")
        return

    head_content = match.group(1)
    remote_content = match.group(2)

    # HEAD content usually ends with "}" (without comma) or "}\n"
    # We need to remove the closing brace and add a comma to the last property

    # 1. Remove the last closing brace in HEAD content
    # Find the last '}'
    last_brace_idx = head_content.rfind('}')
    if last_brace_idx != -1:
        # Check if it is the closing brace of the main object?
        # Since we are appending keys to the main object, the conflict is likely at the end of the file.
        # The content before HEAD usually contains the start of the object.
        # HEAD content contains my new keys and the closing brace.

        # Remove the brace
        head_content_fixed = head_content[:last_brace_idx] + head_content[last_brace_idx+1:]

        # Now we need to ensure the last non-whitespace character is NOT a comma (wait, we need to ADD a comma)
        # Actually, if the previous last item didn't have a comma (valid JSON), now we add more items, so we MUST add a comma.

        # Strip trailing whitespace to find the last char
        head_content_fixed = head_content_fixed.rstrip()
        if head_content_fixed and head_content_fixed[-1] != ',':
             head_content_fixed += ','

        # Add newline for formatting
        head_content_fixed += '\n'
    else:
        print(f"Warning: No closing brace found in HEAD block of {filepath}")
        head_content_fixed = head_content

    # Remote content also usually ends with "}" (which we want to keep as the new end of file)
    # We don't need to change remote content, just append it.

    new_block = head_content_fixed + remote_content

    new_content = content.replace(match.group(0), new_block)

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(new_content)

    print(f"Resolved {filepath}")

def main():
    files = glob.glob("src/assets/lang/*.json")
    for fp in files:
        # Check if file has conflict markers
        with open(fp, 'r', encoding='utf-8') as f:
            if "<<<<<<< HEAD" in f.read():
                resolve_file(fp)

if __name__ == "__main__":
    main()
