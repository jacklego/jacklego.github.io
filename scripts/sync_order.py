#!/usr/bin/env python3
"""Make each listing's `order:` keys follow its `order.txt`.

Each season directory (`pumpkins/<year>/`, and `non-pumpkins/`) can carry an
`order.txt`: one carving title per line, top to bottom in the order the grid
shows them. `ingest.py` appends to it as photos arrive, Peter rearranges the
lines in GitHub's web editor when he's done uploading, and this script rewrites
every carving's `order:` to 1, 2, 3... to match. `.github/workflows/order.yml`
runs it on any push that touches an `order.txt`.

The file is the source of truth; `order:` is what Quarto sorts by, so this keeps
the two in step. It follows ingest's rules:

  1. Peter's edit never fails the run. A line matching no carving -- a typo, a
     deleted carving -- is reported and dropped.
  2. Nothing gets lost. A carving missing from the file keeps its relative
     place, after everything the file lists.
  3. Re-running is a no-op. The file is rewritten in canonical form (one title
     per line, the header restored), so a second run changes nothing.

A line matches a carving by its title or its directory name, ignoring case,
quotes and extra spaces. Failing that, a leading list number or bullet
(`3.`, `3)`, `-`) is stripped and it is tried again.

Stdlib-only, so the runner's python3 is enough, like sync_drafts.py.

Usage:
  python3 scripts/sync_order.py [--check] [DIR ...]
    DIR      a listing directory holding order.txt (default: every one)
    --check  report what would change and exit 1 if anything would
  python3 scripts/sync_order.py --seed pumpkins/2026
    write order.txt for a listing that has none, from its current `order:`
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME = "order.txt"

HEADER = """\
# The order of the pumpkins on this page, top to bottom.
#
# To change it, move the lines up or down (cut and paste), then click
# "Commit changes". The website picks up the new order in about a minute.
#
# Keep the names exactly as they are -- just move them around.
# Lines starting with # are ignored.
"""

TITLE_RE = re.compile(r"^title:\s*(.*?)\s*$", re.MULTILINE)
ORDER_RE = re.compile(r"^order:\s*\S*[ \t]*$", re.MULTILINE)
LIST_PREFIX = re.compile(r"^(?:\d+\s*[.)]|[-*•])\s*")


def norm(text: str) -> str:
    text = text.strip().strip('"').strip("'").replace("’", "'")
    return re.sub(r"\s+", " ", text).casefold()


def front_matter(qmd: Path) -> tuple[str, str]:
    """(front matter, rest) of a page, split on the closing `---`."""
    text = qmd.read_text(encoding="utf-8")
    m = re.match(r"(---\n.*?\n)(---\n.*)", text, re.DOTALL)
    return (m.group(1), m.group(2)) if m else ("", text)


def carvings(listing: Path) -> list[dict]:
    """Every carving under a listing, in its current `order:`."""
    out = []
    for qmd in sorted(listing.glob("*/index.qmd")):
        fm, _ = front_matter(qmd)
        title = TITLE_RE.search(fm)
        order = re.search(r"^order:\s*(\d+)", fm, re.MULTILINE)
        out.append({
            "slug": qmd.parent.name,
            "title": (title.group(1).strip('"').replace('\\"', '"')
                      if title else qmd.parent.name),
            "order": int(order.group(1)) if order else sys.maxsize,
            "qmd": qmd,
        })
    out.sort(key=lambda c: (c["order"], c["slug"]))
    return out


def read_lines(path: Path) -> list[str]:
    """The non-comment lines of an order file, tolerating a BOM and CRLF."""
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    return [ln.strip() for ln in text.splitlines()
            if ln.strip() and not ln.lstrip().startswith("#")]


def render(items: list[dict]) -> str:
    return HEADER + "\n" + "".join(c["title"] + "\n" for c in items)


def resolve(listing: Path) -> tuple[list[dict], list[str], list[dict]]:
    """Match the file against the carvings: (ordered carvings, unmatched lines,
    carvings the file left out)."""
    items = carvings(listing)
    index: dict[str, list[dict]] = {}
    for c in items:
        for key in {norm(c["title"]), norm(c["slug"])}:
            index.setdefault(key, []).append(c)

    ordered, unmatched, seen = [], [], set()
    for line in read_lines(listing / NAME):
        hits = index.get(norm(line)) or index.get(norm(LIST_PREFIX.sub("", line)))
        hits = [c for c in hits or [] if c["slug"] not in seen]
        if not hits:
            # A repeat of a line already placed is harmless, not a typo.
            if not any(norm(line) in (norm(c["title"]), norm(c["slug"]))
                       for c in ordered):
                unmatched.append(line)
            continue
        c = hits[0]  # two carvings sharing a title fill their lines in turn
        seen.add(c["slug"])
        ordered.append(c)
    missing = [c for c in items if c["slug"] not in seen]
    return ordered + missing, unmatched, missing


def set_order(qmd: Path, n: int, *, dry: bool) -> bool:
    fm, rest = front_matter(qmd)
    if ORDER_RE.search(fm):
        new = ORDER_RE.sub(f"order: {n}", fm, count=1)
    elif re.search(r"^date:", fm, re.MULTILINE):
        new = re.sub(r"^(date:)", rf"order: {n}\n\1", fm, count=1, flags=re.MULTILINE)
    else:
        new = fm + f"order: {n}\n"
    if new == fm:
        return False
    if not dry:
        qmd.write_text(new + rest, encoding="utf-8")
    return True


def sync(listing: Path, *, dry: bool = False) -> dict:
    """Apply one listing's order.txt. Returns what changed, for reporting."""
    ordered, unmatched, missing = resolve(listing)
    changed = [c["title"] for n, c in enumerate(ordered, start=1)
               if set_order(c["qmd"], n, dry=dry)]
    path = listing / NAME
    before = path.read_text(encoding="utf-8") if path.exists() else None
    after = render(ordered)
    if before != after and not dry:
        path.write_text(after, encoding="utf-8")
    return {
        "listing": str(listing.relative_to(ROOT)),
        "order": [c["title"] for c in ordered],
        "renumbered": changed,
        "unmatched": unmatched,
        "missing": [c["title"] for c in missing],
        "file_changed": before != after,
    }


