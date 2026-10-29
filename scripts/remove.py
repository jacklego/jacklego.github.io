# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow"]
# ///
"""Remove one carving, and everything that would otherwise bring it back.

Deleting a carving's directory is not enough. Its original stays parked in
`_inbox/`, and the next ingest run sees a photo with no page and rebuilds it. So
this removes, in one go:

  - the carving's directory;
  - every inbox file ingest would build into that directory -- worked out by
    asking `ingest.build()` itself, in dry-run, where each parked photo would
    go, so the two can't disagree about what "belongs" to a carving;
  - its line in the season's `order.txt`, renumbering the rest;
  - the year page's `image:`, if it pointed at this carving -- repointed at
    the first carving left, or dropped if none are.

Anything else that mentions the carving (a link on another page, the homepage
image) is reported for a human rather than edited.

The name is matched like an `order.txt` line: the title or directory name,
ignoring case. A year anywhere in it narrows the search (`Darth Vader 2020`),
and a pasted link or `pumpkins/2020/darth-vader` path is taken as-is. Unlike
ingest, a name that matches nothing -- or more than one carving -- exits 1
having changed nothing: Peter typed this into a box and pressed Run, and a red
X with the reason is the answer he needs.

Run by `.github/workflows/remove.yml`. It does not publish.

Usage:
  uv run scripts/remove.py "Alastor Mad Eye Moody" [--dry-run] [--summary FILE]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ingest  # noqa: E402
import sync_order  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
INBOX = ROOT / "_inbox"
IMAGE_RE = re.compile(r"^image:\s*(\S.*?)\s*$", re.MULTILINE)


def listings() -> list[Path]:
    return sorted(p for p in (ROOT / "pumpkins").iterdir()
                  if p.is_dir() and re.fullmatch(r"\d{4}", p.name)) + [ROOT / "non-pumpkins"]


def carving_year(c: dict) -> str:
    """The season directory, or for a non-pumpkin its `year:` key."""
    listing = c["qmd"].parent.parent
    if listing.name != "non-pumpkins":
        return listing.name
    m = re.search(r"^year:\s*(\d{4})", c["qmd"].read_text(encoding="utf-8"), re.M)
    return m.group(1) if m else ""


def find(query: str) -> list[dict]:
    """Every carving the query could mean."""
    m = re.search(r"((?:pumpkins/\d{4}|non-pumpkins)/[A-Za-z0-9_-]+)", query)
    if m and (ROOT / m.group(1) / "index.qmd").is_file():
        qmd = ROOT / m.group(1) / "index.qmd"
        return [c for c in sync_order.carvings(qmd.parent.parent) if c["qmd"] == qmd]

    everything = [c for listing in listings() for c in sync_order.carvings(listing)]

    def named(name: str) -> list[dict]:
        want = sync_order.norm(name)
        return [c for c in everything
                if want in (sync_order.norm(c["title"]), sync_order.norm(c["slug"]))]

    # The whole query first, so a title that contains a year -- "Frankenstein
    # (1931)" -- still matches as typed.
    hits = named(query)
    year = re.search(r"\b(\d{4})\b", query)
    if not hits and year:
        rest = re.sub(r"[\s,()-]*\b\d{4}\b[\s,()-]*", " ", query).strip()
        hits = [c for c in named(rest) if carving_year(c) == year.group(1)]
    return hits


def parked_originals(target: Path) -> list[Path]:
    """The inbox files ingest would build into `target`."""
    if not INBOX.is_dir():
        return []
    items, _ = ingest.collect(INBOX)
    args = SimpleNamespace(dry_run=True, force=False, changed=None)
    pagetitles = ingest.existing_pagetitles()
    rel = str(target.relative_to(ROOT))
    out = []
    for item in items:
        item["captured"], item["ratio"] = ingest.probe(item["main"])
        if ingest.build(item, args, pagetitles, {})["path"] == rel:
            out += [p for _, p in item["group"]]
            if item["sidecar"]:
                out.append(item["sidecar"])
    return out


def references(target: Path) -> list[tuple[Path, str]]:
    """Pages outside the carving that mention it, as (page, line)."""
    rel = str(target.relative_to(ROOT))
    out = []
    for page in ROOT.rglob("*.qmd"):
        if target in page.parents or any(part.startswith(("_", ".")) for part in
                                         page.relative_to(ROOT).parts):
            continue
        for line in page.read_text(encoding="utf-8").splitlines():
            # Resolve relative `image:` values too: a year page says
            # `image: dracula/_dracula__thumb.jpg`, not the full path.
            m = IMAGE_RE.match(line)
            resolved = ""
            if m:
                try:
                    resolved = str((page.parent / m.group(1)).resolve()
                                   .relative_to(ROOT.resolve()))
                except ValueError:  # a URL, or a path outside the repo
                    pass
            if rel + "/" in line or resolved.startswith(rel + "/"):
                out.append((page, line.strip()))
    return out


def repoint_year_image(listing: Path, target: Path, *, dry: bool) -> str | None:
    """Fix the listing page's `image:` if it showed the removed carving."""
    index = listing / "index.qmd"
    if not index.is_file():
        return None
    text = index.read_text(encoding="utf-8")
    m = IMAGE_RE.search(text)
    if not m or not m.group(1).startswith(target.name + "/"):
        return None
    left = [c for c in sync_order.carvings(listing) if c["qmd"].parent != target]
    for c in left:
        thumb = IMAGE_RE.search(c["qmd"].read_text(encoding="utf-8"))
        if thumb:
            new = f"image: {c['slug']}/{thumb.group(1)}"
            if not dry:
                index.write_text(text[:m.start()] + new + text[m.end():], encoding="utf-8")
            return f"{index.relative_to(ROOT)}: `image:` now shows {c['title']}"
    # Quarto rejects an empty `image:`, so the key goes; ingest adds it back
    # when the next carving arrives.
    if not dry:
        index.write_text(text[:m.start()] + text[m.end() + 1:], encoding="utf-8")
    return f"{index.relative_to(ROOT)}: `image:` removed -- no carvings left"


