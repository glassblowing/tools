#!/usr/bin/env python3
"""Helpers for keeping the tool archive up to date.

    python3 scripts/archive.py validate              # check tools/makers/categories/vendors line up
    python3 scripts/archive.py links [--vendor ID] [--max-age DAYS] [--write]
                                                     # check buy links not checked in the last week
    python3 scripts/archive.py catalog VENDOR_ID     # list a vendor's in-crawl products (Shopify, WooCommerce, Squarespace)
    python3 scripts/archive.py photos [--write]      # link each listing to the seller's own product image
                                                     # (pages with no photo are skipped for 30 days)
    python3 scripts/archive.py geocode [--write]     # town-level map coordinates for makers with a location
    python3 scripts/archive.py types [--write]       # give untyped tools a glossary type from title patterns

Used by the update-archive skill (.claude/skills/update-archive/SKILL.md). Needs PyYAML.
"""
import argparse
import datetime
import fcntl
import html
import json
import re
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

try:
    import yaml
except ImportError:
    sys.exit("PyYAML is required: pip install pyyaml")

ROOT = Path(__file__).resolve().parent.parent
TODAY = datetime.date.today()
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140 Safari/537.36"


def front_matter(path):
    text = path.read_text()
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    return yaml.safe_load(m.group(1)) if m else {}


def glossary():
    """Glossary entries (tool types) by slug."""
    return {p.stem: front_matter(p) for p in sorted((ROOT / "_glossary").glob("*.md"))}


def load():
    tools = {}
    for p in sorted((ROOT / "_tools").glob("*.md")):
        try:
            tools[p.stem] = front_matter(p)
        except yaml.YAMLError as e:
            sys.exit(f"_tools/{p.name}: bad front matter: {e.problem}")
    makers = {p.stem for p in (ROOT / "_makers").glob("*.md")}
    cats = {p.stem for p in (ROOT / "_tool_categories").glob("*.md")}
    vendors = yaml.safe_load((ROOT / "_data" / "vendors.yml").read_text())
    SHOPIFY_HOSTS.update(urlparse(v["url"]).netloc for v in vendors if v.get("platform") == "shopify")
    return tools, makers, cats, vendors


# Shopify rate-limits a client across all of its stores, so every Shopify store shares one
# pacing slot; other sites get one each. Slots are lock files, so two runs of this script at
# once (say, photos and links) still take turns instead of tripping the limit together.
SHOPIFY_HOSTS = set()
PACE = {"shopify": 1.5}


