#!/usr/bin/env python3
"""test_text.py - pages must keep their text (PsiProxy 1.03).

    python3 test/test_text.py

Up to 1.02 three kinds of page lost their words on the way to the Psion:
- a short page of prose with no headlines (example.com) came back empty:
  the article was "thin", and the index view of it had nothing to list;
- a disambiguation page (en.wikipedia.org/wiki/Psion) came back as bare
  links, the words that say what each one is dropped;
- a short article with a big infobox and navboxes (Psion netBook on
  Wikipedia) was taken for an index, as Wikipedia's every /wiki/ link
  looks like a story's, and came back as lists of links.
The saved real pages (test/fetch_fixtures.py: example, wiki-disambig,
wiki-netbook) are used when they are there; small made-up pages of the
same shape always run. Needs lxml; trafilatura or readability for the
article tests.
"""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import test_netbook as T                            # noqa: E402  (own settings folder)

core = T.core
NB, MX = T.NB, T.MX
HAVE_EXTRACTOR = core.trafilatura is not None or core._readability is not None


def text_of(html, url, screen=None, reading=False):
    core.STATE.reading = reading
    try:
        return core._visible_text(T.slim(core, html, url, screen))
    finally:
        core.STATE.reading = False


def saved(name):
    data, url = T.fixture(name)
    if data is None:
        return None, None
    return core._decode_html(data, "text/html; charset=utf-8"), url


# ---- made-up pages of the same shape ----------------------------------------

def made_up_short_page():
    return ("<!doctype html><html><head><title>Example Domain</title></head><body>"
            "<div><h1>Example Domain</h1>"
            "<p>This domain is for use in documentation examples without needing "
            "permission. This is not a service; avoid relying on it for testing.</p>"
            '<p><a href="https://www.iana.org/help/example-domains">Learn more</a></p>'
            "</div></body></html>")


def made_up_disambiguation():
    items = [
        ("/wiki/Psion_(comics)", "Psion (comics)", ", a DC Comics extraterrestrial species"),
        ("/wiki/Psion_(company)", "Psion (company)", ", a British mobile computer company"),
        ("/wiki/J/psi_meson", "Psion", ", the J/psi meson subatomic particle"),
        ("/wiki/Psion_(novel)", "Psion", ", a 1982 novel by Joan D. Vinge"),
    ]
    lis = "".join('<li><a href="%s">%s</a>%s</li>' % it for it in items)
    nav = "".join('<li><a href="/wiki/Nav_%d">Nav %d</a></li>' % (i, i) for i in range(30))
    cites = "".join('<li><a href="#cite_ref-%d">^</a> A source, a book about it, %d.</li>'
                    % (i, 1990 + i) for i in range(3))
    return ("<html><head><title>Psion - Wikipedia</title></head><body>"
            "<ul>%s</ul><main><h1>Psion</h1><p>Psion may refer to:</p>"
            "<h2>Uses</h2><ul>%s</ul><ol class=\"references\">%s</ol></main></body></html>"
            % (nav, lis, cites))


def made_up_short_article():
    """A short article (a few paragraphs, many in-text /wiki/ links) under a
    big box of links, as a Wikipedia stub with navboxes is."""
    para = ('<p>The <a href="/wiki/Psion_netBook">netBook</a> is a subnotebook made by '
            '<a href="/wiki/Psion">Psion</a> from 1999, with a <a href="/wiki/StrongARM">'
            'StrongARM</a> processor and a colour screen of 640 by 480 pixels, running '
            '<a href="/wiki/EPOC">EPOC</a> from its read-only memory.</p>')
    box = "".join('<li><a href="/wiki/Device_%d">Psion device %d</a></li>' % (i, i)
                  for i in range(25))
    return ("<html><head><title>Psion netBook - Wikipedia</title></head><body>"
            "<main><h1>Psion netBook</h1>%s<h2>Hardware</h2>%s<h2>Software</h2>%s"
            "<div class=\"navbox\"><ul>%s</ul></div></main></body></html>"
            % (para * 3, para * 2, para * 2, box))


# ---- the tests ---------------------------------------------------------------

@unittest.skipUnless(HAVE_EXTRACTOR, "needs trafilatura or readability")
class TestShortPage(unittest.TestCase):
    def check(self, html, url):
        for screen in (None, MX, NB):
            for reading in (False, True):
                t = text_of(html, url, screen, reading)
                self.assertIn("documentation examples", t, (screen, reading))

    def test_made_up(self):
        self.check(made_up_short_page(), "http://example.com/")

    def test_saved(self):
        html, url = saved("example")
        if html is None:
            self.skipTest("no saved page (test/fetch_fixtures.py)")
        self.check(html, url)


class TestDisambiguation(unittest.TestCase):
    def check(self, html, url, words):
        for screen in (None, MX, NB):
            t = text_of(html, url, screen)
            for w in words:
                self.assertIn(w, t, screen)

    def test_made_up(self):
        html = made_up_disambiguation()
        url = "https://en.wikipedia.org/wiki/Psion"
        self.check(html, url, ("a DC Comics extraterrestrial species",
                               "a British mobile computer company"))
        out = T.slim(core, html, url, None)
        # the item and its link together, in the list, not in the Menu
        self.assertIn('<a href="https://en.wikipedia.org/wiki/Psion_(company)">Psion (company)</a>'
                      ", a British mobile computer company", out)
        # a footnote (it starts with a link back up the page) is not an item
        self.assertNotIn("a book about it", out)
        # a plain menu of links stays a menu
        self.assertIn('<a name="psi-nav">', out)

    def test_saved(self):
        html, url = saved("wiki-disambig")
        if html is None:
            self.skipTest("no saved page (test/fetch_fixtures.py)")
        self.check(html, url, ("a British mobile computer company",
                               "the J/psi meson subatomic particle"))


@unittest.skipUnless(HAVE_EXTRACTOR, "needs trafilatura or readability")
class TestShortArticle(unittest.TestCase):
    def test_classified_as_article(self):
        html = core._unhide_clean(made_up_short_article(), T.log)
        self.assertFalse(core._classify_index(html, T.log))

    def test_made_up(self):
        t = text_of(made_up_short_article(), "https://en.wikipedia.org/wiki/Psion_netBook")
        self.assertIn("subnotebook made by Psion from 1999", t)

    def test_saved(self):
        html, url = saved("wiki-netbook")
        if html is None:
            self.skipTest("no saved page (test/fetch_fixtures.py)")
        for screen in (None, NB):
            t = text_of(html, url, screen)
            self.assertIn("subnotebook", t, screen)
            self.assertGreater(len(t.split()), 400, screen)


class TestIndexesStayIndexes(unittest.TestCase):
    """The saved index pages are still indexes (headline lists)."""
    def test_saved(self):
        names = [n for n in ("bbc-home", "guardian-tech", "hn", "npr-text", "wiki-table")
                 if saved(n)[0] is not None]
        if not names:
            self.skipTest("no saved pages (test/fetch_fixtures.py)")
        for n in names:
            html, _ = saved(n)
            self.assertTrue(core._classify_index(core._unhide_clean(html, T.log), T.log), n)


if __name__ == "__main__":
    unittest.main(verbosity=2)
