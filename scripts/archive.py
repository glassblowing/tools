#!/usr/bin/env python3
"""Helpers for keeping the tool archive up to date.

    python3 scripts/archive.py validate              # check tools/makers/categories/vendors line up
    python3 scripts/archive.py links [--vendor ID]   # check every buy link
    python3 scripts/archive.py catalog VENDOR_ID     # list a vendor's in-crawl products (Shopify, WooCommerce, Squarespace)

Used by the update-archive skill (.claude/skills/update-archive/SKILL.md). Needs PyYAML.
"""
import argparse
import html
import json
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

try:
    import yaml
except ImportError:
    sys.exit("PyYAML is required: pip install pyyaml")

ROOT = Path(__file__).resolve().parent.parent
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140 Safari/537.36"


def front_matter(path):
    text = path.read_text()
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    return yaml.safe_load(m.group(1)) if m else {}


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
    return tools, makers, cats, vendors


def fetch(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.geturl(), r.read()


def status(url, tries=5):
    for attempt in range(tries):
        try:
            code, final, _ = fetch(url)
            return code, final
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == tries - 1:
                return e.code, url
            # Rate limited: honor Retry-After when it's a number, else back off.
            wait = e.headers.get("Retry-After", "")
            time.sleep(float(wait) if wait.isdigit() else 5 * (attempt + 1))
        except Exception as e:  # DNS, timeout, TLS
            return type(e).__name__, url


def cmd_validate(_):
    tools, makers, cats, vendors = load()
    names = {v["name"] for v in vendors}
    ids = [v["id"] for v in vendors]
    problems = []
    for d in ("_makers", "_tool_categories"):
        for p in sorted((ROOT / d).glob("*.md")):
            try:
                if not front_matter(p).get("title"):
                    problems.append(f"{d}/{p.name}: missing title")
            except yaml.YAMLError as e:
                problems.append(f"{d}/{p.name}: bad front matter: {e.problem}")
    if len(ids) != len(set(ids)):
        problems.append("_data/vendors.yml: duplicate vendor ids")
    for v in vendors:
        if v.get("maker") and v["maker"] not in makers:
            problems.append(f"vendor {v['id']}: maker '{v['maker']}' has no _makers file")
    for slug, t in tools.items():
        for field in ("title", "maker", "category", "summary", "added"):
            if not t.get(field):
                problems.append(f"_tools/{slug}.md: missing {field}")
        if t.get("maker") not in makers:
            problems.append(f"_tools/{slug}.md: unknown maker '{t.get('maker')}'")
        if t.get("category") not in cats:
            problems.append(f"_tools/{slug}.md: unknown category '{t.get('category')}'")
        for b in t.get("buy") or []:
            if b.get("vendor") not in names:
                problems.append(f"_tools/{slug}.md: vendor '{b.get('vendor')}' not in _data/vendors.yml")
        for r in t.get("reviews") or []:
            if not 1 <= int(r.get("rating", 0)) <= 5:
                problems.append(f"_tools/{slug}.md: review rating out of range")
    print("\n".join(problems) or f"OK: {len(tools)} tools, {len(makers)} makers, {len(cats)} categories, {len(vendors)} vendors")
    return 1 if problems else 0


def cmd_links(args):
    tools, _, _, vendors = load()
    by_name = {v["name"]: v for v in vendors}
    jobs = []
    for slug, t in tools.items():
        for b in t.get("buy") or []:
            v = by_name.get(b["vendor"], {})
            if args.vendor and v.get("id") != args.vendor:
                continue
            jobs.append((slug, b["vendor"], b["url"]))

    # Sites are checked in parallel, but each site one request at a time with a short
    # pause, so a big retailer like Hot Glass Color doesn't rate-limit us.
    by_host = {}
    for j in jobs:
        by_host.setdefault(urlparse(j[2]).netloc, []).append(j)

    def check_host(host_jobs):
        out = []
        for j in host_jobs:
            out.append((*j, *status(j[2])))
            time.sleep(0.5)
        return out

    with ThreadPoolExecutor(8) as ex:
        results = [r for rs in ex.map(check_host, by_host.values()) for r in rs]
    results.sort(key=lambda r: r[0])
    bad = 0
    for slug, vendor, url, code, final in results:
        moved = final != url and urlparse(final).path.rstrip("/") != urlparse(url).path.rstrip("/")
        flag = "ok" if code == 200 and not moved else ("moved" if code == 200 else "FAIL")
        bad += flag != "ok"
        extra = f" -> {final}" if moved else ""
        print(f"{flag:5} {code!s:>4}  {slug:45} {vendor}: {url}{extra}")
    print(f"\n{len(results) - bad}/{len(results)} links ok")
    return 0


def text(markup):
    """HTML (and WordPress page-builder shortcodes) to plain text."""
    t = re.sub(r"\[/?[a-z_]+[^\]]*\]", " ", html.unescape(markup or ""))
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t))).strip()


def get_json(url):
    return json.loads(fetch(url)[2])


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


READERS = {"shopify": read_shopify, "woocommerce": read_woocommerce, "squarespace": read_squarespace}


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
        for p in reader(v, c):
            seen.setdefault(p["url"].rstrip("/"), p)
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


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("validate")
    p = sub.add_parser("links")
    p.add_argument("--vendor", help="only this vendor id")
    p = sub.add_parser("catalog")
    p.add_argument("vendor", help="vendor id from _data/vendors.yml")
    args = ap.parse_args()
    return {"validate": cmd_validate, "links": cmd_links, "catalog": cmd_catalog}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
