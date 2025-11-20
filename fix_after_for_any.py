
# fix_after_for_any.py
from __future__ import annotations
import os, sys, re

PATH = os.path.join(os.path.dirname(__file__), "bazos_bot.py")

def get_indent(s: str) -> int:
    return len(s) - len(s.lstrip(" "))

def main():
    if not os.path.exists(PATH):
        print("bazos_bot.py not found next to this script.")
        sys.exit(1)

    text = open(PATH, "r", encoding="utf-8").read()
    # normalize tabs -> 4 spaces to avoid mixed-indents
    text = text.replace("\t", "    ")
    lines = text.splitlines()

    i = 0
    fixes = 0
    while i < len(lines)-1:
        line = lines[i]
        if re.match(r'^\s*for\b.+:\s*$', line):
            base_indent = get_indent(line)
            # find first non-empty after this
            j = i + 1
            while j < len(lines) and lines[j].strip() == "":
                j += 1
            if j >= len(lines):
                break
            first = lines[j]
            first_indent = get_indent(first)
            if first_indent <= base_indent:
                # need to indent a block
                need = base_indent + 4
                k = j
                while k < len(lines):
                    cur = lines[k]
                    if cur.strip() == "":
                        break
                    cur_indent = get_indent(cur)
                    # stop if we hit a new top-level or same-level construct (not a comment)
                    if cur_indent <= base_indent and not cur.lstrip().startswith("#"):
                        break
                    # indent this line to at least 'need' (if it's not already deeper)
                    stripped = cur.lstrip(" ")
                    lines[k] = (" " * need) + stripped
                    k += 1
                fixes += 1
                i = k
                continue
        i += 1

    if fixes == 0:
        print("No missing-indent after 'for' loops detected. Nothing changed.")
        return

    fixed = "\n".join(lines) + ("\n" if not lines[-1].endswith("\n") else "")
    with open(PATH + ".bak", "w", encoding="utf-8") as f:
        f.write(text)
    with open(PATH, "w", encoding="utf-8") as f:
        f.write(fixed)
    print(f"Applied {fixes} indent fix(es). Backup: bazos_bot.py.bak")

if __name__ == '__main__':
    main()