def pace(url):
    """Wait until it's this site's turn to get another request."""
    host = urlparse(url).netloc
    key = "shopify" if host in SHOPIFY_HOSTS else host
    lock = Path(tempfile.gettempdir()) / f"gbt-archive-{key}.pace"
    with open(lock, "a+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.seek(0)
        last = float(f.read() or 0)
        time.sleep(max(0, last + PACE.get(key, 0.5) - time.time()))
        f.seek(0)
        f.truncate()
        f.write(str(time.time()))


def fetch(url, timeout=20, tries=5):
    """GET a URL, waiting and retrying when the site rate-limits us (429)."""
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    for attempt in range(tries):
        pace(url)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, r.geturl(), r.read()
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == tries - 1:
                raise
            # Honor Retry-After when it's a number, else back off.
            wait = e.headers.get("Retry-After", "")
            time.sleep(float(wait) if wait.isdigit() else 5 * (attempt + 1))


def status(url):
    try:
        code, final, _ = fetch(url)
        return code, final
    except urllib.error.HTTPError as e:
        return e.code, url
    except Exception as e:  # DNS, timeout, TLS
        return type(e).__name__, url


# Instagram handles are stored bare (no @, no URL); the templates build the link.
INSTAGRAM = re.compile(r"[A-Za-z0-9_.]{1,30}")


def cmd_validate(_):
    tools, makers, cats, vendors = load()
    names = {v["name"] for v in vendors}
    ids = [v["id"] for v in vendors]
    problems = []
    types = glossary()
    for slug, g in types.items():
        for field in ("title", "category", "summary"):
            if not g.get(field):
                problems.append(f"_glossary/{slug}.md: missing {field}")
        if g.get("category") not in cats:
            problems.append(f"_glossary/{slug}.md: unknown category '{g.get('category')}'")
        for s in g.get("sources") or []:
            if not (s.get("title") and s.get("url")):
                problems.append(f"_glossary/{slug}.md: each source needs a title and url")
        # Inline citations: {% include cite.html n=2 %} or n="1,3" must point at a listed
        # source, every listed source must be cited, and a History section needs citations.
        body = (ROOT / "_glossary" / f"{slug}.md").read_text().split("\n---\n", 1)[-1]
        cited = {int(n) for ns in re.findall(r'cite\.html n="?([\d, ]+)"?', body) for n in ns.split(",") if n.strip()}
        nsrc = len(g.get("sources") or [])
        for n in sorted(cited - set(range(1, nsrc + 1))):
            problems.append(f"_glossary/{slug}.md: cites [{n}] but there are only {nsrc} sources")
        for n in sorted(set(range(1, nsrc + 1)) - cited):
            problems.append(f"_glossary/{slug}.md: source [{n}] is listed but never cited")
        hist = re.search(r"^## History\n(.*?)(?=^## |\Z)", body, re.S | re.M)
        if hist and "cite.html" not in hist.group(1):
            problems.append(f"_glossary/{slug}.md: History section has no citations")
        if g.get("match"):
            try:
                re.compile(g["match"])
            except re.error as e:
                problems.append(f"_glossary/{slug}.md: bad match pattern ({e})")
    for d in ("_makers", "_tool_categories"):
        for p in sorted((ROOT / d).glob("*.md")):
            try:
                fm = front_matter(p)
                if not fm.get("title"):
                    problems.append(f"{d}/{p.name}: missing title")
                if fm.get("instagram") and not INSTAGRAM.fullmatch(str(fm["instagram"])):
                    problems.append(f"{d}/{p.name}: instagram should be a bare handle, not '{fm['instagram']}'")
            except yaml.YAMLError as e:
                problems.append(f"{d}/{p.name}: bad front matter: {e.problem}")
    if len(ids) != len(set(ids)):
        problems.append("_data/vendors.yml: duplicate vendor ids")
    for v in vendors:
        if v.get("maker") and v["maker"] not in makers:
            problems.append(f"vendor {v['id']}: maker '{v['maker']}' has no _makers file")
        if v.get("instagram") and not INSTAGRAM.fullmatch(str(v["instagram"])):
            problems.append(f"vendor {v['id']}: instagram should be a bare handle, not '{v['instagram']}'")
    for slug, t in tools.items():
        for field in ("title", "maker", "category", "summary", "added"):
            if not t.get(field):
                problems.append(f"_tools/{slug}.md: missing {field}")
        if t.get("image") and not t.get("image_credit"):
            problems.append(f"_tools/{slug}.md: image without image_credit")
        if t.get("maker") not in makers:
            problems.append(f"_tools/{slug}.md: unknown maker '{t.get('maker')}'")
        if t.get("category") not in cats:
            problems.append(f"_tools/{slug}.md: unknown category '{t.get('category')}'")
        if t.get("type") and t["type"] not in types:
            problems.append(f"_tools/{slug}.md: unknown type '{t['type']}' (no _glossary/{t['type']}.md)")
        for b in t.get("buy") or []:
            if b.get("vendor") not in names:
                problems.append(f"_tools/{slug}.md: vendor '{b.get('vendor')}' not in _data/vendors.yml")
        for r in t.get("reviews") or []:
            if not 1 <= int(r.get("rating", 0)) <= 5:
                problems.append(f"_tools/{slug}.md: review rating out of range")
    print("\n".join(problems) or f"OK: {len(tools)} tools, {len(makers)} makers, {len(cats)} categories, {len(vendors)} vendors, {len(types)} glossary types")
    untyped = sum(1 for t in tools.values() if t.get("published", True) is not False and not t.get("type"))
    if untyped and not problems:
        print(f"note: {untyped} visible tools have no glossary type yet (make types)")
    return 1 if problems else 0


def cmd_types(args):
    """Give tools without a `type` one, using each glossary entry's `match` pattern on the title.

    A pattern only applies within its entry's `categories` (default: the entry's own category),
    and the first entry by (category, order) that matches wins."""
    tools, *_ = load()
    types = sorted(glossary().items(), key=lambda kv: (kv[1].get("category", ""), kv[1].get("order", 99), kv[0]))
    rules = [(slug, re.compile(g["match"], re.I), set(g.get("match_categories") or [g["category"]]))
             for slug, g in types if g.get("match")]
    set_, unmatched = 0, []
    for slug, t in sorted(tools.items()):
        if t.get("type") or t.get("published", True) is False:
            continue
        hit = next((ts for ts, rx, cats in rules if t.get("category") in cats and rx.search(t["title"])), None)
        if not hit:
            unmatched.append((t.get("category"), t["title"], slug)); continue
        set_ += 1
        print(f"{hit:24} {slug}")
        if args.write:
            p = ROOT / "_tools" / f"{slug}.md"; fm = front_matter(p); fm["type"] = hit
            write_front_matter(p, fm)
    for cat, title, slug in sorted(unmatched):
        print(f"{'(no match)':24} {cat:16} {title}  [{slug}]")
    print(f"\n{set_} tools typed, {len(unmatched)} without a match" + ("" if args.write else " (dry run; pass --write to save)"))
    return 0


def cmd_links(args):
    tools, _, _, vendors = load()
    by_name = {v["name"]: v for v in vendors}
    jobs, skipped, partial = [], 0, set()
    for slug, t in tools.items():
        checked = t.get("last_checked")
        if isinstance(checked, str):
            checked = datetime.date.fromisoformat(checked)
        if args.max_age and checked and (TODAY - checked).days < args.max_age:
            skipped += 1
            continue
        for b in t.get("buy") or []:
            v = by_name.get(b["vendor"], {})
            if args.vendor and v.get("id") != args.vendor:
                partial.add(slug)  # some links unchecked, so don't mark the tool checked
                continue
            queue = "shopify" if v.get("platform") == "shopify" else urlparse(b["url"]).netloc
            jobs.append((queue, slug, b["vendor"], b["url"]))

    # Queues run in parallel; fetch() spaces out the requests to each site.
    queues = {}
    for q, *job in jobs:
        queues.setdefault(q, []).append(job)

    def check(url):
        # A product the store lists in /products.json is live; only look up the rest.
        if urlparse(url).netloc in SHOPIFY_HOSTS and (handle := shopify_handle(url)):
            if handle in shopify_products("{0.scheme}://{0.netloc}".format(urlparse(url))):
                return 200, url
        return status(url)

    def run(item):
        return [(*j, *check(j[2])) for j in item[1]]

    with ThreadPoolExecutor(8) as ex:
        results = [r for rs in ex.map(run, queues.items()) for r in rs]
    results.sort(key=lambda r: r[0])
    bad = limited = 0
    for slug, vendor, url, code, final in results:
        moved = final != url and urlparse(final).path.rstrip("/") != urlparse(url).path.rstrip("/")
        if code == 200:
            flag = "moved" if moved else "ok"
        else:
            # 429 means the site throttled us, not that the page is gone. Recheck later.
            flag = "limit" if code == 429 else "FAIL"
        bad += flag in ("FAIL", "moved")
        limited += flag == "limit"
        extra = f" -> {final}" if moved else ""
        if flag != "ok" or args.verbose:
            print(f"{flag:5} {code!s:>4}  {slug:45} {vendor}: {url}{extra}")
    print(f"\n{len(results) - bad - limited}/{len(results)} links ok, {bad} need attention, {limited} rate-limited (recheck later)"
          + (f"; skipped {skipped} tools checked in the last {args.max_age} days" if skipped else ""))
    if args.write:
        all_ok = {}
        for slug, _, _, code, final in results:
            all_ok[slug] = all_ok.get(slug, True) and code == 200
        done = sorted(s for s, ok in all_ok.items() if ok and s not in partial)
        for slug in done:
            path = ROOT / "_tools" / f"{slug}.md"
            fm = front_matter(path)
            fm["last_checked"] = TODAY
            write_front_matter(path, fm)
        print(f"set last_checked on {len(done)} tools whose links all returned ok")
    return 0


def text(markup):
    """HTML (and WordPress page-builder shortcodes) to plain text."""
    t = re.sub(r"\[/?[a-z_]+[^\]]*\]", " ", html.unescape(markup or ""))
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t))).strip()


