
# fix_for_loop.py
from __future__ import annotations
import os, sys, re

PATH = os.path.join(os.path.dirname(__file__), "bazos_bot.py")

def main():
    if not os.path.exists(PATH):
        print("bazos_bot.py not found next to this script.")
        sys.exit(1)

    with open(PATH, "r", encoding="utf-8") as f:
        text = f.read()

    # Normalize tabs -> 4 spaces
    text = text.replace("\t", "    ")
    lines = text.splitlines()

    # Find a 'for' line that looks like the selector loop
    target_idx = None
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith("for ") and s.endswith(":") and "sel" in s and ("SEND_CODE" in s or "CONFIRM" in s or "ERROR_" in s or "SUCCESS_" in s):
            target_idx = i
            break

    if target_idx is None:
        print("Target 'for sel in ...:' loop not found.")
        sys.exit(2)

    # Ensure the very next non-empty line is indented at least +4 spaces
    j = target_idx + 1
    while j < len(lines) and lines[j].strip() == "":
        j += 1
    if j >= len(lines):
        print("No body after 'for' line to fix.")
        sys.exit(3)

    # Current indent of 'for' line:
    base_indent = len(lines[target_idx]) - len(lines[target_idx].lstrip(" "))
    need_indent = base_indent + 4

    # If the first body line is not indented enough, indent a contiguous block
    first_line = lines[j]
    first_indent = len(first_line) - len(first_line.lstrip(" "))

    if first_indent >= need_indent:
        print("Looks already indented. No changes made.")
        sys.exit(0)

    # Indent from j forward until we hit a blank line or a line with indent <= base_indent
    k = j
    while k < len(lines):
        line = lines[k]
        if line.strip() == "":
            break
        cur_indent = len(line) - len(line.lstrip(" "))
        if cur_indent <= base_indent and not line.lstrip().startswith("#"):
            break
        lines[k] = (" " * need_indent) + line.lstrip(" ")
        k += 1

    fixed = "\n".join(lines) + ("\n" if not lines[-1].endswith("\n") else "")
    with open(PATH + ".bak", "w", encoding="utf-8") as f:
        f.write(text)
    with open(PATH, "w", encoding="utf-8") as f:
        f.write(fixed)

    print(f"Fixed indentation under the for-loop at line {target_idx+1}. Backup: bazos_bot.py.bak")

if __name__ == "__main__":
    main()
