#!/usr/bin/env python3
"""compare.py - the same pages and pictures as the proxy makes them for the
Series 5mx and for the netBook, side by side.

    python3 test/compare.py                  # writes test/out/ (git-ignored)
    python3 test/compare.py --psiweb ../psiweb   # also screenshots, through PsiWeb

For each saved page (test/fetch_fixtures.py) it writes NAME-5mx.html and
NAME-netbook.html with the bytes, pictures, tables and time each took; for
each picture the 5mx's 16-grey GIF and the netBook's version, with their
sizes, and the same picture dithered to EPOC's palette as GIF and PNG, which
is what a JPEG is measured against (summary.txt and summary.json).

With --psiweb DIR (a PsiWeb checkout with build/links/epoc/psiweb-emu.pe,
PsiWeb 0.83 or later) it also starts this PsiProxy on 127.0.0.1, serves the
saved pages on 127.0.0.2 and opens each through it in PsiWeb's ARM harness
(links/emu/run_links.py), once as a 5mx and once as a netBook: NAME-5mx.png,
NAME-netbook.png and NAME-netbook-2.png (a page down), with the harness's
instruction counts and bytes in summary.json.
"""
import http.server
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TOP = os.path.dirname(HERE)
FIX = os.path.join(HERE, "fixtures")
OUT = os.path.join(HERE, "out")
os.environ.setdefault("PSIPROXY_STATE_DIR", tempfile.mkdtemp(prefix="psiproxy-cmp-"))
os.environ.setdefault("PSIPROXY_CONFIG", os.path.join(os.environ["PSIPROXY_STATE_DIR"], "none.env"))
sys.path.insert(0, TOP)
import psiproxy_core as core            # noqa: E402
from PIL import Image                   # noqa: E402

LINE_BPS = 115200 / 10                  # a 115,200 bps serial line, in bytes a second


def log(_m):
    pass


def slim(html, url, screen):
    core._req.screen = core.screen_for({"x-psi-screen": screen} if screen else {})
    t0 = time.time()
    out = core._render_html_page(core._unhide_clean(html, log), url, log)
    if core._screen().netbook:
        out = core._limit_page(out, url, log)
    return out, (time.time() - t0) * 1000


def pages(idx, res):
    for name, e in sorted(idx.items()):
        if e["kind"] != "page":
            continue
        with open(os.path.join(FIX, e["file"]), "rb") as f:
            raw = f.read()
        html = core._decode_html(raw, e.get("type") or "text/html")
        row = {"name": name, "url": e["url"], "source": len(raw)}
        for scr, hdr in (("5mx", "640x240x16"), ("netbook", "640x480x256")):
            out, ms = slim(html, e["url"], hdr)
            b = core._html_bytes(out)
            with open(os.path.join(OUT, "%s-%s.html" % (name, scr)), "wb") as f:
                f.write(b)
            row[scr] = {"bytes": len(b), "ms": round(ms), "pictures": out.count("<img"),
                        "tables": out.count("<table") - 1, "headings": sum(out.count("<h%d" % i) for i in (1, 2, 3))}
        res["pages"].append(row)


def pictures(idx, res):
    pal = core._epoc_palette_image()
    for name, e in sorted(idx.items()):
        if e["kind"] != "picture":
            continue
        with open(os.path.join(FIX, e["file"]), "rb") as f:
            raw = f.read()
        row = {"name": name, "source": len(raw)}
        t0 = time.time()
        gif = core._transcode_image(raw, log)
        row["5mx"] = {"bytes": len(gif or b""), "ms": round((time.time() - t0) * 1000), "what": "gif 16 greys"}
        if gif:
            with open(os.path.join(OUT, name + "-5mx.gif"), "wb") as f:
                f.write(gif)
        t0 = time.time()
        r = core._transcode_colour(raw, core.SCREEN_NETBOOK, log)
        ms = round((time.time() - t0) * 1000)
        if r:
            data, ctype, how = r
            ext = ctype.split("/")[1]
            with open(os.path.join(OUT, "%s-netbook.%s" % (name, ext)), "wb") as f:
                f.write(data)
            row["netbook"] = {"bytes": len(data), "ms": ms, "what": how}
            # the same picture dithered to EPOC's palette, as GIF and PNG
            im = Image.open(io.BytesIO(data)).convert("RGB")
            q = im.quantize(palette=pal, dither=Image.Dither.FLOYDSTEINBERG)
            for fmt in ("GIF", "PNG"):
                b = io.BytesIO()
                q.save(b, fmt, optimize=True)
                row["dithered-" + fmt.lower()] = len(b.getvalue())
        res["pictures"].append(row)


# ---- screenshots through PsiWeb's ARM harness -------------------------------

class _Fixtures(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=FIX, **k)

    def log_message(self, *a):
        pass


def free_port(addr="127.0.0.1"):
    s = socket.socket()
    s.bind((addr, 0))
    p = s.getsockname()[1]
    s.close()
    return p


