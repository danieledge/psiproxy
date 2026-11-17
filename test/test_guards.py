#!/usr/bin/env python3
"""test_guards.py - host tests for the proxy's limits on what a site (or a
page's own requests) can make it do.

    python3 test/test_guards.py

- a gzipped body unpacks to at most MAX_INFLATED;
- a redirect is followed to http and https only (urllib's own FTP handler
  is outside the destination check), and the Psion's cookies and password
  for one site do not go with it to another;
- a 16-grey picture bigger than 40 million pixels is not decoded;
- /_putlog takes a POST only;
- a download stops being fetched once the client has gone.
Uses its own settings folder: never the live proxy's.
"""
import gzip
import http.server
import io
import os
import socket
import sys
import tempfile
import threading
import time
import unittest
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
TOP = os.path.dirname(HERE)
STATE_DIR = tempfile.mkdtemp(prefix="psiproxy-test-")
os.environ["PSIPROXY_STATE_DIR"] = STATE_DIR       # never the user's own settings
os.environ["PSIPROXY_CONFIG"] = os.path.join(STATE_DIR, "none.env")
os.environ["PSIPROXY_LOG_DIR"] = os.path.join(STATE_DIR, "logs")
os.environ["PSIPROXY_ALLOW_PRIVATE"] = "1"         # the test sites are on 127.0.0.1
sys.path.insert(0, TOP)
import psiproxy_core as core                       # noqa: E402


def log(_msg):
    pass


class _Body:
    def __init__(self, data):
        self.data = data

    def read(self, n):
        return self.data[:n]


class TestInflate(unittest.TestCase):
    PAGE = b"<html>" + b"netBook " * 20000 + b"</html>"

    def decoded(self, data, enc):
        return core._read_body_decoded(_Body(data), {"Content-Encoding": enc}, "GET")[0]

    def test_ordinary_bodies(self):
        self.assertEqual(self.decoded(gzip.compress(self.PAGE), "gzip"), self.PAGE)
        self.assertEqual(self.decoded(zlib.compress(self.PAGE), "deflate"), self.PAGE)
        self.assertEqual(self.decoded(zlib.compress(self.PAGE)[2:-4], "deflate"), self.PAGE)
        two = gzip.compress(self.PAGE[:100]) + gzip.compress(self.PAGE[100:])
        self.assertEqual(self.decoded(two, "gzip"), self.PAGE)

    def test_not_gzip_is_passed_on(self):
        self.assertEqual(self.decoded(b"not gzip at all", "gzip"), b"not gzip at all")

    def test_bomb_is_capped(self):
        bomb = gzip.compress(b"\0" * (core.MAX_INFLATED + 8 * 1024 * 1024))
        self.assertLess(len(bomb), core.MAX_BODY)
        self.assertEqual(len(self.decoded(bomb, "gzip")), core.MAX_INFLATED)


class TestRedirect(unittest.TestCase):
    def test_ftp_redirect_is_not_followed(self):
        ftp = socket.socket()
        ftp.bind(("127.0.0.1", 0))
        ftp.listen(1)
        ftp.settimeout(1.0)
        port = ftp.getsockname()[1]

        class Site(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(302)
                self.send_header("Location", "ftp://127.0.0.1:%d/x" % port)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *a):
                pass
        srv = http.server.HTTPServer(("127.0.0.1", 0), Site)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            with self.assertRaises(core.BlockedDestination):
                core._open_upstream("GET", "http://127.0.0.1:%d/" % srv.server_port,
                                    {}, None, False, None, log)
            with self.assertRaises(socket.timeout):
                ftp.accept()                       # nothing came to the FTP port
        finally:
            srv.shutdown()
            srv.server_close()
            ftp.close()