def get_json(url):
    return json.loads(fetch(url)[2])


_shopify = {}
_shopify_lock = threading.Lock()


def shopify_products(origin):
    """Every product a Shopify store lists, by handle, fetched once per run.

    /products.json returns 250 products a request, so a whole store costs a few requests
    instead of one per product page."""
    with _shopify_lock:
        if origin not in _shopify:
            found, page = {}, 1
            try:
                while True:
                    items = get_json(f"{origin}/products.json?limit=250&page={page}")["products"]
                    found.update((p["handle"], p) for p in items)
                    if len(items) < 250:
                        break
                    page += 1
            except Exception as e:  # fall back to fetching product pages one at a time
                print(f"# couldn't list {origin}/products.json ({e}); reading pages one by one", file=sys.stderr)
            _shopify[origin] = found
        return _shopify[origin]


def shopify_handle(url):
    m = re.search(r"/products/([^/?#]+)", urlparse(url).path)
    return m and urllib.parse.unquote(m.group(1))


# Each reader takes (vendor, crawl_url) and yields normalized products:
# {"url", "title", "group", "options", "desc"}.

def read_shopify(v, crawl_url):
    origin = "{0.scheme}://{0.netloc}".format(urlparse(v["url"]))
    group = urlparse(crawl_url).path.rstrip("/").rsplit("/", 1)[-1]
    page = 1
    while True:
        items = get_json(f"{crawl_url.rstrip('/')}/products.json?limit=250&page={page}")["products"]
        for p in items:
            yield {
                "url": f"{origin}/products/{p['handle']}",
                "title": p["title"],
                "group": f"{group} / {p['product_type']}".rstrip(" /"),
                "maker": p.get("vendor", ""),
                "options": "; ".join(f"{o['name']}: {', '.join(o['values'])}" for o in p["options"] if o["name"] != "Title"),
                "desc": text(p.get("body_html")),
            }
        if len(items) < 250:
            return
        page += 1


