#!/usr/bin/env python3
"""Head-kit verifier for spookwerk.nl. Stdlib only.
Slim fork of spookwerk.github.io's tools/verify-seo.py (sub-project E).
Usage: python3 tools/verify-seo.py [--root DIR] [--write-sitemap] [FILE ...]
Pages are auto-discovered (every *.html under root minus SKIP_DIRS); pass
explicit FILEs to scope (scoped runs skip site-level checks, same as .app).
Exit 0 = all checked pages pass; non-zero = failures (printed)."""
import argparse, json, re, sys
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape
from html.parser import HTMLParser
from pathlib import Path

SKIP_DIRS = {"tools", "hooks"}  # never deployed pages (hooks/ = PHP webhook)

SITE = "https://spookwerk.nl"
# The brand entity is anchored on spookwerk.app (shared-entity decision, E §2)
ORG_SITE = "https://spookwerk.app"
ORG_ID = f"{ORG_SITE}/#organization"
SITE_ID = f"{ORG_SITE}/#website"
EXPECTED_LOGO = f"{ORG_SITE}/logo.png"   # external by design; asserted literally
SAMEAS_FIRST = "https://spookwerk.nl"
X_DEFAULT = f"{SITE}/"                   # Dutch-primary site: x-default -> NL page

# index.html <-> en/index.html are mandatory twins
TWIN = {"index.html": "en/index.html", "en/index.html": "index.html"}

OG_REQUIRED = ["og:type", "og:title", "og:description", "og:url",
               "og:image", "og:site_name", "og:locale", "og:locale:alternate"]
TW_REQUIRED = ["twitter:card", "twitter:title", "twitter:description",
               "twitter:image"]


class Head(HTMLParser):
    def __init__(self):
        super().__init__()
        self.canonical = None
        self.alts = []          # (hreflang, href)
        self.og = {}
        self.tw = {}
        self.description = None
        self.robots = ""
        self.ld_raw = []
        self._in_ld = False
        self._buf = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "link":
            rels = (a.get("rel") or "").lower().split()
            if "canonical" in rels:
                self.canonical = a.get("href")
            elif "alternate" in rels and a.get("hreflang"):
                self.alts.append((a["hreflang"], a.get("href")))
        elif tag == "meta":
            prop = a.get("property", "")
            if prop.startswith("og:"):
                self.og[prop] = a.get("content", "")
            name = a.get("name", "")
            if name.startswith("twitter:"):
                self.tw[name] = a.get("content", "")
            elif name == "description":
                self.description = a.get("content", "")
            elif name == "robots":
                self.robots = a.get("content", "")
        elif tag == "script" and (a.get("type") == "application/ld+json"):
            self._in_ld = True
            self._buf = []

    def handle_endtag(self, tag):
        if tag == "script" and self._in_ld:
            self._in_ld = False
            self.ld_raw.append("".join(self._buf).strip())

    def handle_data(self, data):
        if self._in_ld:
            self._buf.append(data)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)


def parse_file(f: Path) -> Head:
    h = Head()
    h.feed(f.read_text(encoding="utf-8", errors="replace"))
    return h


def expected_canonical(relpath: str) -> str:
    if relpath.endswith("index.html"):
        return f"{SITE}/{relpath[:-len('index.html')]}"
    return f"{SITE}/{relpath}"


def href_to_relpath(href: str):
    pre = SITE + "/"
    if not href.startswith(pre):
        return None
    rest = href[len(pre):]
    if rest == "" or rest.endswith("/"):
        return rest + "index.html"
    return rest


def ld_nodes(raw_blocks):
    nodes = []
    for raw in raw_blocks:
        data = json.loads(raw)
        if isinstance(data, dict) and "@graph" in data:
            nodes.extend(data["@graph"])
        elif isinstance(data, list):
            nodes.extend(data)
        else:
            nodes.append(data)
    return nodes


def contains_person(obj) -> bool:
    if isinstance(obj, dict):
        if obj.get("@type") == "Person":
            return True
        return any(contains_person(v) for v in obj.values())
    if isinstance(obj, list):
        return any(contains_person(v) for v in obj)
    return False


