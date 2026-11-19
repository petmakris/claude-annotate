#!/usr/bin/env python3
"""Check a built spotlight in a real browser and capture every part as a PNG.

    uv run --with playwright python check.py <spotlight>.html <review-dir>

At 1440x900 and 390x844 it walks every part and reports: the page scrolling sideways, a ring
outside its screen, a part whose focus finds nothing, a missing connector on desktop, and text
running out of the explanation panel. It writes <review-dir>/desktop-NN.png and phone-NN.png,
one per part, for review and for pasting into a page that cannot host the HTML.
Exits 1 when anything is wrong.
"""
import pathlib
import sys

from playwright.sync_api import sync_playwright

PROBE = """() => {
  const fr = [...document.querySelectorAll('.screen')].find(s => !s.hidden).querySelector('.frame').getBoundingClientRect();
  const rings = [...document.querySelectorAll('.screen:not([hidden]) svg.shade rect.ring:not(.halo)')]
    .map(r => r.getBoundingClientRect());
  const out = rings.filter(r => r.left < fr.left - 1 || r.top < fr.top - 1 || r.right > fr.right + 1 || r.bottom > fr.bottom + 1).length;
  const sec = [...document.querySelectorAll('.part')].find(s => !s.hidden);
  const ex = document.getElementById('explain');
  return {
    sideways: document.documentElement.scrollWidth > innerWidth + 1,
    rings: rings.length, ringsOut: out,
    link: (document.getElementById('linkpath').getAttribute('d') || '').length > 0,
    clipped: ex.scrollHeight > ex.clientHeight + 2 && getComputedStyle(document.body).overflow === 'hidden',
    title: sec ? sec.querySelector('h2').textContent : '',
  };
}"""


def wants(html_path):
    """Which parts have a box or a focus, read from the built page's spec."""
    import json
    import re
    t = pathlib.Path(html_path).read_text()
    spec = json.loads(re.search(r'<script id="spec" type="application/json">(.*?)</script>', t, re.S).group(1).replace('<\\/', '</'))
    return [bool(st.get('boxes') or st.get('focus')) for s in spec['screens'] for st in s['steps']]


def main(argv):
    if len(argv) != 3:
        sys.exit(__doc__)
    page_path = pathlib.Path(argv[1]).resolve()
    review = pathlib.Path(argv[2]).resolve()
    review.mkdir(parents=True, exist_ok=True)
    want = wants(page_path)
    faults = []
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        for name, vp in (('desktop', (1440, 900)), ('phone', (390, 844))):
            p = b.new_page(viewport={'width': vp[0], 'height': vp[1]})
            p.goto(page_path.as_uri())
            p.wait_for_function('window.spotlightPage')
            p.wait_for_timeout(400)
            font = p.evaluate("getComputedStyle(document.body).fontFamily")
            if 'Inter' not in font:
                faults.append(f'{name}: body font is {font}')
            n = p.evaluate('window.spotlightPage.count')
            for k in range(n):
                p.evaluate(f'window.spotlightPage.go({k})')
                p.wait_for_timeout(450)
                r = p.evaluate(PROBE)
                tag = f"{name} part {k + 1} ({r['title'][:50]})"
                if r['sideways']:
                    faults.append(f'{tag}: the page scrolls sideways')
                if want[k] and not r['rings']:
                    faults.append(f'{tag}: its box or focus rings nothing')
                if r['ringsOut']:
                    faults.append(f'{tag}: {r["ringsOut"]} ring(s) outside the screen')
                if name == 'desktop' and want[k] and not r['link']:
                    faults.append(f'{tag}: no line joins the text to its part')
                if name == 'desktop' and r['clipped']:
                    faults.append(f'{tag}: the text is taller than its panel')
                p.screenshot(path=str(review / f'{name}-{k + 1:02d}.png'))
            p.close()
        b.close()
    for f in faults:
        print('FAIL', f)
    print(f'{len(want)} parts checked at 1440 and 390 px, {len(faults)} faults, PNGs in {review}')
    sys.exit(1 if faults else 0)


if __name__ == '__main__':
    main(sys.argv)