def fail(message: str) -> int:
    if os.environ.get("GITHUB_ACTIONS"):
        print(f"::error::{message}")
    print(message, file=sys.stderr)
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("name")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--summary", type=Path, help="write a JSON report here")
    args = ap.parse_args()
    dry = args.dry_run

    query = args.name.strip()
    hits = find(query) if query else []
    if not hits:
        return fail(f"No pumpkin called \"{query}\" -- nothing was removed. "
                    "Use the name exactly as the website shows it.")
    if len(hits) > 1:
        options = "; ".join(f"{c['title']} {carving_year(c)}" for c in hits)
        return fail(f"\"{query}\" matches {len(hits)} pumpkins -- nothing was removed. "
                    f"Add the year to say which one: {options}.")

    c = hits[0]
    target, listing = c["qmd"].parent, c["qmd"].parent.parent
    rel = str(target.relative_to(ROOT))
    originals = parked_originals(target)
    done: list[str] = []
    todo: list[str] = []

    if not dry:
        shutil.rmtree(target)
    done.append(f"deleted {rel}/")
    for path in originals:
        if not dry:
            path.unlink()
        done.append(f"deleted _inbox/{path.name}")

    if (listing / sync_order.NAME).is_file():
        if not dry:
            sync_order.sync(listing)
        done.append(f"took it out of {listing.relative_to(ROOT)}/{sync_order.NAME}")
    if note := repoint_year_image(listing, target, dry=dry):
        done.append(note)

    # Read after the year page is repointed, so only what's still pointing
    # at the carving is reported.
    for page, line in ([] if dry else references(target)):
        todo.append(f"{page.relative_to(ROOT)} still mentions it: `{line}`")

    verb = "Would remove" if dry else "Removed"
    print(f"{verb} {c['title']} ({rel})")
    for line in done:
        print(f"  - {line}")
    for line in todo:
        print(f"  ! {line}")

    if args.summary:
        args.summary.write_text(json.dumps({
            "title": c["title"], "path": rel, "done": done, "todo": todo,
        }, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