def place(listing: Path, slug: str, position: int | None = None) -> int:
    """Put one carving into a listing's order.txt and sync. Used by ingest.

    With no `position`, a carving already in the file keeps its place (so a
    --force re-ingest doesn't move it) and a new one goes last. A position is
    1-based and clamped. Creates the file from the current `order:` if absent.
    Returns the carving's final `order:`.
    """
    ordered, _, missing = resolve(listing)
    if position is not None or any(c["slug"] == slug for c in missing):
        c = next(c for c in ordered if c["slug"] == slug)
        ordered.remove(c)
        if position is None:
            ordered.append(c)
        else:
            ordered.insert(max(0, min(position - 1, len(ordered))), c)
    (listing / NAME).write_text(render(ordered), encoding="utf-8")
    sync(listing)
    return [c["slug"] for c in ordered].index(slug) + 1


def all_listings() -> list[Path]:
    return sorted(p.parent for p in [*ROOT.glob(f"pumpkins/*/{NAME}"),
                                     ROOT / "non-pumpkins" / NAME] if p.exists())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dirs", nargs="*", type=Path)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--seed", action="store_true",
                    help="create order.txt from the current order where missing")
    args = ap.parse_args()

    listings = [(d if d.is_absolute() else ROOT / d).resolve() for d in args.dirs]
    if args.seed:
        for listing in listings:
            path = listing / NAME
            if path.exists():
                print(f"{path.relative_to(ROOT)} already exists")
            elif not args.check:
                path.write_text(render(carvings(listing)), encoding="utf-8")
                print(f"wrote {path.relative_to(ROOT)}")
        return 0

    dirty = False
    for listing in listings or all_listings():
        r = sync(listing, dry=args.check)
        if not (r["renumbered"] or r["file_changed"] or r["unmatched"]):
            continue
        dirty = dirty or bool(r["renumbered"] or r["file_changed"])
        print(f"{r['listing']}/{NAME}")
        for n, title in enumerate(r["order"], start=1):
            print(f"  {n:>2}. {title}" + ("   (moved)" if title in r["renumbered"] else ""))
        for line in r["unmatched"]:
            print(f"  ! no carving called {line!r} -- line dropped")
        for title in r["missing"]:
            print(f"  ! {title!r} wasn't in the file -- put at the end")
    if not dirty:
        print("order already matches every order.txt")
    return 1 if args.check and dirty else 0


if __name__ == "__main__":
    sys.exit(main())