def read_woocommerce(v, crawl_url):
    # The WooCommerce Store API is public and lists the whole store, so crawl_url is only the site.
    origin = "{0.scheme}://{0.netloc}".format(urlparse(crawl_url))
    page = 1
    while True:
        items = get_json(f"{origin}/wp-json/wc/store/v1/products?per_page=100&page={page}")
        for p in items:
            yield {
                "url": p["permalink"],
                "title": html.unescape(p["name"]),
                "group": ", ".join(c["name"] for c in p.get("categories", [])),
                "options": "; ".join(f"{a['name']}: {', '.join(t['name'] for t in a.get('terms', []))}" for a in p.get("attributes", [])),
                "desc": " ".join(filter(None, [text(p.get("short_description")), text(p.get("description"))])),
            }
        if len(items) < 100:
            return
        page += 1


def read_squarespace(v, crawl_url):
    # Any Squarespace page returns its data with ?format=json.
    origin = "{0.scheme}://{0.netloc}".format(urlparse(crawl_url))
    url = f"{crawl_url}?format=json"
    while url:
        d = get_json(url)
        for i in d.get("items", []):
            opts = {}
            for var in i.get("variants", []):
                for k, val in (var.get("attributes") or {}).items():
                    vals = opts.setdefault(k, [])
                    if val not in vals:
                        vals.append(val)
            yield {
                "url": origin + i["fullUrl"],
                "title": i["title"],
                "group": ", ".join(i.get("categories") or []),
                "options": "; ".join(f"{k}: {', '.join(vals)}" for k, vals in opts.items()),
                "desc": " ".join(filter(None, [text(i.get("excerpt")), text(i.get("body"))])),
            }
        nxt = (d.get("pagination") or {}).get("nextPageUrl")
        url = f"{origin}{nxt}&format=json" if nxt else None


