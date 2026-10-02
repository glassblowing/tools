---
name: update-archive
description: Refresh the glassblowing.tools archive from its vendors. Re-checks every buy link, scans each vendor's catalog for new in-scope tools, and adds or updates listings. Use when asked to update, refresh, or sync the archive, check for new tools or broken links, or add a new vendor or shop (e.g. "add https://example.com").
argument-hint: "[vendor-id | add <url> | links]"
---

# Update the archive

The archive is a catalog, not a store. Its value is that it's accurate and trustworthy, so follow these rules on every run:

- **Only list what a vendor actually shows.** Every tool, spec, and link must come from a page you fetched this run. If you can't load a page, say so. Don't fill gaps from memory.
- **Write summaries in your own words.** One or two plain sentences on what the tool is for. Don't paste vendor marketing copy.
- **No prices or reviews. Photos are linked, never copied.** Prices go stale, and reviews only come from people through the GitHub issue form. For photos, run `python3 scripts/archive.py photos --write`. It points each listing's `image` at the seller's own product image URL (hotlinked, never downloaded), with `image_credit` and `image_source`. Never add a vendor photo by hand, and never for a vendor marked `photos: no` (they asked us not to).
- **The site covers furnace (hot shop) glassblowing.** Flameworking and coldworking tools are out of scope for now. Existing ones are kept with `published: false` so they can come back later; don't add new ones.
- **Respect scope.** Each vendor's `scope` in `_data/vendors.yml` says what to index. Skip anything out of scope, and don't add it "for later".
- **Don't push or merge.** Work on a branch and leave pushing and PRs to the user.

## Files

| Path | What it is |
|---|---|
| `_data/vendors.yml` | Every shop, with its crawl pages, scope, and notes. The source of truth for vendors. |
| `_tools/*.md` | One file per tool. The format is in `CONTRIBUTING.md`. |
| `_makers/*.md`, `_tool_categories/*.md` | Makers and categories that tools reference by filename. |
| `scripts/archive.py` | Helper: `validate`, `links [--vendor ID]`, `catalog VENDOR_ID` (Shopify, WooCommerce, Squarespace), `photos [--vendor ID] [--refresh] [--write]`. |

## What to run

Parse the arguments:

- no argument: full run (steps 1–5 for every vendor)
- a vendor id: steps 1–5 for that vendor only
- `links`: steps 1, 2, and 5 only
- `add <url>`: add a new vendor (see below), then steps 3–5 for it

### 1. Start clean

```sh
git switch -c archive-update-$(date +%F)   # or reuse the current non-main branch
python3 scripts/archive.py validate
```

Fix any validation errors first.

### 2. Re-check existing buy links

```sh
python3 scripts/archive.py links            # add --vendor ID to limit
```

For each result that isn't `ok`:

- **404 / gone.** Search the vendor's site for the same product (Shopify stores: run `catalog`, or try `<store>/search?q=<name>`). If it moved, update the URL. If it's discontinued, remove that `buy` entry. If a tool has no buy links left, keep the file with `buy: []` and mention it in the report. Don't delete tools.
- **moved (redirect).** Update to the final URL if it's the same product.
- **limit (429).** The site throttled the checker; the page isn't necessarily gone. Recheck those URLs later, slowly. Never remove a link just for a 429. Shopify stores share one queue in the checker because Shopify rate-limits across all of its stores.
- **403 / timeouts.** Check the vendor's `notes` first; some block scripts (e.g. the Corning Museum shops). Try WebFetch once. If it's still blocked, leave the link, don't set `last_checked` for that tool, and list it under "needs a human to check".

Set `last_checked` to today only on tools whose links all returned `ok` this run.

### 3. Find new tools

For each vendor with `crawl` pages:

- `platform: shopify | woocommerce | squarespace`: run `python3 scripts/archive.py catalog <id>`. It prints every product in the crawl pages with its description and options, and whether it's already indexed. "(no description on the vendor page)" is a real result, not a failure. Write a minimal summary from the name and options, and don't invent details.
- Anything else: read each crawl page with WebFetch (or curl), then the product pages it links to.
- Before trusting `crawl`, check the vendor's sitemap (`/sitemap.xml`) for store collections that were added since the last run, and add any in-scope ones to `crawl`.

