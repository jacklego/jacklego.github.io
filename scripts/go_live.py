#!/usr/bin/env python3
"""Take a season public.

Everything the draft gate needs lives in `_variables.yml`, so going live is
mostly two edits there -- but a few other things have to move at the same
moment, and forgetting one of them is the failure mode this script exists to
prevent. It does not publish; that stays a deliberate `quarto publish gh-pages`.

Deliberately stdlib-only and rewrite-in-place rather than a templating pass, so
the diff it produces is small and reviewable.

Usage:
  python3 scripts/go_live.py 2026 --theme "Classic Movie Monsters"
  python3 scripts/go_live.py 2026 --dry-run
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def edit(path: Path, pattern: str, replacement: str, *, dry: bool,
         flags=re.MULTILINE, expect=1) -> bool:
    """Apply one regex substitution, reporting what changed."""
    before = path.read_text(encoding="utf-8")
    after, n = re.subn(pattern, replacement, before, count=expect, flags=flags)
    rel = path.relative_to(ROOT)
    if n == 0:
        print(f"  !! {rel}: no match for {pattern!r} -- edit by hand")
        return False
    if before == after:
        print(f"  ok {rel}: already current")
        return True
    print(f"  {'would edit' if dry else 'edited'} {rel}")
    if not dry:
        path.write_text(after, encoding="utf-8")
    return True


def theme_for(year: str) -> str | None:
    """Read the season's theme out of _variables.yml, if it has one."""
    text = (ROOT / "_variables.yml").read_text(encoding="utf-8")
    m = re.search(rf"^\s+{year}\s*:\s*(.*)$", text, re.MULTILINE)
    if not m:
        return None
    return m.group(1).strip().strip('"').strip("'")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("year")
    ap.add_argument("--theme", help="season theme; reused from _variables.yml if omitted")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    year = args.year
    if not re.match(r"^\d{4}$", year):
        print(f"not a year: {year}", file=sys.stderr)
        return 2
    year_dir = ROOT / "pumpkins" / year
    if not year_dir.is_dir():
        print(f"no such season: {year_dir.relative_to(ROOT)}", file=sys.stderr)
        return 2

    dry = args.dry_run
    theme = args.theme if args.theme is not None else (theme_for(year) or "")
    variables = ROOT / "_variables.yml"

    print(f"Taking {year} live" + (f' -- "{theme}"' if theme else " (no theme)"))
    print("\n_variables.yml -- this is what the draft gate reads")
    edit(variables, r"^currentYear\s*:.*$", f"currentYear: {year}", dry=dry)
    if theme_for(year) is None:
        # Append inside the ptheme block, after the highest year already listed.
        text = variables.read_text(encoding="utf-8")
        last = max(re.findall(r"^\s+(\d{4})\s*:", text, re.MULTILINE), default=None)
        if last is None:
            print("  !! no ptheme block found -- add the entry by hand")
        else:
            print(f"  {'would add' if dry else 'added'} ptheme entry {year}")
            if not dry:
                variables.write_text(
                    re.sub(rf"^(\s+){last}(\s*:.*)$",
                           lambda m: f"{m.group(0)}\n{m.group(1)}{year}: {theme}",
                           text, count=1, flags=re.MULTILINE),
                    encoding="utf-8",
                )
    else:
        edit(variables, rf"^(\s+){year}\s*:.*$", rf"\g<1>{year}: {theme}", dry=dry)

    print(f"\npumpkins/{year}/index.qmd -- the theme is visible on this page")
    index = year_dir / "index.qmd"
    pagetitle = f"{year} pumpkin carvings" + (f": {theme}" if theme else "")
    edit(index, r'^pagetitle\s*:.*$', f'pagetitle: "{pagetitle}"', dry=dry)
    edit(index, r"^description\s*:.*$",
         f"description: {theme}" if theme else 'description: ""', dry=dry)

    print("\n_quarto.yml -- point This Year's Patch at the new season")
    edit(ROOT / "_quarto.yml", r"(?<=href: pumpkins/)\d{4}", year, dry=dry)

    print("\nDraft gate")
    sys.stdout.flush()  # the child writes straight to fd 1
    if dry:
        subprocess.run([sys.executable, str(ROOT / "scripts" / "sync_drafts.py"),
                        "--check"], check=False)
    else:
        subprocess.run([sys.executable, str(ROOT / "scripts" / "sync_drafts.py")],
                       check=False)

    print(f"""
Still yours to do:
  1. _homepage-memo.md    -- replace with Peter's note for the {year} season
  2. review order         -- carvings are in upload order; resequence `order:`
                             if Peter wants a different one
  3. close out the open `review` issues
  4. archive originals    -- move anything left in _inbox/ into
                             _full-sized-assets/all-pumpkins/{year}/
  5. quarto publish gh-pages
""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