def read_bigcommerce(v, crawl_url):
    # BigCommerce has no public product JSON, but lists every product in its XML sitemap.
    # crawl_url is the store root; each product page is read for its breadcrumb and description.
    origin = "{0.scheme}://{0.netloc}".format(urlparse(crawl_url))
    sitemap = fetch(f"{origin}/xmlsitemap.php?type=products&page=1")[2].decode("utf8", "ignore")
    for url in re.findall(r"<loc>([^<]+)</loc>", sitemap):
        url = html.unescape(url)
        page = fetch(url)[2].decode("utf8", "ignore")
        t = re.sub(r"<script.*?</script>|<style.*?</style>", "", page, flags=re.S)
        t = re.sub(r"(\s*\|\s*)+", " | ", re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " | ", t))))
        m = re.search(r"<title>([^<]*)</title>", page)
        title = html.unescape(m.group(1)).split(" - Steinert")[0].rsplit(" - ", 1)[0].strip() if m else url
        crumbs = re.findall(r"\| Home \| (.*?) \| " + re.escape(title.split(" |")[0][:30]), t)
        desc = re.search(r"Product Description \|(.*?)\| (SKU:|Find Similar)", t)
        yield {
            "url": url,
            "title": title,
            "group": (crumbs[-1].replace(" | ", " / ") if crumbs else ""),
            "options": "",
            "desc": desc.group(1).strip(" |") if desc else "",
        }


READERS = {"shopify": read_shopify, "woocommerce": read_woocommerce, "squarespace": read_squarespace,
           "bigcommerce": read_bigcommerce}


def cmd_catalog(args):
    tools, _, _, vendors = load()
    v = next((v for v in vendors if v["id"] == args.vendor), None)
    if not v:
        sys.exit(f"no vendor '{args.vendor}' in _data/vendors.yml")
    reader = READERS.get(v.get("platform"))
    if not reader:
        print(f"{v['name']}: no reader for platform '{v.get('platform')}'; read these pages directly:\n  "
              + "\n  ".join(v.get("crawl") or ["(none)"]))
        return 0
    indexed = {}
    for slug, t in tools.items():
        for b in t.get("buy") or []:
            indexed[b["url"].rstrip("/")] = slug
    seen = {}
    for c in v.get("crawl") or []:
        try:
            for p in reader(v, c):
                seen.setdefault(p["url"].rstrip("/"), p)
        except Exception as e:  # one broken collection shouldn't stop the rest
            print(f"# couldn't read {c}: {e}")
    print(f"# {v['name']}: {len(seen)} products in crawl pages")
    print(f"# scope in:  {v['scope'].get('in', '')}\n# scope out: {v['scope'].get('out', '')}\n")
    for url, p in seen.items():
        state = f"INDEXED as _tools/{indexed[url]}.md" if url in indexed else "not indexed"
        print(f"## {p['title'].strip()}  [{state}]\n   url: {p['url']}")
        if p["group"]:
            print(f"   group: {p['group']}")
        if p.get("maker"):
            print(f"   maker: {p['maker']}")
        if p["options"]:
            print(f"   options: {p['options']}")
        print(f"   {p['desc'][:900] or '(no description on the vendor page)'}\n")
    return 0


