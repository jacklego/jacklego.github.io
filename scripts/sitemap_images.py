#!/usr/bin/env python3
"""Give `sitemap.xml` image entries, and point its URLs at the canonicals.

Quarto's sitemap lists pages and nothing else. Google Image Search runs off a
separate crawl from the one that indexes pages, and an image sitemap is the
supported way to tell it which images exist -- otherwise the 2400px web copy is
only discoverable by parsing a page body. So this rewrites the sitemap Quarto
just produced, adding an `<image:image>` child per photo:

    <url>
      <loc>https://peterspumpkinpatch.org/pumpkins/2025/dracula/</loc>
      <lastmod>2026-08-21T22:00:22.128Z</lastmod>
      <image:image>
        <image:loc>https://…/pumpkins/2025/dracula/dracula.jpg</image:loc>
      </image:image>
    </url>

`image:loc` is the only child still worth emitting: Google deprecated
`image:caption`, `image:title`, `image:license` and `image:geo_location` in 2022
and ignores them. The alt text is on the `<img>` tag, which is where it counts.

It also drops the trailing `index.html` from every `<loc>`, so the sitemap
agrees with the `<link rel="canonical">` Quarto writes into the page
(`canonical-url: true` resolves directory indexes to the trailing-slash form).
The mismatch cost nothing -- Google follows the canonical -- but there is no
reason to hand it two URLs for one page.

Which images
------------
Only the photos in a page's body, found by parsing the rendered HTML rather
than the front matter, so what lands in the sitemap is exactly what publishes.
Navbar logos and listing-card thumbnails are skipped by class, which means:

  - a carving page contributes its full-size web copy plus any secondary
    images (`_itchy.jpg` and friends);
  - a year page, section index or the Everything page contributes nothing,
    since all it shows is thumbnails of images already listed on their own
    pages. Google wants the best version of an image, once.

An `<img>` whose file is missing from the output directory is reported and
left out; a sitemap that lists 404s is worse than one that omits them.

A declared image that *looks* like a thumbnail is warned about on stderr but
still emitted. The skip list is three class names Quarto owns, so if a Quarto
release renames one the filter stops matching and thumbnails silently start
being declared -- it fails open. This makes that visible without failing the
run: Peter dispatches the publish workflow himself, and a red X he can't act on
is worse than a sitemap entry that can be fixed at leisure.

Draft seasons stay out for free: Quarto has already excluded them from the
sitemap, and this only ever rewrites the entries it finds there.

Post-render, and idempotent
---------------------------
Quarto writes `sitemap.xml` in its own website post-render step, which runs
before project `post-render` scripts, and nothing touches it afterwards -- so
this sees a finished sitemap and gets the last word.

On an *incremental* render Quarto reads the existing sitemap back, keeps only
`loc` and `lastmod`, and matches entries by exact `loc`. That has two
consequences this script has to absorb, and does:

  - image entries are dropped, so they are rebuilt from scratch every run;
  - a normalized `…/dracula/` no longer matches the `…/dracula/index.html`
    Quarto is looking for, so it appends a second entry for the same page.
    Every run therefore re-normalizes and de-duplicates the whole file, keeping
    the newest `lastmod`. The published sitemap is clean regardless of how many
    incremental renders preceded it.

Stdlib-only, like the other hook scripts: Quarto invokes it with whatever
`python3` is on PATH.

Usage:
  python3 scripts/sitemap_images.py [--site-dir _site] [--dry-run] [--quiet]
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit

ROOT = Path(os.environ.get("QUARTO_PROJECT_DIR") or Path(__file__).resolve().parent.parent)

SITEMAP_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"
IMAGE_NS = "http://www.google.com/schemas/sitemap-image/1.1"

# Chrome, not content. `navbar-logo` is the favicon in the navbar; every
# listing card thumbnail carries `thumbnail-image` (sometimes with `card-img`
# beside it, sometimes not); `about-image` is the avatar in the "jolla" about
# template, which here is Ozzy's *thumbnail* -- the full-size copy is already
# listed against the carving's own page, where it belongs.
SKIP_CLASSES = {"navbar-logo", "thumbnail-image", "about-image"}

# The naming convention from `ingest.py`: `_<stem>__thumb.jpg`. Nothing that
# matches this belongs in the sitemap -- see the docstring.
THUMB_MARKER = "__thumb."


class BodyImages(HTMLParser):
    """Collect the `src` of every content `<img>`, in document order."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.srcs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "img":
            return
        attr = dict(attrs)
        src = (attr.get("src") or "").strip()
        if not src or src.startswith("data:"):
            return
        if SKIP_CLASSES & set((attr.get("class") or "").split()):
            return
        if src not in self.srcs:
            self.srcs.append(src)


def site_url(quarto_yml: Path) -> str:
    """Read `website: site-url:` out of _quarto.yml.

    Only needed for its path component, so that a site published under a
    subdirectory still maps URLs back onto the output tree correctly.
    """
    if not quarto_yml.exists():
        return "/"
    m = re.search(r"^\s*site-url:\s*(\S+)\s*$", quarto_yml.read_text(encoding="utf-8"), re.M)
    return m.group(1).strip("\"'") if m else "/"


def canonical(loc: str) -> str:
    """`…/dracula/index.html` -> `…/dracula/`, matching the page's canonical."""
    return loc[: -len("index.html")] if loc.endswith("/index.html") else loc