Decide what to add using the vendor's `scope.in` / `scope.out`. If an item is borderline, leave it out and list it in the report for the user to decide.

Retailers (vendors without `maker`) with empty `crawl` are only buy links. Don't index their whole catalog. When you add a tool, check whether any registered retailer also sells it, and add those buy links too.

### 4. Write or update listings

One file per product page. Collapse variants (lengths, body material, grips) into `specs`. Don't create a file per variant.

- **Filename:** `_tools/<maker-slug>-<product-slug>.md`, lowercase and hyphenated, e.g. `spiral-arts-standard-workhorse-pipe.md`.
- **title:** the product name, cleaned up. Put catalog numbers such as `PI-SW` in `specs.Model`, not the title.
- **maker / category:** existing slugs. If no category fits, create one in `_tool_categories/` (title, order, icon, summary, one-paragraph body) and mention it in the report. Create a `_makers/` file for a new maker, using only facts you can source.
- **disciplines:** any of `furnace`, `flameworking`, `coldworking`.
- **specs:** short factual key/values from the vendor page: Model, Body, Head, Length, Grip, Dimensions, and so on. Use inches the way the vendor does.
- **added:** today, for new files only. Don't change it on existing ones.
- **buy[].vendor:** must exactly match a `name` in `_data/vendors.yml`. The site adds "Direct from the maker" by itself when the vendor's `maker` matches.
- Keep `reviews:` as it is. New files get `reviews: []`.
- The Markdown body is optional. Add one only when there's a genuinely useful fact beyond the summary, like a care note or what it pairs with.

When updating an existing tool, change only what the vendor's page contradicts, and keep other people's edits.

After writing listings, run `python3 scripts/archive.py photos --write` to link photos for any new listing. It skips pages shared by several listings (catalog and category pages) and site logos, so a missing photo is normal.

### 5. Verify and report

```sh
python3 scripts/archive.py validate
podman run --rm -v "$PWD":/src:Z,ro -v /tmp/gbt-site:/out:Z -e PAGES_REPO_NWO=glassblowing/tools -e JEKYLL_NO_GITHUB=1 \
  --entrypoint sh ghcr.io/actions/jekyll-build-pages:v1.0.13 \
  -c 'cd / && bundle exec github-pages build --source /src --destination /out'
```

(`mkdir -p /tmp/gbt-site` first. `docker` works in place of `podman`. This is the same image the deploy uses. If neither is available, say the build wasn't verified.)

Commit on the branch with a message like `archive: Update from vendors (YYYY-MM-DD)`, then report:

- **Added:** tools, per vendor
- **Updated:** fixed or moved links, changed specs
- **Removed:** buy links for discontinued products
- **Skipped:** borderline items you left out
- **Needs a human:** blocked links and anything uncertain

## Adding a vendor (`add <url>`)

1. Fetch the home page and navigation, and work out what they sell and what platform the store runs on:
   - Shopify: `<url>/products.json` returns JSON. `crawl` = collection URLs.
   - WooCommerce: `<url>/wp-json/wc/store/v1/products` returns JSON. `crawl` = the site's shop page (the API lists the whole store).
   - Squarespace: any page plus `?format=json` returns JSON. Shop menus are often plain pages, so find the real store collections in `/sitemap.xml` and use those as `crawl`.
   - Anything else: no `platform`; `crawl` = category pages to read directly.
2. Ask the user what's in scope unless they already said. Default to hand tools and small bench tools, not furnaces or large studio equipment.
3. Add an entry to `_data/vendors.yml`: `id`, `name`, `url`, `maker` (if they make what they sell), `platform`, and `crawl` (the collection or category pages that hold in-scope items). Write `scope.in` / `scope.out` in the user's words, and add `notes` for quirks.
4. Check the vendor's distributor or stockist page. If a registered retailer carries the line, add those buy links too (step 3), and note any unregistered distributors in `notes`.
5. If they're a maker, create `_makers/<slug>.md` with location, website, and a two-sentence description, using only sourced facts. Leave out `founded` unless the vendor's own site gives it. If it has a `location`, run `python3 scripts/archive.py geocode --write` so the maker gets a town-level pin on the Makers map.
