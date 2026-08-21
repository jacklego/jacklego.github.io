"""Derivation rules for a carving page's front matter.

This module is the executable form of the conventions recorded in CLAUDE.md.
Both `ingest.py` and a local run import it, so CI and a laptop produce identical
output. Nothing here touches the network, and the only file it reads is
`categories.txt` beside it.

Three relations matter, and they are not equally mechanical:

  name (+ source, logo, medium)  ->  description   ~80% mechanical
  description subject clause     ->  pagetitle      144/148 mechanical
  name (+ source, logo, medium)  ->  image-alt      articles are editorial

`pagetitle` is derived from the *description*, never independently, because that
is the relation CLAUDE.md documents and the only one that reproduces the
existing pages exactly. `_local/test_carving.py` measures all three against the
148 committed pages (local-only; `_local/` is gitignored).

The one exception to "no filesystem" is the category list, which is read from
`scripts/categories.txt` at import time rather than hard-coded here.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

CATEGORIES_FILE = Path(__file__).with_name("categories.txt")


def load_categories(path: Path | str | None = None) -> list[str]:
    """Read the closed set of category tags, one per line.

    Blank lines and #-comments are skipped; every other line is a tag as
    written. File order is the canonical tag order for a carving's
    `categories:` list, most-specific-first.
    """
    lines = Path(path or CATEGORIES_FILE).read_text(encoding="utf-8").splitlines()
    tags = [t for t in (ln.strip() for ln in lines) if t and not t.startswith("#")]
    if not tags:
        raise ValueError(f"no categories found in {path or CATEGORIES_FILE}")
    return tags


# The closed set, most-specific-first, read from scripts/categories.txt. Order
# there is the canonical tag order for a carving's `categories:` list.
CATEGORIES = load_categories()

EM_DASH = "—"
_YEAR = re.compile(r"^\d{4}$")
_TRAILING_PAREN = re.compile(r"^(.*?)\s*\(([^()]*)\)$")

# Windows text editors and word processors introduce all of these.
_PUNCT_FIXES = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"',
    "–": "-", "—": "-", "―": "-",
    " ": " ", "…": "...",
}


def clean_text(s: str) -> str:
    """Normalize text that came off a Windows machine.

    Strips a UTF-8 BOM (Notepad writes one, and it breaks a strict YAML parser
    on the very first key), folds smart quotes and dashes back to ASCII, and
    collapses whn't need. Upload this file togeitespace. Applied to every value read from a sidecar or a
    filename before anything else looks at it.
    """
    if not isinstance(s, str):
        return s
    s = s.lstrip("﻿")
    s = unicodedata.normalize("NFC", s)
    for bad, good in _PUNCT_FIXES.items():
        s = s.replace(bad, good)
    return re.sub(r"\s+", " ", s).strip()


def split_paren(name: str) -> tuple[str, str | None]:
    """`Oddjob (Goldfinger)` -> `("Oddjob", "Goldfinger")`."""
    m = _TRAILING_PAREN.match(name)
    if not m:
        return name, None
    return m.group(1).strip(), m.group(2).strip()


def paren_work(name: str) -> str | None:
    """The trailing parenthetical, when it names a work rather than a year.

    A bare four-digit parenthetical is a release year, so it never becomes a
    "from" clause -- "Frankenstein from 1931" would be nonsense. The committed
    pages keep such a year in the subject itself (`Frankenstein (1931) -- a
    pumpkin carving ...`), which is what `subject()` does with it.
    """
    paren = split_paren(name)[1]
    if paren is None or _YEAR.match(paren):
        return None
    return paren


def same_work(a: str, b: str) -> str:
    """Whether two strings name the same work, ignoring a release year.

    `source: Frankenstein (1931)` on a carving titled `Frankenstein` is the work
    itself, not a character in it -- so the description must not read
    "Frankenstein from Frankenstein (1931)".
    """
    return split_paren(a)[0].strip().lower() == split_paren(b)[0].strip().lower()


def logo_stem(name: str) -> str:
    """`High Society Logo` -> `High Society`; the word is implied by the frame."""
    return re.sub(r"\s+Logo$", "", split_paren(name)[0], flags=re.IGNORECASE)


def slugify(name: str) -> str:
    """Directory and image-stem name.

    Reproduces the repo's convention as far as it is mechanical: drop a trailing
    parenthetical and a leading article, `&` -> `and`, elide apostrophes rather
    than turning them into separators, everything else to hyphens.

    It cannot reproduce the editorial shortenings -- `Ernst Stavro Blofeld (You
    Only Live Twice)` -> `blofeld`, `The Chronicles of Narnia` -> `narnia`,
    `20,000 Leagues Under the Sea` -> `20k-leagues` -- nor the hyphen-eliding in
    `Spider-Man` -> `spiderman`, which contradicts `Dr. Frank-N-Furter` ->
    `frank-n-furter`. Those come from the sidecar's `slug:` override or a rename
    during review.
    """
    s = clean_text(name)
    s = split_paren(s)[0]
    s = re.sub(r"^the\s+", "", s, flags=re.IGNORECASE)
    s = s.replace("&", " and ")
    s = s.replace("'", "").replace("’", "")
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def subject(name: str, source: str | None = None, logo: bool = False) -> str:
    """The clause a description opens with.

    A trailing parenthetical outranks `meta.source` as the "from" work, which is
    what makes the 2023 Bond season come out right: `Oddjob (Goldfinger)` with
    `source: James Bond` reads "Oddjob from Goldfinger", naming the film rather
    than the franchise.
    """
    if logo:
        return f"The {logo_stem(name)} logo"
    work = paren_work(name)
    if work:
        return f"{split_paren(name)[0]} from {work}"
    if source and not same_work(source, name):
        return f"{name} from {source}"
    return name


def description(
    name: str,
    *,
    source: str | None = None,
    logo: bool = False,
    medium: str | None = None,
    year: int | str,
    group: bool = False,
) -> str:
    med = medium or "pumpkin"
    subj = subject(name, source, logo)
    if group:
        return f"{subj} {EM_DASH} {med} carvings by Peter Wiegand, {year}."
    return f"{subj} {EM_DASH} a {med} carving by Peter Wiegand, {year}."


def description_subject(desc: str, medium: str | None = None) -> str | None:
    """Recover the subject clause from a rendered description.

    The inverse of `description()`, so `pagetitle()` can work off either a
    freshly derived description or one already committed to a page.
    """
    med = medium or "pumpkin"
    m = re.match(
        rf"^(.*) {EM_DASH} (?:a {re.escape(med)} carving|{re.escape(med)} carvings)"
        rf" by Peter Wiegand, \d{{4}}\.$",
        desc,
    )
    return m.group(1) if m else None


def image_alt(
    name: str,
    *,
    source: str | None = None,
    logo: bool = False,
    medium: str | None = None,
    group: bool = False,
) -> str:
    """Alt text for the photo.

    The one field that genuinely cannot be derived: the committed pages read
    "the Death Star", "a pirate skull", "Marvel's Spider-Man", "The Mummy" --
    article and possessive choices that depend on the subject, not on its
    grammar. This emits the bare form, and `ingest.py` always flags it for
    review.
    """
    med = medium or "pumpkin"
    lead = f"A group of {med}s carved with" if group else f"A {med} carved with"
    if logo:
        return f"{lead} the {logo_stem(name)} logo."
    work = paren_work(name) or source
    if work and same_work(work, name):
        # The carving is of the work itself, not a character in it.
        return f"{lead} imagery from {name}."
    return f"{lead} {subject(name, source, logo)}."


def pagetitle(
    subject_clause: str,
    *,
    name: str,
    medium: str | None = None,
    logo: bool = False,
) -> str:
    """Search phrasing, derived from the description's subject clause.

    Drops the trailing "from <work>" clause, so `Homer Simpson from The
    Simpsons` becomes "Homer Simpson pumpkin carving" -- but keeps it when the
    title is itself built on "from", or `Creature from the Black Lagoon` would
    collapse to "Creature" and lose the search term. Never contains the site
    name: Quarto appends `website.title` on its own.
    """
    med = medium or "pumpkin"
    subj = subject_clause.strip()
    if logo or subj.endswith(" logo"):
        # Keyed on the clause's shape rather than on `meta.logo`, which some
        # logo pages (non-pumpkins/uw-husky) do not set.
        subj = re.sub(r"^The\s+", "", subj)
    elif " from " not in name.lower():
        subj = re.sub(r",?\s+from\s+.*$", "", subj)
    subj = subj.rstrip(",")
    return f"{subj} {med} carving"


def version_suffix(pt: str, version: int, year: int | str) -> str:
    """Disambiguate a repeat carving: `... carving, v3, 2020`.

    Duplicate <title> tags across pages are a quality signal Google acts on, and
    subject-only phrasing collides on the carvings Peter has done more than once.
    """
    return f"{pt}, v{version}, {year}"


def derive(
    name: str,
    *,
    source: str | None = None,
    logo: bool = False,
    medium: str | None = None,
    year: int | str,
    group: bool = False,
) -> dict[str, str]:
    """Everything derivable from a carving's name, in one call."""
    desc = description(
        name, source=source, logo=logo, medium=medium, year=year, group=group
    )
    return {
        "title": name,
        "pagetitle": pagetitle(
            subject(name, source, logo), name=name, medium=medium, logo=logo
        ),
        "description": desc,
        "image-alt": image_alt(
            name, source=source, logo=logo, medium=medium, group=group
        ),
        "slug": slugify(name),
    }