class TestRedirectHeaders(unittest.TestCase):
    """The Psion's Cookie and Authorization for one site do not follow a
    redirect to another (localhost and 127.0.0.1 stand for two sites)."""
    def fetch(self, first_host, second_host):
        seen = {}

        class Site(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/a":
                    self.send_response(302)
                    self.send_header("Location", "http://%s:%d/b" % (second_host, self.server.server_port))
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                seen["cookie"] = self.headers.get("Cookie")
                seen["auth"] = self.headers.get("Authorization")
                seen["lang"] = self.headers.get("Accept-Language")
                self.send_response(200)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"ok")

            def log_message(self, *a):
                pass
        srv = http.server.HTTPServer(("127.0.0.1", 0), Site)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            r = core._open_upstream("GET", "http://%s:%d/a" % (first_host, srv.server_port),
                                    {"cookie": "sid=secret", "authorization": "Basic eDp5",
                                     "accept-language": "en-GB"}, None, False, None, log)
            r[0].read()
            r[0].close()
        finally:
            srv.shutdown()
            srv.server_close()
        return seen

    def test_same_site_keeps_them(self):
        seen = self.fetch("127.0.0.1", "127.0.0.1")
        self.assertEqual((seen["cookie"], seen["auth"], seen["lang"]), ("sid=secret", "Basic eDp5", "en-GB"))

    def test_other_site_does_not_get_them(self):
        seen = self.fetch("localhost", "127.0.0.1")
        self.assertEqual((seen["cookie"], seen["auth"], seen["lang"]), (None, None, "en-GB"))

    def test_same_site(self):
        self.assertTrue(core._same_site("http://example.com/", "https://www.example.com/x"))
        self.assertTrue(core._same_site("http://www.example.com/", "http://example.com/"))
        self.assertFalse(core._same_site("http://example.com/", "http://badexample.com/"))
        self.assertFalse(core._same_site("http://a.example.com/", "http://b.example.com/"))


class TestPictures(unittest.TestCase):
    def test_huge_picture_is_not_decoded(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("no Pillow")
        im = Image.new("1", (8000, 6000))          # 48 million pixels, a few KB as PNG
        b = io.BytesIO()
        im.save(b, "PNG")
        self.assertIsNone(core._transcode_image(b.getvalue(), log))
        im = Image.new("1", (800, 600))
        b = io.BytesIO()
        im.save(b, "PNG")
        self.assertTrue(core._transcode_image(b.getvalue(), log).startswith(b"GIF8"))


class _Pipe:
    """A transport that keeps what is sent; 'gone' makes send fail."""
    def __init__(self, gone_after=None):
        self.out = bytearray()
        self.gone_after = gone_after

    def stopped(self):
        return False

    def recv(self):
        return b""

    def send(self, data):
        if self.gone_after is not None and len(self.out) >= self.gone_after:
            return False
        self.out += data
        return True


class TestRoutes(unittest.TestCase):
    def run_one(self, request):
        t = _Pipe()
        s = core.ProxySession(t, log, local_names={"127.0.0.1"})
        head, _, body = request.partition(b"\r\n\r\n")
        s.handle(head, body)
        return bytes(t.out)

    def test_putlog_is_post_only(self):
        d = os.environ["PSIPROXY_LOG_DIR"]
        got = self.run_one(b"GET /_putlog?app=PsiWeb HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n")
        self.assertTrue(got.startswith(b"HTTP/1.1 405 "), got[:40])
        self.assertFalse(os.path.isdir(d) and os.listdir(d))
        got = self.run_one(b"POST /_putlog?app=PsiWeb HTTP/1.0\r\nHost: 127.0.0.1\r\n"
                           b"Content-Length: 5\r\n\r\nhello")
        self.assertIn(b"Log saved: PsiWeb-", got)
        self.assertEqual(len(os.listdir(d)), 1)

    def test_download_stops_when_the_client_goes(self):
        class Upstream:
            def __init__(self):
                self.reads = 0

            def read(self, n):
                self.reads += 1
                return b"x" * n if self.reads < 1000 else b""

            def close(self):
                pass

        class Hdrs(dict):
            def get_all(self, k):
                return None
        t = _Pipe(gone_after=200000)
        s = core.ProxySession(t, log)
        up = Upstream()
        sent, closed = s._stream_passthrough(up, 200, "OK", Hdrs({"Content-Length": "65536000"}),
                                             "GET", False)
        self.assertTrue(closed)
        self.assertLess(up.reads, 10)


if __name__ == "__main__":
    unittest.main(verbosity=2)
