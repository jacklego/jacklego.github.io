# jacklego.github.io (AKA Peter's Pumpkin Patch)

> ## 🎃 Peter: start here
> ### [How to put a pumpkin photo on the website](_how-to-add-a-pumpkin/README.md)
> That page is all you need. You can skip everything below it on this page.

## Other instructions in this repo

- [`_how-to-add-a-pumpkin/README.md`](_how-to-add-a-pumpkin/README.md): *Peter*. Photo to live site, step by step.
- [`_inbox/README.md`](_inbox/README.md): *Connor*. Details of the upload pipeline: extra photos, text files with details, season visibility.
- [`_inbox/TEMPLATE.txt`](_inbox/TEMPLATE.txt): *Connor, or Peter if Connor walks him through it*. The optional details file.
- `CLAUDE.md` (gitignored, local only): *Claude*. Design notes and gotchas for working on the site.

---

*(Past instructions. To be deleted.)*

## Homepage message: 
Edit in [_homepage-memo.md](_homepage-memo.md).

## To edit a year's image thumbnail: 
1. Go to the relevant year's `index.qmd` file
2. Edit the line that starts with `image: ` (should be near the bottom)
3. Change it to another thumbnail (_Note_: Make sure to match the formatting for the thumbnail: include the path and target the `__thumb` file)

## To build: 
1. Go to `Actions` tab in Github
2. On the left, click `Quarto Publish`
3. Click `run workflow` (from `Branch:main`)