def output_file(loc: str, base_path: str, site_dir: Path) -> Path:
    """Map a sitemap `<loc>` back to the rendered file that produced it."""
    path = urlsplit(loc).path
    if base_path and path.startswith(base_path):
        path = path[len(base_path) :]
    rel = path.lstrip("/")
    if not rel or rel.endswith("/"):
        rel += "index.html"
    return site_dir / rel


def read_urls(sitemap: Path) -> list[tuple[str, str | None]]:
    root = ET.parse(sitemap).getroot()
    urls = []
    for url in root.findall(f"{{{SITEMAP_NS}}}url"):
        loc = url.findtext(f"{{{SITEMAP_NS}}}loc")
        if loc:
            urls.append((loc.strip(), (url.findtext(f"{{{SITEMAP_NS}}}lastmod") or "").strip() or None))
    return urls


def dedupe(urls: list[tuple[str, str | None]]) -> tuple[list[tuple[str, str | None]], int, int]:
    """Canonicalize every loc, then collapse duplicates onto the newest lastmod.

    Duplicates are what an incremental render leaves behind (see the module
    docstring); on a full render there are none.
    """
    merged: dict[str, str | None] = {}
    normalized = 0
    for loc, lastmod in urls:
        key = canonical(loc)
        if key != loc:
            normalized += 1
        prior = merged.get(key, ...)
        if prior is ...:
            merged[key] = lastmod
        else:
            # ISO-8601 UTC throughout, so lexical order is chronological.
            merged[key] = max(filter(None, (prior, lastmod)), default=None)
    return list(merged.items()), normalized, len(urls) - len(merged)


def build(
    sitemap: Path, site_dir: Path, base_path: str
) -> tuple[str, dict[str, int], list[str], list[str]]:
    urls, normalized, collapsed = dedupe(read_urls(sitemap))

    ET.register_namespace("", SITEMAP_NS)
    ET.register_namespace("image", IMAGE_NS)
    root = ET.Element(f"{{{SITEMAP_NS}}}urlset")

    images = pages = 0
    missing: list[str] = []
    thumbs: list[str] = []

    for loc, lastmod in urls:
        url_el = ET.SubElement(root, f"{{{SITEMAP_NS}}}url")
        ET.SubElement(url_el, f"{{{SITEMAP_NS}}}loc").text = loc
        if lastmod:
            ET.SubElement(url_el, f"{{{SITEMAP_NS}}}lastmod").text = lastmod

        page = output_file(loc, base_path, site_dir)
        if not page.exists():
            missing.append(f"{loc} (no {page.relative_to(site_dir)})")
            continue

        parser = BodyImages()
        parser.feed(page.read_text(encoding="utf-8", errors="replace"))
        found = 0
        for src in parser.srcs:
            img_url = urljoin(loc, src)
            img_file = output_file(img_url, base_path, site_dir)
            if not img_file.exists():
                missing.append(f"{img_url} (referenced by {loc})")
                continue
            if THUMB_MARKER in img_file.name:
                thumbs.append(f"{img_url} (on {loc})")
            image_el = ET.SubElement(url_el, f"{{{IMAGE_NS}}}image")
            ET.SubElement(image_el, f"{{{IMAGE_NS}}}loc").text = img_url
            found += 1
        images += found
        pages += 1 if found else 0

    ET.indent(root, space="  ")
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"
    stats = {
        "urls": len(urls),
        "images": images,
        "pages": pages,
        "normalized": normalized,
        "collapsed": collapsed,
    }
    return xml, stats, missing, thumbs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--site-dir",
        type=Path,
        default=None,
        help="rendered output directory (default: $QUARTO_PROJECT_OUTPUT_DIR, else _site)",
    )
    ap.add_argument("--dry-run", action="store_true", help="report without writing")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    site_dir = args.site_dir or Path(os.environ.get("QUARTO_PROJECT_OUTPUT_DIR") or ROOT / "_site")
    site_dir = site_dir if site_dir.is_absolute() else (ROOT / site_dir)
    sitemap = site_dir / "sitemap.xml"

    if not sitemap.exists():
        # No `site-url` means no sitemap, which is a valid configuration --
        # nothing to do rather than a failure.
        if not args.quiet:
            print(f"sitemap: none at {sitemap}, skipped")
        return 0

    base_path = urlsplit(site_url(ROOT / "_quarto.yml")).path.rstrip("/")
    xml, stats, missing, thumbs = build(sitemap, site_dir, base_path)

    if not args.dry_run:
        sitemap.write_text(xml, encoding="utf-8")

    for note in missing:
        print(f"sitemap: missing {note}", file=sys.stderr)
    if thumbs:
        print(
            f"sitemap: WARNING -- {len(thumbs)} thumbnail(s) declared. A Quarto upgrade "
            f"has probably renamed one of {sorted(SKIP_CLASSES)}; check SKIP_CLASSES "
            "in this script. Not fatal, and the sitemap was still written.",
            file=sys.stderr,
        )
        for note in thumbs[:5]:
            print(f"sitemap:   {note}", file=sys.stderr)
        if len(thumbs) > 5:
            print(f"sitemap:   … and {len(thumbs) - 5} more", file=sys.stderr)

    if not args.quiet:
        detail = f"{stats['urls']} urls, {stats['images']} images on {stats['pages']} pages"
        for label, key in (("normalized", "normalized"), ("deduped", "collapsed")):
            if stats[key]:
                detail += f", {stats[key]} {label}"
        print(f"sitemap: {'would write ' if args.dry_run else ''}{detail}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