def og_image(page_html):
    """The product image from JSON-LD, falling back to og:image."""
    for m in re.finditer(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', page_html, re.S):
        try:
            data = json.loads(m.group(1))
        except ValueError:
            continue
        for d in data if isinstance(data, list) else [data]:
            if isinstance(d, dict) and d.get("@type") == "Product" and d.get("image"):
                img = d["image"]
                img = img[0] if isinstance(img, list) else img
                # ImageObject: contentUrl is the image; url can be the product page (Ecwid).
                return (img.get("contentUrl") or img.get("url")) if isinstance(img, dict) else img
    m = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)', page_html) or \
        re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image', page_html)
    return html.unescape(m.group(1)) if m else None


_site_default = {}


def image_ok(url):
    """True if the URL serves a real image, not an error or a placeholder it redirects to."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "image/*"})
        with urllib.request.urlopen(req, timeout=20) as r:
            ctype = r.headers.get("Content-Type", "")
            final = r.geturl().lower()
            r.read(1024)
            return r.status == 200 and ctype.startswith("image/") and not any(
                k in final for k in ("no-image", "noimage", "placeholder"))
    except Exception:
        return False


def find_image(v, url):
    """Return the vendor's own image URL for a product page, or None."""
    origin = "{0.scheme}://{0.netloc}".format(urlparse(url))
    platform = v.get("platform")
    if platform == "shopify":
        p = shopify_products(origin).get(shopify_handle(url))
        if p is None:  # not in the store's listing (unlisted product); read its own page
            p = get_json(url.split("?")[0].rstrip("/") + ".json")["product"]
        return p["images"][0]["src"] if p.get("images") else None
    if platform == "squarespace":
        item = get_json(url.split("?")[0] + "?format=json").get("item") or {}
        # Product photos live in the item's gallery; the item-level assetUrl is often a
        # legacy static1 URL that redirects to Squarespace's "no-image" placeholder.
        gallery = [i.get("assetUrl") for i in item.get("items") or [] if i.get("assetUrl")]
        src = gallery[0] if gallery else item.get("assetUrl")
        return src + "?format=1000w" if src else None
    if platform == "woocommerce":
        slug = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
        found = get_json(f"{origin}/wp-json/wc/store/v1/products?slug={slug}")
        return found[0]["images"][0]["src"] if found and found[0].get("images") else None
    img = og_image(fetch(url)[2].decode("utf8", "ignore"))
    if not img:
        return None
    img = urllib.parse.urljoin(url, img)
    # A page that only has the site-wide share image (usually the logo) has no product photo.
    if origin not in _site_default:
        try:
            home = og_image(fetch(origin + "/")[2].decode("utf8", "ignore"))
            _site_default[origin] = urllib.parse.urljoin(origin + "/", home) if home else None
        except Exception:
            _site_default[origin] = None
    if img == _site_default[origin] or "logo" in img.lower():
        return None
    return img


def write_front_matter(path, fm):
    text_ = path.read_text()
    body = re.match(r"^---\n.*?\n---\n(.*)$", text_, re.S).group(1)
    y = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True, width=1000)
    y = re.sub(r"^(added|last_checked): '(\d{4}-\d\d-\d\d)'$", r"\1: \2", y, flags=re.M)
    path.write_text(f"---\n{y}---\n{body}")


# Product pages that loaded but had no usable photo, by URL, with the date we looked.
# Kept so later runs don't ask again every time; --refresh ignores it.
MISSES = ROOT / "scripts" / "photo-misses.json"
MISS_DAYS = 30


