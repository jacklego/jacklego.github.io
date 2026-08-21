#!/usr/bin/env python3
"""Render `ingest.py`'s JSON summary for humans and for GitHub.

Three consumers, one source of truth:

  --commit-message   the bot commit's message
  --issues-dir DIR   two files per carving, `<n>-<slug>.title` and
                     `<n>-<slug>.body`, which the workflow feeds to `gh issue
                     create --assignee` -- the assignment is what notifies.
  --summary          markdown for $GITHUB_STEP_SUMMARY and for a comment on
                     Peter's own commit -- the only place the new page's URL
                     appears, since nothing on the site links to it yet

Stdlib only -- it runs in CI with no environment to set up.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


# A drafted season is excluded from every listing, so nothing on the site links
# to a new carving until go-live. These URLs are the only way Peter reaches his
# own photo, which makes them the most important thing this script emits.
SITE = "https://peterspumpkinpatch.org"


def url_for(path: str) -> str:
    return f"{SITE}/{path.strip('/')}/"


def load(path: Path) -> dict:
    if not path.exists():
        return {"carvings": [], "notes": []}
    return json.loads(path.read_text(encoding="utf-8"))


def built(data: dict) -> list[dict]:
    return [c for c in data.get("carvings", []) if not c.get("skipped")]


def commit_message(data: dict) -> str:
    made = built(data)
    if not made:
        return "No carvings ingested\n"
    if len(made) == 1:
        subject = f"Add {made[0]['name']} ({made[0]['path']})"
    else:
        subject = f"Add {len(made)} carvings"

    lines = [subject, ""]
    for c in made:
        lines.append(f"{c['name']} -> {c['path']}")
        lines.append(f"  from {', '.join(c['source_files'])}")
        lines.append(f"  order {c['order']}, date {c['date']}, "
                     f"categories: {', '.join(c['categories']) or 'none'}")
        lines.append(f"  pagetitle: {c['pagetitle']}")
        for flag in c.get("flags", []):
            lines.append(f"  ! {strip_md(flag)}")
        lines.append("")
    for note in data.get("notes", []):
        lines.append(f"note: {note}")
    for c in data.get("carvings", []):
        if c.get("skipped"):
            lines.append(f"skipped: {c['name']} -- {c['skipped']}")
    return "\n".join(lines).rstrip() + "\n"


def strip_md(text: str) -> str:
    return text.replace("**", "").replace("`", "")


def issue(c: dict) -> tuple[str, str]:
    """The review issue for one carving, as (title, body)."""
    rows = [
        ("slug", f"`{c['slug']}`", "derived"),
        ("order", c["order"], "upload order"),
        ("date", c["date"], "EXIF"),
        ("pagetitle", c["pagetitle"], "derived"),
        ("description", c["description"], "derived"),
        ("image-alt", c["image-alt"], "**check the article**"),
        (
            "categories",
            ", ".join(c["categories"]) or "*(none)*",
            "as given" if c["categories"] else "**needs tagging**",
        ),
    ]
    body = [
        f"### {c['name']} — `{c['path']}/`",
        "",
        "| field | value | |",
        "|---|---|---|",
    ]
    body += [f"| {k} | {v} | {note} |" for k, v, note in rows]

    other = [f for f in c.get("flags", [])
             if "check the article" not in f and "categories need filling" not in f]
    if other:
        body += ["", "**Flags**", ""] + [f"- {f}" for f in other]

    files = ", ".join("`" + s + "`" for s in c["source_files"])
    n_extra = c.get("extras") or 0
    tail = ""
    if n_extra:
        tail = " (+%d extra photo%s)" % (n_extra, "s" if n_extra != 1 else "")
    body += [
        "",
        f"Live at <{url_for(c['path'])}> once the site is published.",
        "",
        "Built from " + files + tail + ".",
        "",
        "- [ ] categories",
        "- [ ] prose reads right",
        "- [ ] original archived out of `_inbox/`",
        "",
        "<sub>Opened by the ingest workflow. Closing this marks the carving "
        "ready for go-live.</sub>",
    ]
    return (
        f"{c['name']} — review derived front matter",
        "\n".join(body) + "\n",
    )


def summary(data: dict) -> str:
    made = built(data)
    skipped = [c for c in data.get("carvings", []) if c.get("skipped")]
    if not made and not skipped and not data.get("notes"):
        return "## Ingest\n\nNothing to ingest — the inbox held no new photos.\n"

    out = ["## Ingest", ""]
    if made:
        out += [f"Built {len(made)} carving page{'s' if len(made) != 1 else ''}.", ""]
        for c in made:
            out.append(f"### {c['name']}")
            out.append("")
            out.append(f"**{url_for(c['path'])}**")
            out.append("")
            out.append(
                f"order {c['order']} · {c['date']} · "
                f"{', '.join(c['categories']) or 'no categories yet'}"
            )
            out.append("")
        out += [
            "To see these on the site, run the **Quarto Publish** workflow "
            "(Actions → Quarto Publish → Run workflow). Until then the pages "
            "exist in the repo but have not been deployed.",
            "",
            "The season is still private: these links work, but the carvings "
            "are deliberately absent from every list on the site, so "
            "`/pumpkins/2026/` will look empty until the year goes live.",
            "",
        ]
    for c in skipped:
        out.append(f"- **skipped** {c['name']} — {c['skipped']}")
    for note in data.get("notes", []):
        out.append(f"- {note}")
    return "\n".join(out) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("summary_json", type=Path)
    ap.add_argument("--commit-message", action="store_true")
    ap.add_argument("--summary", action="store_true")
    ap.add_argument("--issues-dir", type=Path)
    args = ap.parse_args()

    data = load(args.summary_json)
    if args.commit_message:
        sys.stdout.write(commit_message(data))
    if args.summary:
        sys.stdout.write(summary(data))
    if args.issues_dir:
        args.issues_dir.mkdir(parents=True, exist_ok=True)
        for n, c in enumerate(built(data), start=1):
            title, body = issue(c)
            stem = args.issues_dir / f"{n:02d}-{c['slug']}"
            stem.with_suffix(".title").write_text(title, encoding="utf-8")
            stem.with_suffix(".body").write_text(body, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
