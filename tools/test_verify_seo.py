import json, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path

VERIFY = Path(__file__).parent / "verify-seo.py"
SITE = "https://spookwerk.nl"
ORG_SITE = "https://spookwerk.app"
ORG_ID = f"{ORG_SITE}/#organization"
SITE_ID = f"{ORG_SITE}/#website"

ORG = {"@type": "Organization", "@id": ORG_ID, "name": "Spookwerk",
       "logo": f"{ORG_SITE}/logo.png",
       "sameAs": ["https://spookwerk.nl", "https://x.com/Spookwerk"]}
WEB = {"@type": "WebSite", "@id": SITE_ID,
       "publisher": {"@id": ORG_ID}}


def sitewide(org=None, web=None):
    g = {"@context": "https://schema.org", "@graph": [org or ORG, web or WEB]}
    return f'<script type="application/ld+json">{json.dumps(g)}</script>'


def page(canonical, locale, *, alts=None, drop=None, org=None, raw=None):
    """A minimal valid .nl page head. alts default: the full correct trio."""
    drop = drop or set()
    if alts is None:
        alts = [("nl", f"{SITE}/"), ("en", f"{SITE}/en/"),
                ("x-default", f"{SITE}/")]
    L = []
    if "canonical" not in drop:
        L.append(f'<link rel="canonical" href="{canonical}">')
    for hl, href in alts:
        L.append(f'<link rel="alternate" hreflang="{hl}" href="{href}">')
    if "description" not in drop:
        L.append('<meta name="description" content="D">')
    if "og" not in drop:
        loc_alt = "en_US" if locale == "nl_NL" else "nl_NL"
        L += ['<meta property="og:type" content="website">',
              '<meta property="og:title" content="Spookwerk">',
              '<meta property="og:description" content="D">',
              f'<meta property="og:url" content="{canonical}">',
              f'<meta property="og:image" content="{SITE}/og/default.png">',
              '<meta property="og:site_name" content="Spookwerk">',
              f'<meta property="og:locale" content="{locale}">',
              f'<meta property="og:locale:alternate" content="{loc_alt}">']
    if "tw" not in drop:
        L += ['<meta name="twitter:card" content="summary_large_image">',
              '<meta name="twitter:title" content="Spookwerk">',
              '<meta name="twitter:description" content="D">',
              f'<meta name="twitter:image" content="{SITE}/og/default.png">']
    if "ld" not in drop:
        L.append(raw if raw is not None else sitewide(org=org))
    head = "\n".join(L)
    return f"<!DOCTYPE html><html><head>{head}</head><body></body></html>"


ROBOTS = f"User-agent: *\nAllow: /\n\nSitemap: {SITE}/sitemap.xml\n"
LLMS = f"# Spookwerk\n\n- [Home]({SITE}/)\n- [Home EN]({SITE}/en/)\n"
SITEMAP = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
           f"  <url><loc>{SITE}/</loc></url>\n"
           f"  <url><loc>{SITE}/en/</loc></url>\n"
           "</urlset>\n")


class Site:
    """Builds a valid synthetic .nl site in a temp dir; tests mutate it."""

    def __init__(self):
        self.dir = Path(tempfile.mkdtemp())
        (self.dir / "en").mkdir()
        (self.dir / "og").mkdir()
        self.write("index.html", page(f"{SITE}/", "nl_NL"))
        self.write("en/index.html", page(f"{SITE}/en/", "en_US"))
        self.write("og/default.png", "png")
        self.write("robots.txt", ROBOTS)
        self.write("llms.txt", LLMS)
        self.write("sitemap.xml", SITEMAP)

    def write(self, rel, text):
        f = self.dir / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")

    def run(self, *args):
        return subprocess.run(
            [sys.executable, str(VERIFY), "--root", str(self.dir), *args],
            capture_output=True, text=True)

    def cleanup(self):
        shutil.rmtree(self.dir, ignore_errors=True)