def cmd_photos(args):
    """Point listings at the seller's own product image (hotlinked, never copied), with credit."""
    tools, _, _, vendors = load()
    misses = json.loads(MISSES.read_text()) if MISSES.exists() else {}
    recent = {u for u, d in misses.items()
              if (TODAY - datetime.date.fromisoformat(d)).days < MISS_DAYS and not args.refresh}
    skipped = 0
    by_name = {v["name"]: v for v in vendors}
    url_uses = {}
    for t in tools.values():
        for b in t.get("buy") or []:
            url_uses[b["url"]] = url_uses.get(b["url"], 0) + 1

    jobs = []
    for slug, t in tools.items():
        if t.get("image") and not args.refresh:
            continue
        candidates = []
        for b in t.get("buy") or []:
            v = by_name.get(b["vendor"], {})
            if v.get("photos") == "no" or (args.vendor and v.get("id") != args.vendor):
                continue
            if url_uses[b["url"]] > 1:  # a catalog or category page, not this product's page
                continue
            if b["url"] in recent:
                skipped += 1
                continue
            direct = v.get("maker") == t.get("maker")
            candidates.append((not direct, b, v))
        if candidates:
            candidates.sort(key=lambda c: c[0])
            jobs.append((slug, [(b, v) for _, b, v in candidates]))

    queues = {}
    for slug, cands in jobs:
        v = cands[0][1]
        q = "shopify" if v.get("platform") == "shopify" else urlparse(cands[0][0]["url"]).netloc
        queues.setdefault(q, []).append((slug, cands))

    new_misses = {}

    def run(item):
        name, qjobs = item
        out = []
        for slug, cands in qjobs:
            for b, v in cands:
                try:
                    img = find_image(v, b["url"])
                    miss = True
                except Exception:  # blocked, throttled, or gone: try again next run
                    img, miss = None, False
                if img and img.startswith("//"):
                    img = "https:" + img
                elif img and img.startswith("http://"):
                    img = "https://" + img[len("http://"):]  # the site is HTTPS; don't mix content
                if img and not image_ok(img):
                    img = None
                if img:
                    out.append((slug, img, b, v))
                    break
                if miss:
                    new_misses[b["url"]] = TODAY.isoformat()
            else:
                out.append((slug, None, None, None))
        return out

    with ThreadPoolExecutor(8) as ex:
        results = [r for rs in ex.map(run, queues.items()) for r in rs]
    found = [r for r in results if r[1]]
    for slug, img, b, v in sorted(found):
        print(f"{slug:55} {v['name']}: {img}")
        if args.write:
            path = ROOT / "_tools" / f"{slug}.md"
            fm = front_matter(path)
            fm.update({"image": img, "image_credit": v["name"], "image_source": b["url"]})
            write_front_matter(path, fm)
    print(f"\n{len(found)}/{len(results)} listings have a vendor photo"
          + (f"; skipped {skipped} pages with no photo in the last {MISS_DAYS} days" if skipped else "")
          + ("" if args.write else " (dry run; pass --write to save)"))
    if args.write:
        misses.update(new_misses)
        live = {b["url"] for t in tools.values() for b in t.get("buy") or []}
        misses = {u: d for u, d in sorted(misses.items()) if u in live}  # drop links that are gone
        MISSES.write_text(json.dumps(misses, indent=1) + "\n")
    return 0


