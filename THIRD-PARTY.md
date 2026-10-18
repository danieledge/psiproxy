# Third-party components

Nothing is vendored: PsiProxy is plain Python and installs its packages
from PyPI (`requirements.txt`, `requirements-optional.txt`), each under its
own licence. None is included in this repository.

| Package | Used for | Licence |
|---|---|---|
| [trafilatura](https://github.com/adbar/trafilatura) | article extraction | Apache-2.0 |
| [readability-lxml](https://github.com/buriy/python-readability) | fallback extractor for galleries and listicles | Apache-2.0 |
| [lxml](https://lxml.de/) with `lxml_html_clean` | HTML parsing and the tag allowlist | BSD-3-Clause |
| [Pillow](https://python-pillow.org/) | pictures to 16-grey GIFs | MIT-CMU (HPND) |
| [Textual](https://textual.textualize.io/) | the dashboard (`./psiproxy`) | MIT |
| [Playwright](https://playwright.dev/python/) (optional) | JavaScript rendering in a headless Chromium, which it downloads (BSD and others) | Apache-2.0 |

Everything else here is this project's own code, MIT (`LICENSE`).
