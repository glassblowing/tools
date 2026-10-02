# Contributing

Every listing is a Markdown file with YAML front matter. You don't need to write any HTML.

## Add a tool

Create `_tools/<maker>-<tool-name>.md`:

```yaml
---
title: Standard Diamond Shears
maker: jim-moore          # filename (without .md) of a file in _makers/
category: shears          # filename of a file in _tool_categories/
disciplines: [furnace]    # any of: furnace, flameworking, coldworking
summary: One or two sentences shown on cards and at the top of the page.
added: 2026-09-29         # used for "Recently added" on the home page
last_checked: 2026-09-29  # when the buy links were last verified (optional)
image: https://example.com/product-photo.jpg   # optional; the seller's own image URL, or a photo you took
image_credit: Jim Moore Glass Tools   # required with image; shown as "Photo: ..."
image_source: https://example.com/product   # optional; the credit links here
specs:                    # optional, free-form key/value pairs
  Material: Tool steel
buy:
  - vendor: Shops at the Corning Museum of Glass
    url: https://example.com/product
    note: Optional short note, e.g. "also sells replacement blades"
reviews: []
---

Optional longer description in Markdown.
```

If the maker or category doesn't exist yet, add a file in `_makers/` or `_tool_categories/`. Copy an existing one.

## Photos

Listing photos link to the seller's own product image (we don't copy or host vendor photos), and every photo shows a credit linking back to the seller. `make photos` fills these in automatically. If you took a photo yourself, add it under `assets/img/tools/` and credit yourself.

Makers and shops: if you'd rather we didn't show your photos, open an issue and we'll take them down.

## Add a review

Reviews come in through the "Review a tool" issue form. To publish one, add it to the tool's `reviews:` list and reference the issue in your PR:

```yaml
reviews:
  - author: Sam R.
    experience: Hot shop, 6 years   # optional
    rating: 4                       # 1–5
    date: 2026-09-29
    body: |
      Markdown is fine here.
```

The page works out the average rating itself.

## Run locally

With podman or docker installed:

```sh
make serve      # build with the same image GitHub Pages uses, then open http://localhost:4000
make check      # validate the data and build; run this before opening a pull request
make            # list every task (links, photos, catalog, geocode, ...)
```

Or with Ruby: `bundle install && bundle exec jekyll serve`.

Pushing to `main` deploys to GitHub Pages via `.github/workflows/jekyll-gh-pages.yml`.