def cmd_geocode(args):
    """Add town-level `coords` to makers that have a `location` (OpenStreetMap Nominatim)."""
    done = 0
    for path in sorted((ROOT / "_makers").glob("*.md")):
        fm = front_matter(path)
        loc = fm.get("location")
        if not loc or (fm.get("coords") and not args.refresh):
            continue
        parts = [x.strip() for x in loc.split(",")]
        hits = []
        # Try the full location, then just "town, country" (regions like "Småland" can confuse it).
        for query in [loc] + ([f"{parts[0]}, {parts[-1]}"] if len(parts) > 2 else []):
            # Nominatim's usage policy: an identifying User-Agent and at most one request a second.
            q = urllib.parse.urlencode({"q": query, "format": "json", "limit": 1})
            req = urllib.request.Request(f"https://nominatim.openstreetmap.org/search?{q}",
                                         headers={"User-Agent": "glassblowing.tools archive script (https://github.com/glassblowing/tools)"})
            try:
                hits = json.load(urllib.request.urlopen(req, timeout=20))
            except Exception as e:
                print(f"{path.stem}: lookup failed ({type(e).__name__})")
            time.sleep(1.1)
            if hits:
                break
        if not hits:
            print(f"{path.stem}: no match for {loc!r}")
            continue
        # Round to ~1 km: the town, never a street address.
        fm["coords"] = [round(float(hits[0]["lat"]), 2), round(float(hits[0]["lon"]), 2)]
        print(f"{path.stem:25} {loc} -> {fm['coords']}  ({hits[0].get('display_name', '')[:60]})")
        if args.write:
            write_front_matter(path, fm)
            done += 1
    # Shops: vendors without a maker but with a location. Edit vendors.yml line by line
    # so its comments survive.
    vpath = ROOT / "_data" / "vendors.yml"
    text = vpath.read_text()
    for v in yaml.safe_load(text):
        if v.get("maker") or not v.get("location") or (v.get("coords") and not args.refresh):
            continue
        hit = _nominatim(v["location"])
        if not hit:
            print(f"shop {v['id']}: no match for {v['location']!r}")
            continue
        coords = [round(float(hit["lat"]), 2), round(float(hit["lon"]), 2)]
        print(f"shop {v['id']:20} {v['location']} -> {coords}")
        if args.write:
            block = re.search(rf"^- id: {re.escape(v['id'])}\n(?:  .*\n|    .*\n)*", text, re.M)
            seg = re.sub(r"^  coords: .*\n", "", block.group(0), flags=re.M)
            seg = re.sub(r"^(  location: .*\n)", rf"\1  coords: [{coords[0]}, {coords[1]}]\n", seg, count=1, flags=re.M)
            text = text[:block.start()] + seg + text[block.end():]
            done += 1
    if args.write:
        vpath.write_text(text)
    print(f"\n{done} makers and shops updated" + ("" if args.write else " (dry run; pass --write to save)"))
    return 0


def _nominatim(loc):
    parts = [x.strip() for x in loc.split(",")]
    for query in [loc] + ([f"{parts[0]}, {parts[-1]}"] if len(parts) > 2 else []):
        q = urllib.parse.urlencode({"q": query, "format": "json", "limit": 1})
        req = urllib.request.Request(f"https://nominatim.openstreetmap.org/search?{q}",
                                     headers={"User-Agent": "glassblowing.tools archive script (https://github.com/glassblowing/tools)"})
        try:
            hits = json.load(urllib.request.urlopen(req, timeout=20))
        except Exception:
            hits = []
        time.sleep(1.1)
        if hits:
            return hits[0]
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("validate")
    p = sub.add_parser("links")
    p.add_argument("--vendor", help="only this vendor id")
    p.add_argument("--max-age", type=int, default=7, metavar="DAYS",
                   help="skip tools whose last_checked is newer than this (default 7; 0 checks everything)")
    p.add_argument("--write", action="store_true", help="set last_checked on tools whose links all returned ok")
    p.add_argument("-v", "--verbose", action="store_true", help="also print links that are ok")
    p = sub.add_parser("catalog")
    p.add_argument("vendor", help="vendor id from _data/vendors.yml")
    p = sub.add_parser("photos")
    p.add_argument("--vendor", help="only use this vendor's pages")
    p.add_argument("--refresh", action="store_true", help="also re-check listings that already have a photo")
    p.add_argument("--write", action="store_true", help="save changes (default is a dry run)")
    p = sub.add_parser("types")
    p.add_argument("--write", action="store_true", help="save changes (default is a dry run)")
    p = sub.add_parser("geocode")
    p.add_argument("--refresh", action="store_true", help="redo makers that already have coords")
    p.add_argument("--write", action="store_true", help="save changes (default is a dry run)")
    args = ap.parse_args()
    return {"validate": cmd_validate, "links": cmd_links, "catalog": cmd_catalog, "photos": cmd_photos,
            "geocode": cmd_geocode, "types": cmd_types}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
