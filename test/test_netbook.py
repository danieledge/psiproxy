#!/usr/bin/env python3
"""test_netbook.py - host tests for the netBook output, and a check that the
Series 5mx's output is exactly what it was.

    python3 test/test_netbook.py            # or: python3 -m unittest discover test

Needs Pillow and lxml (trafilatura and readability make the article tests
meaningful; without them those pages are slimmed whole). Uses the saved real
pages and pictures in test/fixtures/ when test/fetch_fixtures.py has been
run, and small made-up ones otherwise. The 5mx check compares this
checkout's output with that of psiproxy_core.py before the netBook output
(BASELINE_REF, or the file named by $PSIPROXY_BASELINE): it is skipped
outside a git checkout.
"""
import http.server
import importlib.util
import io
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
TOP = os.path.dirname(HERE)
FIX = os.path.join(HERE, "fixtures")
STATE_DIR = tempfile.mkdtemp(prefix="psiproxy-test-")
os.environ["PSIPROXY_STATE_DIR"] = STATE_DIR       # never the user's own settings
os.environ["PSIPROXY_CONFIG"] = os.path.join(STATE_DIR, "none.env")
sys.path.insert(0, TOP)
import psiproxy_core as core                       # noqa: E402

from PIL import Image                              # noqa: E402

NB = "640x480x256"
MX = "640x240x16"


def log(_msg):
    pass


# the last version before the netBook output (October 2026): the 5mx's
# output must stay byte for byte what it gave. Move it on only with a
# change to the 5mx's output that is meant.
BASELINE_REF = os.environ.get("PSIPROXY_BASELINE_REF", "84c7707")
# saved pages whose 5mx output has changed on purpose since BASELINE_REF:
# for these the check is that no text is lost, not the same bytes
MEANT_5MX_CHANGES = {
    # 1.03: pages that came back with no text, or only links
    "example": "a short page of prose kept as an article, not an empty index",
    "wiki-disambig": "a list item keeps the words that say what its link is",
    "wiki-netbook": "a prose-rich page is an article, whatever its story links",
    "guardian-article": "the same",
    "wiki-table": "four reference items keep their words",
}


