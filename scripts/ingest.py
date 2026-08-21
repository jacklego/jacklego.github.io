# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow"]
# ///
"""Turn photos dropped in `_inbox/` into finished carving pages.

Peter renames a photo to the carving's name and drags it into `_inbox/` through
the GitHub web UI. This script pairs it with an optional sidecar, derives the
front matter from `carving.py`, builds the two derived image sizes, writes
`index.qmd`, and reports what it had to guess.

Design rules, in order of importance:

  1. Peter's input never fails the run. Unknown categories are dropped, an
     unparseable sidecar is ignored in favour of the filename, a missing EXIF
     date falls back. Every degradation becomes a review flag, not an error.
  2. Incomplete input is a no-op, not a failure. Creating a sidecar and
     uploading a photo through the web UI easily lands as two commits, firing
     this twice; the first run must exit clean.
  3. Re-running is safe. An existing target directory is skipped unless
     --force, which is what makes the workflow idempotent.

Usage:
  uv run scripts/ingest.py [--dry-run] [--force] [--inbox DIR] [--summary FILE]
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageOps

sys.path.insert(0, str(Path(__file__).resolve().parent))
import carving  # noqa: E402
import sync_drafts  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

# Files in the inbox that are furniture, not input.
FURNITURE = {"readme.md", "template.txt", "template.yml", "template.md",
             ".gitkeep"}

# Derived image tiers, matching what is already committed exactly. Verified with
# `identify` across all 148 pages: web copies are 2400px long-edge at Q82,
# thumbnails 1200px at Q80, both stripped, progressive, 4:2:0.
WEB_EDGE, WEB_QUALITY = 2400, 82
THUMB_EDGE, THUMB_QUALITY = 1200, 80

BOOL_TRUE = {"yes", "y", "true", "t", "1", "on"}
SIDECAR_KEYS = {
    "name", "title", "categories", "category", "source", "logo", "medium",
    "off-theme", "offtheme", "note", "notes", "order", "slug", "year", "date",
    "group",
    # `source-file:` names the photo this sidecar belongs to. It is the only key
    # read before the pairing is decided -- see `collect()`.
    "source-file", "source_file", "sourcefile", "photo", "file",
    # The template asks for `source-material:`, which reads as English next to
    # `source-file:`; `source:` is the front matter key and still accepted.
    "source-material", "source_material", "sourcematerial",
}

# Aliases for `source-file:`, in the order they are consulted.
SOURCE_FILE_KEYS = ("source-file", "source_file", "sourcefile", "photo", "file")

# Aliases for the work a carving is from, written to front matter as
# `meta.source`. The template's spelling comes first.
SOURCE_KEYS = ("source-material", "source_material", "sourcematerial", "source")


# --------------------------------------------------------------------------
# reading the inbox
# --------------------------------------------------------------------------

def mime_type(path: Path) -> str:
    """Classify by content, never by extension.

    `_local/audit-images.sh` uses the same call, and it is what caught
    non-pumpkins/om/om.jpg being an AVIF file wearing a .jpg extension. Here it
    also means a sidecar works whatever Notepad named it -- `notes.txt`,
    `frankenstein.yml`, `frankenstein.yml.txt`, or no extension at all.
    """
    try:
        out = subprocess.run(
            ["file", "-b", "--mime-type", str(path)],
            capture_output=True, text=True, check=True,
        )
        return out.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "application/octet-stream"


def split_counter(stem: str) -> tuple[str, int] | None:
    """`Frankenstein (1931) 2` -> `("Frankenstein (1931)", 2)`, or None."""
    m = re.match(r"^(.*?)[ _-]+(\d{1,2})$", stem)
    if m and m.group(1).strip():
        return m.group(1).strip(), int(m.group(2))
    return None


def base_stem(stem: str, known: set[str]) -> tuple[str, int]:
    """Group extra photos of one carving with their main image.

    A trailing number only counts as a photo counter when some other file in the
    inbox carries the bare stem -- otherwise "Apollo 13" would silently become
    the thirteenth photo of a carving called "Apollo", and the name would lose
    its number. `known` is the set of stems present, so the decision is made
    from what was actually uploaded rather than from the shape of one name.
    """
    split = split_counter(stem)
    if split and split[0].lower() in known:
        return split
    return stem.strip(), 0


def read_sidecar(path: Path) -> tuple[dict, list[str]]:
    """Parse a sidecar as leniently as possible.

    Deliberately not PyYAML. Every tolerance below is a real failure mode for
    someone editing a text file on Windows, and a strict parser would answer
    each one with a message that means nothing to Peter:

      - a UTF-8 BOM, which Notepad writes by default, breaks strict YAML on the
        very first key
      - cp1252 bytes when the file was not saved as UTF-8 at all
      - curly quotes and dashes from Word or WordPad autocorrect
      - `---` fences present or absent
      - `categories: Horror, Monsters` with no brackets
      - CRLF line endings
    """
    flags: list[str] = []
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return {}, [f"could not read sidecar {path.name}: {exc}"]

    text = None
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        return {}, [f"could not decode sidecar {path.name}"]

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Drop front matter fences if present; keep the body either way.
    parts = text.split("---")
    if text.lstrip().startswith("---") and len(parts) >= 3:
        text = parts[1]

    data: dict[str, str] = {}
    for line in text.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = carving.clean_text(key).lower().strip().strip("-* ")
        value = carving.clean_text(value.split(" #")[0]).strip().strip('"').strip("'")
        if not key or key not in SIDECAR_KEYS:
            if key:
                flags.append(f"ignored unknown sidecar key `{key}`")
            continue
        if value:
            data[key] = value
    return data, flags


def as_bool(value: str | None) -> bool:
    return bool(value) and value.strip().lower() in BOOL_TRUE


def parse_categories(value: str | None) -> tuple[list[str], list[str]]:
    """Match against the closed set of 17, case- and order-insensitively.

    Returns the recognized tags in canonical (most-specific-first) order plus
    whatever was not recognized, which becomes a review flag rather than an
    error -- an unknown tag would otherwise pollute the Everything page's filter.
    """
    if not value:
        return [], []
    value = value.strip().strip("[]")
    wanted = [v.strip() for v in re.split(r"[,;]", value) if v.strip()]
    lookup = {c.lower(): c for c in carving.CATEGORIES}
    lookup["pirates and skulls"] = "Pirates & Skulls"
    good, bad = [], []
    for w in wanted:
        hit = lookup.get(w.lower())
        if hit:
            good.append(hit)
        else:
            bad.append(w)
    good = [c for c in carving.CATEGORIES if c in good]
    return good, bad


# --------------------------------------------------------------------------
# images
# --------------------------------------------------------------------------

def magick() -> str:
    for exe in ("magick", "convert"):
        if shutil.which(exe):
            return exe
    raise SystemExit("ImageMagick not found: install `imagemagick`")


def resize(src: Path, dest: Path, edge: int, quality: int) -> None:
    """One derived image, to the recipe the repo already uses.

    `-auto-orient` matters: some originals carry an EXIF rotation that `-strip`
    would otherwise discard, leaving the photo sideways. The `>` on the geometry
    prevents upscaling, so an original already under `edge` is just re-encoded.
    """
    exe = magick()
    args = [exe]
    if exe == "magick":
        args.append("convert")
    args += [
        str(src), "-auto-orient", "-resize", f"{edge}x{edge}>", "-strip",
        "-interlace", "Plane", "-sampling-factor", "4:2:0",
        "-quality", str(quality), str(dest),
    ]
    subprocess.run(args, check=True, capture_output=True)


def probe(path: Path) -> tuple[str | None, float | None]:
    """EXIF capture timestamp and true aspect ratio of an original.

    Dimensions are read after `exif_transpose`, matching the `-auto-orient` the
    derived images get, so a portrait photo tagged as rotated reports < 1.
    """
    try:
        with Image.open(path) as img:
            exif = img.getexif()
            # 36867 DateTimeOriginal lives in the Exif sub-IFD (0x8769); Pillow
            # flattens it into the top level for most JPEGs but not all, so try
            # both before falling back to 306 DateTime.
            sub = exif.get_ifd(0x8769) or {}
            raw = exif.get(36867) or sub.get(36867) or exif.get(306)
            w, h = ImageOps.exif_transpose(img).size
    except Exception:
        return None, None
    captured = None
    if raw:
        m = re.match(r"(\d{4})[:\-](\d{2})[:\-](\d{2})[ T](\d{2}):(\d{2}):(\d{2})", str(raw))
        if m:
            y, mo, d, hh, mm, ss = m.groups()
            captured = f"{y}-{mo}-{d}T{hh}:{mm}:{ss}"
    ratio = round(w / h, 4) if w and h else None
    return captured, ratio


# --------------------------------------------------------------------------
# writing the page
# --------------------------------------------------------------------------

def quote(value: str) -> str:
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"') + '"'


# Keys the committed pages write as bare scalars. Everything else is quoted, so
# an apostrophe or a colon in a title can never break the front matter.
BARE = {"date", "order", "extras", "year", "image", "full",
        "raw-aspect-ratio", "medium"}


def render_qmd(fm: dict, meta: dict, body: str) -> str:
    def emit(key, value, indent=""):
        if isinstance(value, bool):
            return f"{indent}{key}: {str(value).lower()}"
        if isinstance(value, list):
            return f"{indent}{key}: [{', '.join(value)}]"
        if isinstance(value, (int, float)) or key in BARE:
            return f"{indent}{key}: {value}"
        return f"{indent}{key}: {quote(value)}"

    lines = ["---"]
    lines += [emit(k, v) for k, v in fm.items() if v is not None]
    if meta:
        lines += ["", "meta:"]
        lines += [emit(k, v, "  ") for k, v in meta.items() if v is not None]
    lines += ["", "---", "", body, ""]
    return "\n".join(lines)


def existing_pagetitles() -> dict[str, str]:
    out = {}
    for qmd in list(ROOT.glob("pumpkins/*/*/index.qmd")) + list(
        ROOT.glob("non-pumpkins/*/index.qmd")
    ):
        m = re.search(r"^pagetitle:\s*(.+)$", qmd.read_text(encoding="utf-8"), re.M)
        if m:
            out[m.group(1).strip().strip('"')] = str(qmd.parent.relative_to(ROOT))
    return out


def next_order(parent: Path, assigned: dict[Path, int]) -> int:
    """The next `order:` in a season -- an append, never a renumber.

    `assigned` carries the orders handed out earlier in this same run, so a batch
    of several photos numbers correctly and --dry-run reports the same numbers a
    real run would use.
    """
    orders = [assigned.get(parent, 0)]
    for qmd in parent.glob("*/index.qmd"):
        m = re.search(r"^order:\s*(\d+)", qmd.read_text(encoding="utf-8"), re.M)
        if m:
            orders.append(int(m.group(1)))
    nxt = max(orders) + 1
    assigned[parent] = nxt
    return nxt


YEAR_INDEX = """---
title: "{year}"
pagetitle: "{year} pumpkin carvings"
description: ""
date: {year}-10-31
listing:
  contents: ./*/index.qmd
  sort: "order asc"
  type: grid
  fields: [title, image]
  field-types:
    extras: number
  categories: false
  sort-ui: false
  filter-ui: false
  grid-columns: 2
page-layout: full
body-classes: patch-listing
image: {thumb}
---
"""


# --------------------------------------------------------------------------
# the pipeline
# --------------------------------------------------------------------------

def pick(sidecar: dict, *keys: str) -> str | None:
    """The first key present with a non-empty value, or None."""
    for key in keys:
        if sidecar.get(key):
            return sidecar[key]
    return None


def declared_photo(sidecar: dict) -> str | None:
    """The photo a sidecar says it belongs to, from `source-file:` or an alias."""
    value = pick(sidecar, *SOURCE_FILE_KEYS)
    if value is None:
        return None
    # Tolerate a pasted path: the web UI shows `_inbox/Frankenstein.jpg`.
    return value.replace("\\", "/").rstrip("/").split("/")[-1].strip()


def collect(inbox: Path) -> tuple[list[dict], list[str]]:
    """Group inbox contents into carvings, by MIME then by name.

    Pairing a sidecar with its photo is tried three ways, most explicit first:

      1. `source-file: Frankenstein (1931).jpg` inside the sidecar. This is the
         only one that works when several photos arrive in one commit, so the
         template asks for it and README mandates it for a multi-photo upload.
         A value naming no uploaded photo is *not* guessed at -- the sidecar is
         skipped and flagged, because a wrong pairing writes the wrong prose
         onto a page and reads as correct.
      2. an exact stem match, `frankenstein.txt` beside `Frankenstein.jpg`.
      3. one photo and one sidecar, whatever they are called -- the case where
         insisting on either of the above would be ceremony.
    """
    notes: list[str] = []
    images: dict[str, list[tuple[int, Path]]] = {}
    sidecar_stems: dict[Path, str] = {}

    usable = [
        p for p in sorted(inbox.iterdir())
        if not p.is_dir()
        and not p.name.startswith(".")
        and p.name.lower() not in FURNITURE
    ]
    # Stems present verbatim, so a trailing number can be recognized as a photo
    # counter only when there is a main photo for it to count against.
    known = {p.stem.strip().lower() for p in usable}

    for path in usable:
        stem, index = base_stem(path.stem, known)
        if mime_type(path).startswith("image/"):
            images.setdefault(stem, []).append((index, path))
        else:
            # A list, not a stem-keyed dict: two sidecars can now legitimately
            # share a stem (`notes.txt`, `notes 2.txt`) and be told apart by
            # their `source-file:` lines.
            sidecar_stems[path] = stem

    # Read each candidate once for its pairing key only; `build()` re-reads the
    # file for everything else, so parse flags are reported against the carving.
    declared = {path: declared_photo(read_sidecar(path)[0])
                for path in sidecar_stems}

    # Every name a photo answers to -> the group it belongs to, so
    # `source-file: Frankenstein 2.jpg` resolves to the Frankenstein carving.
    photo_names: dict[str, str] = {}
    for stem, group in images.items():
        for _, photo in group:
            photo_names[photo.name.strip().lower()] = stem
            photo_names[photo.stem.strip().lower()] = stem

    paired: dict[str, Path] = {}
    leftover: list[Path] = []
    orphans: list[tuple[Path, str]] = []

    # 1. the declared pairing
    for path, want in declared.items():
        if not want:
            leftover.append(path)
            continue
        stem = photo_names.get(want.lower()) or photo_names.get(Path(want).stem.strip().lower())
        if stem is None:
            orphans.append((path, f"`source-file: {want}` names no uploaded photo"))
        elif stem in paired:
            orphans.append((path, f"`source-file: {want}` names a photo already "
                                  f"claimed by `{paired[stem].name}`"))
        else:
            paired[stem] = path

    # 2. exact stem match
    for path in list(leftover):
        stem = sidecar_stems[path]
        hit = next((s for s in images if s.lower() == stem.lower()), None)
        if hit is not None and hit not in paired:
            paired[hit] = path
            leftover.remove(path)

    # 3. the single-photo, single-sidecar case, so Peter never has to make the
    #    two filenames agree when there is nothing to confuse them with. A
    #    `source-file:` that matched nothing is forgiven here rather than
    #    dropping the only sidecar uploaded -- with one photo there is nothing
    #    else it could belong to, and the likeliest cause is an uncommented
    #    example line left in a copy of TEMPLATE.txt.
    pair_flags: dict[str, list[str]] = {}
    if len(images) == 1 and len(sidecar_stems) == 1 and not paired:
        only = next(iter(images))
        if leftover:
            paired[only] = leftover.pop()
        else:
            path, reason = orphans.pop()
            paired[only] = path
            pair_flags[only] = [f"paired the only sidecar uploaded even though "
                                f"{reason} -- check it belongs to this carving"]

    for path in leftover:
        orphans.append((path, "no `source-file:` line, and its name matches no photo"))

    orphan_names = sorted("`" + p.name + "`" for p, _ in orphans)
    items = []
    for stem, group in images.items():
        group.sort()
        sidecar = paired.get(stem)
        flags = pair_flags.get(stem, [])
        # Surfaced on the carving that went without: the sidecar itself gets no
        # issue of its own, and a dropped sidecar is otherwise invisible.
        if sidecar is None and orphan_names:
            flags.append(
                "unmatched sidecar%s in this upload (%s) -- if one of them "
                "belongs here, give it a `source-file:` line naming the photo"
                % ("s" if len(orphan_names) != 1 else "", ", ".join(orphan_names))
            )
        items.append({
            "stem": stem,
            "main": group[0][1],
            "extras": [p for _, p in group[1:]],
            "sidecar": sidecar,
            "pair_flags": flags,
        })

    for path, reason in orphans:
        notes.append(f"sidecar `{path.name}` skipped -- {reason} -- left in place")
    return items, notes


def build(item: dict, args, pagetitles: dict[str, str],
          assigned: dict[Path, int]) -> dict:
    """Process one carving. Returns a report; writes files unless --dry-run."""
    flags: list[str] = []
    sidecar, sflags = read_sidecar(item["sidecar"]) if item["sidecar"] else ({}, [])
    flags += sflags
    if not item["sidecar"]:
        flags.append("no sidecar -- categories need filling in")
    flags += item.get("pair_flags") or []

    name = carving.clean_text(sidecar.get("name") or sidecar.get("title") or item["stem"])
    # A sidecar `slug:` is normalized too, so `slug: My Thing` cannot produce a
    # directory with spaces in it. Slugifying a proper slug is a no-op.
    slug = carving.slugify(sidecar.get("slug") or name)
    if not slug:
        slug = "untitled"
        flags.append(f"could not make a directory name from `{name}` -- used `untitled`")
    medium = (sidecar.get("medium") or "").lower() or None
    if medium in ("pumpkin", ""):
        medium = None
    logo = as_bool(sidecar.get("logo"))
    source = pick(sidecar, *SOURCE_KEYS)
    group = as_bool(sidecar.get("group"))

    categories, unknown = parse_categories(
        sidecar.get("categories") or sidecar.get("category")
    )
    if unknown:
        flags.append("unrecognized categories dropped: " + ", ".join(unknown))

    captured, ratio = item.get("captured"), item.get("ratio")
    if not captured:
        fallback = sidecar.get("date")
        if fallback and re.match(r"\d{4}-\d{2}-\d{2}", fallback):
            captured = f"{fallback[:10]}T12:00:00"
            flags.append("no EXIF date; used the date from the sidecar")
        else:
            captured = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
            flags.append("**no EXIF date and none supplied -- date is the upload time**")
    if ratio is None:
        flags.append("could not read image dimensions")

    year = sidecar.get("year") or captured[:4]
    if not re.match(r"^\d{4}$", str(year)):
        year = captured[:4]

    if medium:
        target = ROOT / "non-pumpkins" / slug
        order = int(sidecar.get("order") or next_order(target.parent, assigned))
    else:
        target = ROOT / "pumpkins" / str(year) / slug
        order = int(sidecar.get("order") or next_order(target.parent, assigned))

    report = {
        "name": name, "slug": slug, "path": str(target.relative_to(ROOT)),
        "year": str(year), "order": order, "categories": categories,
        "extras": len(item["extras"]), "flags": flags, "skipped": None,
        "source_files": [item["main"].name] + [p.name for p in item["extras"]],
    }

    if target.exists() and not args.force:
        report["skipped"] = f"{target.relative_to(ROOT)} already exists"
        return report

    # The prose year is the real one from `date:`, never the directory -- a year
    # directory is a grouping, so 2010/spiderman correctly says 2004.
    derived = carving.derive(
        name, source=source, logo=logo, medium=medium,
        year=captured[:4], group=group,
    )
    pagetitle = derived["pagetitle"]
    if pagetitle in pagetitles:
        version = 2
        while carving.version_suffix(pagetitle, version, year) in pagetitles:
            version += 1
        flags.append(
            f"pagetitle collided with {pagetitles[pagetitle]} -- versioned as v{version}; "
            "the earlier page needs the same treatment"
        )
        pagetitle = carving.version_suffix(pagetitle, version, year)
    pagetitles[pagetitle] = str(target.relative_to(ROOT))
    flags.append("check the article in `image-alt`")

    fm = {
        "title": name,
        "pagetitle": pagetitle,
        "description": derived["description"],
        "image": f"_{slug}__thumb.jpg",
        "image-alt": derived["image-alt"],
        "full": f"{slug}.jpg",
    }
    if item["extras"]:
        fm["extras"] = len(item["extras"])
    if medium:
        fm["year"] = int(year)
    fm["order"] = order
    fm["date"] = captured[:10]
    fm["categories"] = categories  # written even when empty, so the gap is visible

    meta = {}
    if source:
        meta["source"] = source
    if logo:
        meta["logo"] = True
    if medium:
        meta["medium"] = medium
    if as_bool(sidecar.get("off-theme") or sidecar.get("offtheme")):
        meta["off-theme"] = True
    meta["captured"] = captured
    if ratio is not None:
        meta["raw-aspect-ratio"] = f"{ratio:.4f}"
    if sidecar.get("note") or sidecar.get("notes"):
        meta["note"] = sidecar.get("note") or sidecar.get("notes")

    group_attr = f' group="{slug}"' if item["extras"] else ""
    body = (
        "![]({{< meta full >}}){fig-align=\"center\" "
        'fig-alt="{{< meta image-alt >}}"' + group_attr + "}"
    )
    if item["extras"]:
        cells = []
        for n, _ in enumerate(item["extras"], start=1):
            suffix = "" if n == 1 else f"-{n}"
            cells.append(
                f"![TODO caption](_alt{suffix}.jpg){{fig-alt=\"TODO describe this photo.\""
                f"{group_attr}}}"
            )
        body += "\n\n::: {layout-ncol=2}\n" + "\n\n".join(cells) + "\n:::"
        flags.append("extra photos need captions and `fig-alt` text")

    report["pagetitle"] = pagetitle
    report["description"] = derived["description"]
    report["image-alt"] = derived["image-alt"]
    report["date"] = captured[:10]

    if args.dry_run:
        report["qmd"] = render_qmd(fm, meta, body)
        return report

    target.mkdir(parents=True, exist_ok=True)
    resize(item["main"], target / f"{slug}.jpg", WEB_EDGE, WEB_QUALITY)
    resize(item["main"], target / f"_{slug}__thumb.jpg", THUMB_EDGE, THUMB_QUALITY)
    for n, extra in enumerate(item["extras"], start=1):
        suffix = "" if n == 1 else f"-{n}"
        resize(extra, target / f"_alt{suffix}.jpg", WEB_EDGE, WEB_QUALITY)
    (target / "index.qmd").write_text(render_qmd(fm, meta, body), encoding="utf-8")

    if not medium:
        year_index = target.parent / "index.qmd"
        thumb = f"{slug}/_{slug}__thumb.jpg"
        if not year_index.exists():
            year_index.write_text(
                YEAR_INDEX.format(year=year, thumb=thumb), encoding="utf-8"
            )
            report["created_year"] = str(year_index.relative_to(ROOT))
        else:
            # A year page created ahead of the first upload has no carving to
            # point `image:` at, and Quarto rejects an empty value -- so the key
            # is absent until the first carving arrives to fill it.
            body = year_index.read_text(encoding="utf-8")
            if not re.search(r"^image:\s*\S", body, re.MULTILINE):
                year_index.write_text(
                    re.sub(r"^(body-classes:.*)$", rf"\1\nimage: {thumb}", body,
                           count=1, flags=re.MULTILINE),
                    encoding="utf-8",
                )
                report["year_image"] = thumb
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--inbox", default="_inbox", type=Path)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="overwrite a carving directory that already exists")
    ap.add_argument("--summary", type=Path,
                    help="write a JSON report here for the workflow to read")
    args = ap.parse_args()

    inbox = args.inbox if args.inbox.is_absolute() else ROOT / args.inbox
    if not inbox.is_dir():
        print(f"no inbox at {inbox}", file=sys.stderr)
        return 2

    items, notes = collect(inbox)
    for note in notes:
        print(f"note: {note}")
    if not items:
        print("nothing to ingest")
        if args.summary:
            args.summary.write_text(json.dumps({"carvings": [], "notes": notes}, indent=1))
        return 0

    # A single commit carrying several photos has no recoverable upload order, so
    # `order:` follows capture time -- deterministic, and the likeliest sequence.
    for item in items:
        item["captured"], item["ratio"] = probe(item["main"])
    items.sort(key=lambda i: (i["captured"] or "9999", i["stem"]))

    pagetitles = existing_pagetitles()
    assigned: dict[Path, int] = {}
    reports = [build(item, args, pagetitles, assigned) for item in items]

    for r in reports:
        if r["skipped"]:
            print(f"\nSKIP {r['name']}: {r['skipped']}")
            continue
        print(f"\n{r['name']}  ->  {r['path']}")
        print(f"  order {r['order']}   date {r['date']}   "
              f"categories: {', '.join(r['categories']) or '(none)'}")
        print(f"  pagetitle:   {r['pagetitle']}")
        print(f"  description: {r['description']}")
        print(f"  image-alt:   {r['image-alt']}")
        if r.get("created_year"):
            print(f"  created {r['created_year']}")
        for flag in r["flags"]:
            print(f"  ! {flag}")
        if args.dry_run:
            print("\n" + "\n".join("    " + ln for ln in r["qmd"].splitlines()))

    if not args.dry_run and any(not r["skipped"] for r in reports):
        sync_drafts.main()

    if args.summary:
        args.summary.write_text(
            json.dumps({"carvings": reports, "notes": notes}, indent=1),
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
