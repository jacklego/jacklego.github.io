# Adding a carving

Everything here gets turned into a page on the site automatically. You only ever
put files *in*; you never have to edit anything else.

## The short version

1. On your computer, rename the photo to the name of the carving —
   **`Frankenstein.jpg`** or **`Frankenstein (1931).jpg`**, for instance.
   Whatever you type becomes the title on the page.
3. On this page, click **Add file → Upload files**.
4. Drag the photo in.
5. Click **Commit changes**.

A minute or two later, a comment appears on the **_commit_** you just made with a
link to the new page.

## Seeing it on the site

Now the scaffolding for the page exists. To deploy it to the web:

5. Go to the **Actions** tab, pick **Quarto Publish** on the left, and press
   **Run workflow**.

Wait for the green tick and your link works.

## More than one photo of the same carving

Number the extras. `Frankenstein.jpg` is the main photo; `Frankenstein 2.jpg` and
`Frankenstein 3.jpg` become extra photos on the same page, and the page gets a
small "multiple photos" marker in the listing.

## Adding the details (optional)

If you want to set the categories or say what film it's from, make a plain text
file alongside the photo. Copy **`TEMPLATE.txt`**, fill in the lines you care
about, delete the rest, and drag it in *together with the photo* so they arrive
in one go.

Name it whatever you like. When you're uploading several photos at once, it's 
clearer if name of the text file matches the name of the photo file, e.g.
`Frankenstein.txt` alongside `Frankenstein.jpg`, but it isn't required.

You can also skip this and defer it for later.

## Visibility

A new season (year) is hidden until you're ready. Your pages are live once 
deployed, but they're left out of every list on the site. In other words, 
`peterspumpkinpatch.org/pumpkins/2026/` exists, but it shows a heading 
and nothing else (a hidden carving is hidden from that list too). If you 
want to view the page before the season is visibly published, use the links
from your commits. 

When you're ready, you can either tell Connor to publish the season, or do it 
yourself. 

### Publishing the Season

1. From the [project root](https://github.com/jacklego/jacklego.github.io/),
   edit the file named [`_variables.yml`](/_variables.yml). Change the following:
   
     (i) Set the `currentYear:` to the year you want published (there needs to
     be a space after the colon).
   
     (ii) Add an entry immediately following the last entry under `ptheme:`. This
     should include the current year, a colon + space, and a value (the theme).
     Make sure to replicate the spacing of the previous entries. For instance,
   `2026: Harry Potter Villains`.
2. Commit these changes. 
3. Go to the current year's folder (under `pumpkins`), and edit the file named
   `_metadata.yml`. Delete the line that says `draft: true`. Alternatively, you
   can simply delete this file.
4. Commit this change.
5. Deploy the site with the Github **Action**. 

## Things worth knowing

- **Don't shrink or edit the photo first.** Upload it exactly as it came off the
  camera or phone. The site makes its own smaller copies, and the original's
  timestamp metadata is what dates the page.
- **Windows won't let you put `:` in a filename.** If the name needs one
  (`Alien: Resurrection`), put it in the `name:` line of a `TEMPLATE.txt` copy
  instead.
- **Nothing you can do here breaks the site.** If something is wrong or missing,
  the page still gets built.