def shots(psiweb, idx, res, only):
    harness = os.path.join(psiweb, "links", "emu", "run_links.py")
    pe = os.path.join(psiweb, "build", "links", "epoc", "psiweb-emu.pe")
    if not (os.path.exists(harness) and os.path.exists(pe)):
        print("no PsiWeb harness or psiweb-emu.pe in %s" % psiweb)
        return
    site = http.server.ThreadingHTTPServer(("127.0.0.2", 0), _Fixtures)
    threading.Thread(target=site.serve_forever, daemon=True).start()
    port = free_port()
    env = dict(os.environ, PSIPROXY_ADDR="127.0.0.1", PSIPROXY_PORT=str(port),
               PSIPROXY_ALLOW_PRIVATE="1", PSIPROXY_JS_RENDER="0", PSIPROXY_PLUGINS="none",
               PSIPROXY_PUTLOG="0")
    proc = subprocess.Popen([sys.executable, os.path.join(TOP, "psiproxyd.py")], env=env,
                            stdout=open(os.path.join(OUT, "psiproxy.log"), "w"), stderr=subprocess.STDOUT)
    try:
        time.sleep(1.5)
        jobs = []
        for name, e in sorted(idx.items()):
            if only and name not in only:
                continue
            if e["kind"] == "page":
                url = "http://127.0.0.2:%d/%s" % (site.server_address[1], e["file"])
            else:
                continue
            for scr, opts in (("5mx", []), ("netbook", ["--netbook"])):
                script = os.path.join(OUT, "%s-%s.txt" % (name, scr))
                with open(script, "w") as f:
                    f.write("open %s\nidle\nshot %s\nkey 4\nidle\nshot %s\nquit\n"
                            % (url, os.path.join(OUT, "%s-%s.png" % (name, scr)),
                               os.path.join(OUT, "%s-%s-2.png" % (name, scr))))
                j = os.path.join(OUT, "%s-%s.json" % (name, scr))
                cmd = [sys.executable, harness, "--count", "--images", "--proxy", "127.0.0.1:%d" % port,
                       "--json", j] + opts + [script]
                jobs.append((name, scr, j, cmd))
        running = []
        while jobs or running:
            while jobs and len(running) < 3:
                name, scr, j, cmd = jobs.pop(0)
                lf = open(os.path.join(OUT, "%s-%s.log" % (name, scr)), "w")
                running.append((name, scr, j, subprocess.Popen(cmd, stdout=lf, stderr=subprocess.STDOUT), time.time()))
            time.sleep(0.5)
            for r in list(running):
                name, scr, j, p, t0 = r
                if p.poll() is None and time.time() - t0 < 900:
                    continue
                if p.poll() is None:
                    p.kill()
                running.remove(r)
                try:
                    with open(j) as f:
                        d = json.load(f)
                    page = [x for x in d["pages"] if x["what"].startswith("open")][0]
                    res.setdefault("psiweb", {}).setdefault(name, {})[scr] = {
                        k: page.get(k) for k in ("insns", "bytes_in", "heap_peak", "alloc_fails")}
                except Exception as ex:
                    res.setdefault("psiweb", {}).setdefault(name, {})[scr] = {"error": str(ex)}
                print("  %s %s done" % (name, scr))
    finally:
        proc.terminate()
        site.shutdown()


def summary(res):
    lines = ["Pages (slimmed HTML; secs = on a 115,200 bps line, before gzip)", ""]
    lines.append("%-15s %9s | %8s %4s %3s %3s | %8s %4s %3s %3s %6s" %
                 ("page", "source", "5mx", "pics", "tbl", "h", "netBook", "pics", "tbl", "h", "ms"))
    for r in res["pages"]:
        a, b = r["5mx"], r["netbook"]
        lines.append("%-15s %9d | %8d %4d %3d %3d | %8d %4d %3d %3d %6d" %
                     (r["name"], r["source"], a["bytes"], a["pictures"], a["tables"], a["headings"],
                      b["bytes"], b["pictures"], b["tables"], b["headings"], b["ms"]))
    lines += ["", "Pictures (bytes; the netBook's choice against the same picture dithered to EPOC's palette)", ""]
    lines.append("%-14s %8s | %8s | %8s %-26s | %8s %8s" %
                 ("picture", "source", "5mx gif", "netBook", "", "dith gif", "dith png"))
    for r in res["pictures"]:
        nb = r.get("netbook") or {}
        lines.append("%-14s %8d | %8d | %8s %-26s | %8s %8s" %
                     (r["name"], r["source"], r["5mx"]["bytes"], nb.get("bytes", "-"), nb.get("what", "")[:26],
                      r.get("dithered-gif", "-"), r.get("dithered-png", "-")))
    if res.get("psiweb"):
        lines += ["", "PsiWeb (ARM harness): instructions to lay the page out and draw it, bytes over the line",
                  ""]
        for name, d in sorted(res["psiweb"].items()):
            for scr in ("5mx", "netbook"):
                x = d.get(scr, {})
                lines.append("%-15s %-8s %12s insns %9s bytes  heap peak %9s" %
                             (name, scr, x.get("insns"), x.get("bytes_in"), x.get("heap_peak")))
    return "\n".join(lines) + "\n"


def main():
    if not os.path.exists(os.path.join(FIX, "index.json")):
        print("no fixtures: run test/fetch_fixtures.py first")
        return 1
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(FIX, "index.json")) as f:
        idx = json.load(f)
    res = {"pages": [], "pictures": []}
    pages(idx, res)
    pictures(idx, res)
    if "--psiweb" in sys.argv:
        only = [a for a in sys.argv[sys.argv.index("--psiweb") + 2:] if not a.startswith("--")]
        shots(sys.argv[sys.argv.index("--psiweb") + 1], idx, res, only)
    with open(os.path.join(OUT, "summary.json"), "w") as f:
        json.dump(res, f, indent=1)
    text = summary(res)
    with open(os.path.join(OUT, "summary.txt"), "w") as f:
        f.write(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
