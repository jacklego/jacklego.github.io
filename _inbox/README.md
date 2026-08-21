# Adding a carving

Everything here gets turned into a page on the site automatically. You only ever
put files *in*; you never have to edit anything else.

## The short version

1. On your computer, rename the photo to the name of the carving —
   **`Frankenstein.jpg`**, or **`Frankenstein (1931).jpg`** if you want the year
   shown. Whatever you type becomes the title on the page.
2. On this page, click **Add file → Upload files**.
3. Drag the photo in.
4. Click **Commit changes**.

A minute or two later, a comment appears **on the commit you just made** with a
link to the new page. Connor also gets a note asking him to check the wording.

## Seeing it on the site

Building the page and putting it on the web are two separate steps, so there is
one more click:

5. Go to the **Actions** tab, pick **Quarto Publish** on the left, and press
   **Run workflow**.

Wait for the green tick and your link works. (If you'd rather not do this bit,
just tell Connor and he'll publish.)

## More than one photo of the same carving

Number the extras. `Frankenstein.jpg` is the main photo; `Frankenstein 2.jpg` and
`Frankenstein 3.jpg` become extra photos on the same page, and the page gets a
small "multiple photos" marker in the listing.

## Adding the details (optional)

If you want to set the categories or say what film it's from, make a plain text
file alongside the photo. Copy **`TEMPLATE.txt`**, fill in the lines you care
about, delete the rest, and drag it in *together with the photo* so they arrive
in one go.

Name it whatever you like. `notes.txt` is fine. If the name matches the photo —
`Frankenstein.txt` next to `Frankenstein.jpg` — that's clearer when you're
uploading several at once, but it isn't required.

You can skip this entirely. Connor fills in the categories when he checks the
wording.

## Staying private

A new season is hidden until it's ready. Your pages are real and the links work,
but they're left out of every list on the site and search engines can't find
them. When you're happy with the whole set, tell Connor and he'll take the year
live.

One thing this means: **the season's own page will look empty.** Going to
`peterspumpkinpatch.org/pumpkins/2026/` shows a heading and nothing under it,
because a hidden carving is hidden from that list too. Use the links from your
commits until the year goes live — it's worth keeping them somewhere. Everything
appears at once when Connor flips the switch.

## Things worth knowing

- **Don't shrink or edit the photo first.** Upload it exactly as it came off the
  camera or phone. The site makes its own smaller copies, and the original's
  hidden date stamp is what dates the page.
- **Windows won't let you put `:` in a filename.** If the name needs one
  (`Alien: Resurrection`), put it in the `name:` line of a `TEMPLATE.txt` copy
  instead.
- **Nothing you can do here breaks the site.** If something is wrong or missing,
  the page still gets built and Connor gets told what to look at.
