#!/usr/bin/env python3
"""fetch_fixtures.py - saves a set of real pages and pictures for the tests.

    python3 test/fetch_fixtures.py            # into test/fixtures/ (git-ignored)

The tests (test_netbook.py, compare.py) use them when they are there and
fall back to their own small made-up pages when they are not, so nothing
here is needed to run the tests. Files already saved are kept; --again
fetches them all again. Pages change: fetch again to refresh. The
files are other people's work: they stay on this computer and are never
committed (test/fixtures/ is in .gitignore).
"""
import json
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "fixtures")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# name, address, kind (page or picture)
ITEMS = [
    ("wiki-psion", "https://en.wikipedia.org/wiki/Psion_(company)", "page"),
    ("wiki-netbook", "https://en.wikipedia.org/wiki/Psion_netBook", "page"),
    ("wiki-table", "https://en.wikipedia.org/wiki/List_of_largest_cities", "page"),
    ("bbc-home", "https://www.bbc.co.uk/news", "page"),
    ("guardian-tech", "https://www.theguardian.com/technology", "page"),
    ("guardian-article", "https://www.theguardian.com/technology/2026/nov/05/"
     "apple-ipad-mini-a20-pro-review-best-small-tablet-but-big-price", "page"),
    ("bbc-article", "https://www.bbc.co.uk/news/articles/c38xzy980924o", "page"),
    ("npr-text", "https://text.npr.org/", "page"),
    ("python-docs", "https://docs.python.org/3/tutorial/datastructures.html", "page"),
    ("hn", "https://news.ycombinator.com/", "page"),
    # (test_text.py) a short page of prose with no headlines, and a
    # disambiguation page: a list of described links
    ("example", "https://example.com/", "page"),
    ("wiki-disambig", "https://en.wikipedia.org/wiki/Psion", "page"),
    # pictures: a photo, a big photo, a drawing with flat colours, a PNG
    # with transparency, a WebP
    ("photo-jpeg", "https://www.gstatic.com/webp/gallery/1.jpg", "picture"),
    ("photo-flowers", "https://www.gstatic.com/webp/gallery/4.jpg", "picture"),
    ("photo-big", "https://picsum.photos/id/1015/2400/1600.jpg", "picture"),
    ("photo-city", "https://picsum.photos/id/1067/1600/1067.jpg", "picture"),
    ("drawing-flag", "https://upload.wikimedia.org/wikipedia/en/thumb/a/ae/"
     "Flag_of_the_United_Kingdom.svg/960px-Flag_of_the_United_Kingdom.svg.png", "picture"),
    ("png-alpha", "https://www.gstatic.com/webp/gallery3/1.png", "picture"),
    ("webp-photo", "https://www.gstatic.com/webp/gallery/1.webp", "picture"),
]


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read(), r.headers.get("Content-Type", ""), r.geturl()


def main():
    os.makedirs(OUT, exist_ok=True)
    index = {}
    try:
        with open(os.path.join(OUT, "index.json")) as f:
            index = json.load(f)
    except (OSError, ValueError):
        pass
    fresh = "--again" in sys.argv
    for name, url, kind in ITEMS:
        if not fresh and name in index and os.path.exists(os.path.join(OUT, index[name]["file"])):
            continue                      # (kept: --again fetches everything)
        time.sleep(1)                     # gently: some sites limit the rate
        try:
            body, ctype, final = fetch(url)
        except Exception as e:
            print("%-14s failed: %s" % (name, e))
            continue
        ext = ".html" if kind == "page" else ""
        path = os.path.join(OUT, name + ext)
        with open(path, "wb") as f:
            f.write(body)
        index[name] = {"url": final, "type": ctype, "kind": kind, "file": name + ext}
        print("%-14s %7d bytes  %s" % (name, len(body), ctype))
    with open(os.path.join(OUT, "index.json"), "w") as f:
        json.dump(index, f, indent=1)
    return 0 if index else 1


if __name__ == "__main__":
    sys.exit(main())