def load_baseline():
    """psiproxy_core.py as it was (BASELINE_REF in git, or the file named by
    $PSIPROXY_BASELINE), as a separate module, or None."""
    path = os.environ.get("PSIPROXY_BASELINE")
    src = None
    if path:
        with open(path) as f:
            src = f.read()
    else:
        try:
            src = subprocess.run(["git", "-C", TOP, "show", BASELINE_REF + ":psiproxy_core.py"],
                                 capture_output=True, text=True, check=True).stdout
        except Exception:
            return None
    d = tempfile.mkdtemp(prefix="psiproxy-base-")
    p = os.path.join(d, "psiproxy_core_base.py")
    with open(p, "w") as f:
        f.write(src)
    spec = importlib.util.spec_from_file_location("psiproxy_core_base", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---- made-up pages and pictures ---------------------------------------------

def synthetic_article():
    para = ("The netBook has a 640 by 480 screen in 256 colours, a 190 MHz "
            "StrongARM and a proper keyboard. It runs EPOC Release 5. ") * 4
    rows = "".join("<tr><td>Model %d</td><td>%d MB</td><td>%d MHz</td></tr>" % (i, 8 * i, 36 * i)
                   for i in range(1, 6))
    wide = "".join("<td>c%d</td>" % i for i in range(9))
    return ("<html><head><title>The Psion netBook</title></head><body>"
            "<nav><a href='/'>Home</a> <a href='/news'>News</a></nav>"
            "<article><h1>The Psion netBook</h1>"
            + "".join("<p>%s</p>" % para for _ in range(6)) +
            "<h2>Models</h2><table><thead><tr><th>Model</th><th>RAM</th><th>CPU</th></tr></thead>"
            "<tbody>%s</tbody></table>" % rows +
            "<h2>Wide</h2><table><tr>%s</tr><tr>%s</tr></table>" % (wide, wide) +
            "<ul><li>One</li><li>Two</li></ul>"
            "<p><img src='http://example.com/a.jpg' alt='A'></p>"
            + "".join("<p>%s</p>" % para for _ in range(4)) +
            "</article><footer>Footer</footer></body></html>")


def synthetic_photo(w=1200, h=800):
    """Gradients with grain: a JPEG of it at 560 is well over 12 KB, as a
    real photo's is."""
    import random
    rnd = random.Random(5)
    im = Image.new("RGB", (w, h))
    px = im.load()
    for y in range(h):
        for x in range(w):
            n = rnd.randint(-40, 40)
            px[x, y] = (max(0, min(255, (x * 255) // w + n)), max(0, min(255, (y * 255) // h - n)),
                        ((x * 7 + y * 3) // 5) % 256)
    b = io.BytesIO()
    im.save(b, "JPEG", quality=90)
    return b.getvalue()


def synthetic_logo():
    im = Image.new("RGBA", (300, 120), (0, 0, 0, 0))
    for x in range(40, 260):
        for y in range(20, 100):
            im.putpixel((x, y), (200, 30, 30, 255) if x < 150 else (20, 40, 160, 255))
    b = io.BytesIO()
    im.save(b, "PNG")
    return b.getvalue()


def fixture(name):
    try:
        with open(os.path.join(FIX, "index.json")) as f:
            idx = json.load(f)
        e = idx[name]
        with open(os.path.join(FIX, e["file"]), "rb") as f:
            return f.read(), e["url"]
    except (OSError, KeyError, ValueError):
        return None, None


def fixture_pages():
    try:
        with open(os.path.join(FIX, "index.json")) as f:
            idx = json.load(f)
    except (OSError, ValueError):
        return []
    return [n for n, e in sorted(idx.items()) if e["kind"] == "page"]


def slim(mod, html, url, screen):
    """A page through mod's pipeline as handle() runs it, for one screen."""
    if hasattr(mod, "_req"):
        mod._req.screen = mod.screen_for({"x-psi-screen": screen} if screen else {})
    cleaned = mod._unhide_clean(html, log)
    out = mod._render_html_page(cleaned, url, log)
    if hasattr(mod, "_req") and mod._screen().netbook:
        out = mod._limit_page(out, url, log)
    return out


# ---- the tests ---------------------------------------------------------------

class TestScreen(unittest.TestCase):
    def test_header(self):
        self.assertEqual(core.screen_for({}).name, "5mx")
        self.assertEqual(core.screen_for({"x-psi-screen": MX}).name, "5mx")
        s = core.screen_for({"x-psi-screen": NB})
        self.assertTrue(s.netbook)
        self.assertEqual((s.img_maxw, s.column), (560, 600))
        self.assertEqual(core.screen_for({"x-psi-screen": " 640 x 480 x 256 "}).name, "netbook")

    def test_bad_headers_are_the_5mx(self):
        for v in ("", "x", "640x480", "99999x480x256", "640x480x-1", "640x480x256;drop",
                  "<script>", "0x0x0", "640x480x256" + "9" * 50):
            self.assertFalse(core.screen_for({"x-psi-screen": v}).netbook, v)

    def test_narrow_colour_screen(self):
        s = core.screen_for({"x-psi-screen": "480x320x65536"})
        self.assertTrue(s.netbook)
        self.assertLessEqual(s.column, 440)
        self.assertLessEqual(s.img_maxw, s.column)

    def test_forced(self):
        self.assertTrue(core.screen_for({}, "netbook").netbook)
        self.assertFalse(core.screen_for({"x-psi-screen": NB}, "5mx").netbook)

    def test_palette(self):
        pal = core.EPOC256
        self.assertEqual(len(pal), 256)
        self.assertEqual(len(set(pal)), 256)
        self.assertEqual(pal[0], (0, 0, 0))
        self.assertEqual(pal[255], (255, 255, 255))
        self.assertEqual(pal[1], (0x33, 0, 0))         # TRgb 0x000033: red 0x33
        self.assertEqual(pal[108], (0x11, 0x11, 0x11))
        # PsiWeb's own copy, when its checkout is beside this one
        h = os.path.join(TOP, "..", "psiweb", "links", "psi_pal.h")
        if os.path.exists(h):
            with open(h) as f:
                vals = [int(x, 16) for x in re.findall(r"0x([0-9a-f]{6})", f.read())][:256]
            self.assertEqual(pal, [(v & 255, (v >> 8) & 255, v >> 16) for v in vals])


class TestPictures(unittest.TestCase):
    def setUp(self):
        core._req.screen = core.SCREEN_NETBOOK

    def test_photo_is_a_colour_jpeg_at_560(self):
        data, ctype, how = core._transcode_colour(synthetic_photo(), core.SCREEN_NETBOOK, log)
        self.assertEqual(ctype, "image/jpeg")
        im = Image.open(io.BytesIO(data))
        self.assertEqual(im.mode, "RGB")
        self.assertEqual(im.width, 560)
        self.assertLessEqual(len(data), core.NB_IMG_BUDGET)
        self.assertNotIn(b"\xff\xc2", data)             # baseline, not progressive

    def test_small_photo_is_a_dithered_png(self):
        # (PsiWeb draws a small JPEG black on the netBook: see NB_SMALL_JPEG)
        b = io.BytesIO()
        Image.open(io.BytesIO(synthetic_photo())).resize((200, 120)).save(b, "JPEG", quality=80)
        data, ctype, how = core._transcode_colour(b.getvalue(), core.SCREEN_NETBOOK, log)
        self.assertEqual(ctype, "image/png")
        im = Image.open(io.BytesIO(data)).convert("RGB")
        self.assertTrue(set(c for _, c in im.getcolors(1 << 16)) <= set(core.EPOC256))

    def test_logo_is_epoc_palette_png_on_white(self):
        data, ctype, how = core._transcode_colour(synthetic_logo(), core.SCREEN_NETBOOK, log)
        self.assertEqual(ctype, "image/png")
        im = Image.open(io.BytesIO(data)).convert("RGB")
        cols = set(c for _, c in im.getcolors(1024))
        self.assertTrue(cols <= set(core.EPOC256), cols - set(core.EPOC256))
        self.assertEqual(im.getpixel((0, 0)), (255, 255, 255))   # transparency on white

    def test_tall_picture_fits(self):
        b = io.BytesIO()
        Image.new("RGB", (800, 6000), (10, 200, 30)).save(b, "PNG")
        data, ctype, how = core._transcode_colour(b.getvalue(), core.SCREEN_NETBOOK, log)
        im = Image.open(io.BytesIO(data))
        self.assertLessEqual(im.height, core.NB_IMG_MAXH)
        self.assertLessEqual(im.width, 560)

    def test_rubbish_is_passed_on(self):
        self.assertIsNone(core._transcode_colour(b"not a picture", core.SCREEN_NETBOOK, log))

    def test_5mx_pictures_unchanged(self):
        gif = core._transcode_image(synthetic_photo(), log)
        im = Image.open(io.BytesIO(gif))
        self.assertEqual(im.format, "GIF")
        self.assertEqual(im.width, 320)
        self.assertLessEqual(len(set(im.convert("L").getdata())), 16)

    def test_fixture_pictures(self):
        names = ["photo-jpeg", "photo-flowers", "photo-big", "photo-city", "png-alpha",
                 "drawing-flag", "webp-photo"]
        seen = 0
        for n in names:
            data, _ = fixture(n)
            if not data:
                continue
            seen += 1
            res = core._transcode_colour(data, core.SCREEN_NETBOOK, log)
            self.assertIsNotNone(res, n)
            out, ctype, how = res
            im = Image.open(io.BytesIO(out))
            self.assertLessEqual(im.width, 560, n)
            self.assertLessEqual(len(out), max(core.NB_IMG_BUDGET, len(data)), n)
            self.assertIn(ctype, ("image/jpeg", "image/png", "image/gif"), n)
        if not seen:
            self.skipTest("no fixtures (test/fetch_fixtures.py)")


class TestPages(unittest.TestCase):
    def test_tables_kept_where_they_fit(self):
        out = slim(core, synthetic_article(), "http://example.com/2026/11/netbook-article", NB)
        self.assertIn("<table", out)
        self.assertIn("Model 3", out)
        self.assertIn('border="1"', out)
        # the 9-column table is flattened into lines
        self.assertIn("c0 | c1", out)
        self.assertIn('<table width="600"', out)

    def test_5mx_has_no_tables(self):
        out = slim(core, synthetic_article(), "http://example.com/2026/11/netbook-article", MX)
        self.assertNotIn("border=", out)
        self.assertIn('<table width="560"', out)

    def test_limits(self):
        core._req.screen = core.SCREEN_NETBOOK
        imgs = "".join('<p><img src="http://e.com/%d.jpg"></p>' % i for i in range(40))
        out = core._limit_page(imgs, "http://e.com/", log)
        self.assertEqual(out.count("<img"), core.NB_PAGE_PICTURES)
        self.assertEqual(out.count("[Picture]"), 40 - core.NB_PAGE_PICTURES)
        big = "<ul>" + "".join("<li><p>%s</p></li>" % ("word " * 60) for _ in range(800)) + "</ul>"
        out = core._limit_page('<table width="600"><tr><td>' + big, "http://e.com/x", log)
        self.assertLess(len(out), core.NB_PAGE_MAX + 2048)
        self.assertIn("Page shortened for the netBook", out)
        self.assertEqual(out.count("<ul>"), out.count("</ul>"))

    def test_fixture_pages_netbook(self):
        pages = fixture_pages()
        if not pages:
            self.skipTest("no fixtures (test/fetch_fixtures.py)")
        for n in pages:
            data, url = fixture(n)
            html = core._decode_html(data, "text/html; charset=utf-8")
            t0 = time.time()
            out = slim(core, html, url, NB)
            ms = (time.time() - t0) * 1000
            self.assertLess(len(out.encode("utf-8")), core.NB_PAGE_MAX + 4096, n)
            self.assertLessEqual(out.count("<img"), core.NB_PAGE_PICTURES, n)
            self.assertNotIn("<script", out.lower(), n)
            self.assertLess(ms, 20000, n)


class TestFiveMxUnchanged(unittest.TestCase):
    """The one-Coda rule: a request without X-Psi-Screen, or with the 5mx's,
    gets byte for byte what the proxy gave before this change."""
    @classmethod
    def setUpClass(cls):
        cls.base = load_baseline()

    def setUp(self):
        if self.base is None:
            self.skipTest("no baseline (not a git checkout)")

    def compare(self, html, url):
        for flags in ({"reading": False}, {"reading": True}):
            for mod in (core, self.base):
                mod.STATE.reading = flags["reading"]
            before = slim(self.base, html, url, None)
            after_none = slim(core, html, url, None)
            after_mx = slim(core, html, url, MX)
            self.assertEqual(before, after_none, "%s %s" % (url, flags))
            self.assertEqual(before, after_mx, "%s %s" % (url, flags))
        for mod in (core, self.base):
            mod.STATE.reading = False

    def test_synthetic(self):
        self.compare(synthetic_article(), "http://example.com/2026/11/netbook-article")
        self.compare(synthetic_article(), "http://example.com/")

    def test_fixtures(self):
        pages = fixture_pages()
        if not pages:
            self.skipTest("no fixtures (test/fetch_fixtures.py)")
        for n in pages:
            data, url = fixture(n)
            html = core._decode_html(data, "text/html; charset=utf-8")
            if n in MEANT_5MX_CHANGES:
                self.more_text(html, url, n)
            else:
                self.compare(html, url)

    def more_text(self, html, url, n):
        """A page whose 5mx output changed on purpose: it shows at least the
        text it did (test_text.py checks what it now shows)."""
        for reading in (False, True):
            for mod in (core, self.base):
                mod.STATE.reading = reading
            before = len(core._visible_text(slim(self.base, html, url, None)))
            after = len(core._visible_text(slim(core, html, url, MX)))
            self.assertGreaterEqual(after, before, "%s reading=%s" % (n, reading))
        for mod in (core, self.base):
            mod.STATE.reading = False

    def test_pictures(self):
        for data in (synthetic_photo(), synthetic_logo()):
            self.assertEqual(core._transcode_image(data, log), self.base._transcode_image(data, log))


# ---- end to end: the daemon, a local site, a client that says which screen

class _Site(http.server.SimpleHTTPRequestHandler):
    files = {}

    def do_GET(self):
        body, ctype = self.files.get(self.path, (None, None))
        if body is None:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class TestEndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _Site.files = {
            "/photo.jpg": (synthetic_photo(), "image/jpeg"),
            "/logo.png": (synthetic_logo(), "image/png"),
            "/2026/11/article": (synthetic_article().encode(), "text/html; charset=utf-8"),
        }
        # (127.0.0.2: an address that is not the proxy's own, which would be
        # its control page)
        cls.site = http.server.ThreadingHTTPServer(("127.0.0.2", 0), _Site)
        threading.Thread(target=cls.site.serve_forever, daemon=True).start()
        cls.port = free_port()
        env = dict(os.environ, PSIPROXY_ADDR="127.0.0.1", PSIPROXY_PORT=str(cls.port),
                   PSIPROXY_ALLOW_PRIVATE="1", PSIPROXY_JS_RENDER="0", PSIPROXY_PLUGINS="none",
                   PSIPROXY_PUTLOG="0", PSIPROXY_STATE_DIR=tempfile.mkdtemp(prefix="psiproxy-e2e-"))
        cls.proc = subprocess.Popen([sys.executable, os.path.join(TOP, "psiproxyd.py")], env=env,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                socket.create_connection(("127.0.0.1", cls.port), 0.2).close()
                break
            except OSError:
                time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(5)
        cls.site.shutdown()

    def get(self, path, screen=None, accept="image/gif, image/jpeg, image/png"):
        url = "http://127.0.0.2:%d%s" % (self.site.server_address[1], path)
        op = urllib.request.build_opener(urllib.request.ProxyHandler({"http": "http://127.0.0.1:%d" % self.port}))
        h = {"Accept": accept}
        if screen:
            h["X-Psi-Screen"] = screen
        with op.open(urllib.request.Request(url, headers=h), timeout=60) as r:
            return r.read(), r.headers.get("Content-Type")

    def test_picture_per_screen(self):
        body, ctype = self.get("/photo.jpg")
        self.assertEqual(ctype, "image/gif")
        self.assertEqual(Image.open(io.BytesIO(body)).width, 320)
        body, ctype = self.get("/photo.jpg", MX)
        self.assertEqual(ctype, "image/gif")
        body, ctype = self.get("/photo.jpg", NB)
        self.assertEqual(ctype, "image/jpeg")
        self.assertEqual(Image.open(io.BytesIO(body)).width, 560)
        body, ctype = self.get("/logo.png", NB)
        self.assertEqual(ctype, "image/png")

    def test_page_per_screen(self):
        a, _ = self.get("/2026/11/article", None, "text/html")
        b, _ = self.get("/2026/11/article", NB, "text/html")
        self.assertNotIn(b"border=", a)
        self.assertIn(b'border="1"', b)
        self.assertIn(b'<table width="600"', b)


if __name__ == "__main__":
    unittest.main(verbosity=2)
