
# fix_indent.py
from __future__ import annotations
import re, sys, os

PATH = os.path.join(os.path.dirname(__file__), "bazos_bot.py")

def main():
    if not os.path.exists(PATH):
        print("bazos_bot.py not found next to this script.")
        sys.exit(1)
    with open(PATH, "r", encoding="utf-8") as f:
        text = f.read()

    # Replace tabs with 4 spaces globally to prevent mixed-indentation errors
    text = text.replace("\t", "    ")

    lines = text.splitlines()

    # Find target indices
    try:
        i_global = next(i for i,l in enumerate(lines) if "global SEND_CODE_TEXTS" in l)
    except StopIteration:
        print("No 'global SEND_CODE_TEXTS' line found. Nothing to fix.")
        return

    # Find indentation of run_country_flow body (first non-empty line after def)
    try:
        i_def = next(i for i,l in enumerate(lines) if l.strip().startswith("def run_country_flow("))
    except StopIteration:
        print("def run_country_flow(...) not found.")
        sys.exit(2)

    # Compute base indent: look ahead for first non-empty line after def
    indent_base = None
    for j in range(i_def+1, min(i_def+40, len(lines))):
        s = lines[j]
        if s.strip():
            indent_base = len(s) - len(s.lstrip(" "))
            break
    if indent_base is None:
        indent_base = 4

    # Also try to capture the indent of the 'with sync_playwright() as pw:' line (desired indent)
    desired = None
    for j in range(i_def+1, len(lines)):
        if "with sync_playwright() as pw:" in lines[j]:
            desired = len(lines[j]) - len(lines[j].lstrip(" "))
            break
    if desired is None:
        # fall back to base
        desired = indent_base

    # Now reindent the block starting at the config load down to (but not including) the 'with' line
    # Detect start of block: a line with 'cfg = load_runtime_config()'
    try:
        i_cfg = next(i for i,l in enumerate(lines) if "cfg = load_runtime_config()" in l)
    except StopIteration:
        i_cfg = i_global  # at least move the globals

    end = j if desired is not None else i_global+1
    new_lines = lines[:]

    for k in range(i_cfg, end):
        # Skip empty lines
        if not new_lines[k].strip():
            continue
        content = new_lines[k].lstrip(" ")
        new_lines[k] = " " * desired + content

    fixed = "\n".join(new_lines) + ("\n" if not new_lines[-1].endswith("\n") else "")
    # Backup and write
    with open(PATH + ".bak", "w", encoding="utf-8") as f:
        f.write(text)
    with open(PATH, "w", encoding="utf-8") as f:
        f.write(fixed)
    print("Indentation normalized. Backup saved as bazos_bot.py.bak")

if __name__ == "__main__":
    main()