def check_page(root: Path, relpath: str, parsed_set: dict) -> list:
    errs = []
    h = parsed_set[relpath]
    exp = expected_canonical(relpath)

    # 1. canonical + meta description
    if not h.canonical:
        errs.append("missing canonical")
    elif h.canonical != exp:
        errs.append(f"canonical {h.canonical!r} != expected {exp!r}")
    if not h.description:
        errs.append("missing meta description")

    # 2. hreflang — MANDATORY on .nl (both pages are a bilingual pair)
    if not h.alts:
        errs.append("missing hreflang (mandatory: twin exists)")
    else:
        hrefs = {hl: hr for hl, hr in h.alts}
        if "x-default" not in hrefs:
            errs.append("hreflang missing x-default")
        elif hrefs["x-default"] != X_DEFAULT:
            errs.append(f"x-default {hrefs['x-default']!r} != {X_DEFAULT!r} "
                        "(Dutch-primary site, E §2)")
        for hl, hr in h.alts:
            rp = href_to_relpath(hr)
            if rp is None or not (root / rp).exists():
                errs.append(f"hreflang {hl} target missing: {hr}")
        if exp not in hrefs.values():
            errs.append(f"hreflang does not list self ({exp})")
        twin = TWIN.get(relpath)
        if twin:
            twin_url = expected_canonical(twin)
            if twin_url not in {hr for _, hr in h.alts}:
                errs.append(f"hreflang does not list twin {twin_url}")
        for hl, hr in h.alts:
            if hl == "x-default":
                continue
            rp = href_to_relpath(hr)
            if rp and rp != relpath and rp in parsed_set:
                back = {v for _, v in parsed_set[rp].alts}
                if exp not in back:
                    errs.append(f"hreflang not reciprocal with {rp}")

    # 3. Open Graph
    for k in OG_REQUIRED:
        if k not in h.og or not h.og[k]:
            errs.append(f"missing {k}")
    if h.og.get("og:type") and h.og["og:type"] != "website":
        errs.append(f"og:type {h.og['og:type']!r} != 'website'")
    if h.og.get("og:url") and h.canonical and h.og["og:url"] != h.canonical:
        errs.append("og:url != canonical")

    # 4. Twitter
    for k in TW_REQUIRED:
        if k not in h.tw or not h.tw[k]:
            errs.append(f"missing {k}")

    # 5. JSON-LD: shared sitewide spine (anchored on spookwerk.app)
    if not h.ld_raw:
        errs.append("missing JSON-LD")
    else:
        try:
            nodes = ld_nodes(h.ld_raw)
        except json.JSONDecodeError as e:
            errs.append(f"invalid JSON-LD: {e}")
            nodes = []
        ids = {n.get("@id") for n in nodes if isinstance(n, dict)}
        if ORG_ID not in ids:
            errs.append(f"JSON-LD missing Organization @id {ORG_ID}")
        if SITE_ID not in ids:
            errs.append(f"JSON-LD missing WebSite @id {SITE_ID}")
        if contains_person(nodes):
            errs.append("Person found in JSON-LD (name-privacy violation)")
        for n in nodes:
            if isinstance(n, dict) and n.get("@id") == ORG_ID:
                if n.get("logo") != EXPECTED_LOGO:
                    errs.append(f"logo {n.get('logo')!r} != {EXPECTED_LOGO!r} "
                                "(external by design, E §2)")
                same = n.get("sameAs") or []
                if not same or same[0] != SAMEAS_FIRST:
                    errs.append(f"sameAs[0] must be {SAMEAS_FIRST!r}")

    # 6. og:image asset exists in the repo
    img = h.og.get("og:image")
    rp = href_to_relpath(img) if img else None
    if rp and not (root / rp).exists():
        errs.append(f"og:image asset missing: {img}")

    return errs


def sitewide_block(h: Head):
    if not h.ld_raw:
        return None
    try:
        return json.loads(h.ld_raw[0])
    except (json.JSONDecodeError, TypeError):
        return None


def discover(root: Path) -> dict:
    parsed = {}
    for f in sorted(root.rglob("*.html")):
        rel = f.relative_to(root).as_posix()
        if rel.split("/")[0] in SKIP_DIRS:
            continue
        h = parse_file(f)
        if "noindex" in h.robots.lower():
            continue
        parsed[rel] = h
    return parsed