class T(unittest.TestCase):
    def setUp(self):
        self.s = Site()
        self.addCleanup(self.s.cleanup)

    def ok(self):
        r = self.s.run()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def fails_with(self, needle):
        r = self.s.run()
        self.assertNotEqual(r.returncode, 0, r.stdout)
        self.assertIn(needle, r.stdout)

    def test_valid_site_passes(self):
        self.ok()

    def test_missing_hreflang_fails(self):
        self.s.write("index.html", page(f"{SITE}/", "nl_NL", alts=[]))
        self.fails_with("mandatory")

    def test_missing_og_locale_fails(self):
        html = page(f"{SITE}/", "nl_NL").replace(
            '<meta property="og:locale" content="nl_NL">\n', "")
        self.s.write("index.html", html)
        self.fails_with("og:locale")

    def test_missing_og_locale_alternate_fails(self):
        html = page(f"{SITE}/", "nl_NL").replace(
            '<meta property="og:locale:alternate" content="en_US">', "")
        self.s.write("index.html", html)
        self.fails_with("og:locale:alternate")

    def test_logo_must_be_app_absolute_url(self):
        org = dict(ORG, logo="/logo.png")
        self.s.write("index.html", page(f"{SITE}/", "nl_NL", org=org))
        self.fails_with("logo")

    def test_missing_x_default_fails(self):
        alts = [("nl", f"{SITE}/"), ("en", f"{SITE}/en/")]
        self.s.write("index.html", page(f"{SITE}/", "nl_NL", alts=alts))
        self.fails_with("x-default")

    def test_x_default_must_point_to_nl_page(self):
        alts = [("nl", f"{SITE}/"), ("en", f"{SITE}/en/"),
                ("x-default", f"{SITE}/en/")]
        self.s.write("index.html", page(f"{SITE}/", "nl_NL", alts=alts))
        self.fails_with("x-default")

    def test_twin_must_be_listed(self):
        alts = [("nl", f"{SITE}/"), ("x-default", f"{SITE}/")]
        self.s.write("index.html", page(f"{SITE}/", "nl_NL", alts=alts))
        self.fails_with("twin")

    def test_wrong_logo_fails(self):
        org = dict(ORG, logo=f"{SITE}/logo.png")
        self.s.write("index.html", page(f"{SITE}/", "nl_NL", org=org))
        self.fails_with("logo")

    def test_sameas_first_must_be_nl(self):
        org = dict(ORG, sameAs=["https://x.com/Spookwerk"])
        self.s.write("index.html", page(f"{SITE}/", "nl_NL", org=org))
        self.fails_with("sameAs")

    def test_person_in_jsonld_fails(self):
        org = dict(ORG, founder={"@type": "Person", "name": "X"})
        self.s.write("index.html", page(f"{SITE}/", "nl_NL", org=org))
        self.fails_with("Person")

    def test_sitewide_block_must_be_identical(self):
        org = dict(ORG, description="different")
        self.s.write("index.html", page(f"{SITE}/", "nl_NL", org=org))
        self.fails_with("differs")

    def test_hooks_and_tools_excluded_from_discovery(self):
        self.s.write("hooks/stray.html", "<html></html>")
        self.s.write("tools/stray.html", "<html></html>")
        self.ok()  # not discovered -> no page checks, no sitemap parity break

    def test_sitemap_extra_url_fails(self):
        self.s.write("sitemap.xml", SITEMAP.replace(
            "</urlset>", f"  <url><loc>{SITE}/ghost/</loc></url>\n</urlset>"))
        self.fails_with("no page")

    def test_sitemap_missing_page_fails(self):
        self.s.write("sitemap.xml", SITEMAP.replace(
            f"  <url><loc>{SITE}/en/</loc></url>\n", ""))
        self.fails_with("missing from sitemap")

    def test_robots_disallow_fails(self):
        self.s.write("robots.txt", ROBOTS + "Disallow: /hooks/\n")
        self.fails_with("Disallow")

    def test_robots_missing_sitemap_line_fails(self):
        self.s.write("robots.txt", "User-agent: *\nAllow: /\n")
        self.fails_with("Sitemap")

    def test_llms_dead_link_fails(self):
        self.s.write("llms.txt", LLMS + f"- [Ghost]({SITE}/ghost/)\n")
        self.fails_with("dead link")

    def test_write_sitemap_deterministic(self):
        (self.s.dir / "sitemap.xml").unlink()
        r1 = self.s.run("--write-sitemap")
        self.assertEqual(r1.returncode, 0, r1.stdout + r1.stderr)
        first = (self.s.dir / "sitemap.xml").read_bytes()
        self.assertIn(f"{SITE}/en/", first.decode())
        r2 = self.s.run("--write-sitemap")
        self.assertEqual(r2.returncode, 0)
        self.assertEqual(first, (self.s.dir / "sitemap.xml").read_bytes())

    def test_write_sitemap_refuses_file_args(self):
        r = self.s.run("--write-sitemap", "index.html")
        self.assertEqual(r.returncode, 2)

    def test_scoped_run_skips_site_checks(self):
        (self.s.dir / "sitemap.xml").unlink()  # would fail discovery mode
        r = self.s.run("index.html", "en/index.html")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