def sitemap_xml(relpaths) -> str:
    body = "\n".join(f"  <url><loc>{escape(expected_canonical(r))}</loc></url>"
                     for r in sorted(relpaths,
                                     key=lambda r: expected_canonical(r)))
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            + body + "\n</urlset>\n")


SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}


def check_site_files(root: Path, parsed: dict) -> dict:
    errs = {}
    sm = root / "sitemap.xml"
    expected = {expected_canonical(r) for r in parsed}
    if not sm.exists():
        errs["sitemap.xml"] = [
            "missing — generate with: tools/verify-seo.py --write-sitemap"]
    else:
        try:
            got = {(el.text or "").strip()
                   for el in ET.parse(sm).findall(".//sm:loc", SITEMAP_NS)}
            e = []
            for url in sorted(got - expected):
                e.append(f"sitemap lists URL with no page: {url}")
            for url in sorted(expected - got):
                e.append(f"page missing from sitemap: {url} — regenerate")
            if e:
                errs["sitemap.xml"] = e
        except ET.ParseError as ex:
            errs["sitemap.xml"] = [f"unparseable sitemap: {ex}"]
    rb = root / "robots.txt"
    if not rb.exists():
        errs["robots.txt"] = ["missing"]
    else:
        e = []
        lines = rb.read_text(encoding="utf-8").splitlines()
        if f"Sitemap: {SITE}/sitemap.xml" not in lines:
            e.append(f"missing line: Sitemap: {SITE}/sitemap.xml")
        for ln in lines:
            if ln.strip().lower().startswith("disallow:"):
                e.append(f"Disallow directive present: {ln.strip()!r} "
                         "(site policy is allow-all; see spec E §2)")
        if e:
            errs["robots.txt"] = e
    lm = root / "llms.txt"
    if not lm.exists():
        errs["llms.txt"] = ["missing"]
    else:
        e = []
        text = lm.read_text(encoding="utf-8")
        for url in re.findall(r"https://spookwerk\.nl/[^\s)\"'>\]]*", text):
            url = re.split(r"[#?]", url)[0].rstrip(".,;:")
            rp = href_to_relpath(url)
            if rp and not (root / rp).exists():
                e.append(f"dead link: {url}")
        if e:
            errs["llms.txt"] = e
    return errs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--write-sitemap", action="store_true",
                    help="(re)generate sitemap.xml from discovered pages, then exit")
    ap.add_argument("files", nargs="*")
    args = ap.parse_args()
    root = Path(args.root).resolve()

    parsed = {}
    missing = []
    if args.files:
        for rel in args.files:
            f = root / rel
            if not f.exists():
                missing.append(rel)
                continue
            parsed[rel] = parse_file(f)
    else:
        parsed = discover(root)

    if args.write_sitemap:
        if args.files:
            print("--write-sitemap cannot be combined with FILE args")
            sys.exit(2)
        (root / "sitemap.xml").write_text(sitemap_xml(parsed), encoding="utf-8")
        print(f"sitemap.xml written ({len(parsed)} URLs)")
        sys.exit(0)

    failures = {}
    for rel in parsed:
        e = check_page(root, rel, parsed)
        if e:
            failures[rel] = e
    for rel in missing:
        failures[rel] = ["file not found"]

    # site-level checks only make sense against the full discovered set
    if not args.files:
        for name, e in check_site_files(root, parsed).items():
            failures.setdefault(name, []).extend(e)

    # sitewide JSON-LD block (full first block) must be identical on every page
    sitewide_blocks = {rel: b for rel in parsed
                       if (b := sitewide_block(parsed[rel])) is not None}
    if sitewide_blocks:
        first_rel = next(iter(sitewide_blocks))
        ref = sitewide_blocks[first_rel]
        for rel, b in sitewide_blocks.items():
            if b != ref:
                failures.setdefault(rel, []).append(
                    f"sitewide JSON-LD block differs from {first_rel}")

    if failures:
        for rel, errs in failures.items():
            print(f"FAIL {rel}")
            for e in errs:
                print(f"     - {e}")
        print(f"\n{len(failures)} page(s) failed.")
        sys.exit(1)
    print(f"OK: {len(parsed)} page(s) passed.")
    sys.exit(0)


if __name__ == "__main__":
    main()
