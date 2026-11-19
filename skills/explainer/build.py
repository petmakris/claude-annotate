#!/usr/bin/env python3
"""Build an explainer: a JSON spec plus its screens -> one self-contained HTML file.

    python3 build.py <folder>/explainer.json

Writes the file the spec's "out" names (relative to the spec), or <slug>.html next to the spec.
Images are embedded as data: URIs. A box is [x, y, width, height] in the image's own pixels;
a box that leaves its image, or a step without a title, stops the build.
The spec format is in SKILL.md.
"""
import base64
import json
import mimetypes
import pathlib
import re
import struct
import sys

HERE = pathlib.Path(__file__).resolve().parent


class SpecError(ValueError):
    pass


def image_size(data):
    """(width, height) of PNG or JPEG bytes."""
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        return struct.unpack('>II', data[16:24])
    if data[:2] == b'\xff\xd8':
        i = 2
        while i < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            m = data[i + 1]
            if m in (0xC0, 0xC1, 0xC2):
                h, w = struct.unpack('>HH', data[i + 5:i + 9])
                return w, h
            i += 2 + struct.unpack('>H', data[i + 2:i + 4])[0]
    raise SpecError('not a PNG or JPEG')


def cropped(data, crop, size, sid):
    """Cut [x, y, width, height] out of the image, so the part that matters is drawn larger.
    Boxes stay in the full image's pixels; the caller moves them by the returned offset."""
    import io
    if len(crop) != 4:
        raise SpecError(f'{sid}: crop is [x, y, width, height], got {crop}')
    x, y, cw, ch = crop
    if cw <= 0 or ch <= 0 or x < 0 or y < 0 or x + cw > size[0] or y + ch > size[1]:
        raise SpecError(f'{sid}: crop {crop} leaves the {size[0]}x{size[1]} image')
    try:
        from PIL import Image
    except ImportError:
        raise SpecError(f'{sid}: crop needs Pillow; run the build with uv run --with pillow python build.py')
    im = Image.open(io.BytesIO(data)).crop((x, y, x + cw, y + ch))
    buf = io.BytesIO()
    im.save(buf, 'PNG', optimize=True)
    return buf.getvalue(), 'image/png', (cw, ch), (x, y)


def slug(text):
    return re.sub(r'[^A-Za-z0-9]+', '-', text).strip('-') or 'explainer'


def normalize(spec, base):
    """Check the spec and give every screen what the viewer reads: src/w/h or html, and steps with boxes."""
    spec = dict(spec)
    # feature-walkthrough specs name the ticket instead of a tag and a link
    spec.setdefault('tag', spec.get('ticket', ''))
    spec.setdefault('link', spec.get('ticket_url', ''))
    if not spec.get('title'):
        raise SpecError('the spec has no title')
    screens = spec.get('screens') or []
    if not screens:
        raise SpecError('the spec has no screens')
    seen = set()
    out = []
    for n, s in enumerate(screens, 1):
        s = dict(s)
        sid = s.get('id') or f'screen-{n}'
        if sid in seen:
            raise SpecError(f'two screens are called {sid}')
        seen.add(sid)
        s['id'] = sid
        if s.get('phase') not in (None, 'today', 'design'):
            raise SpecError(f"{sid}: phase is today or design, not {s['phase']!r}")
        if s.get('image'):
            p = base / s['image']
            if not p.is_file():
                raise SpecError(f'{sid}: no image at {p}')
            data = p.read_bytes()
            try:
                w, h = image_size(data)
            except SpecError as e:
                raise SpecError(f'{sid}: {p.name} is {e}')
            mime = mimetypes.guess_type(p.name)[0] or 'image/png'
            crop = s.pop('crop', None)
            if crop:
                data, mime, (w, h), off = cropped(data, crop, (w, h), sid)
            else:
                off = (0, 0)
            s.update(w=w, h=h, src=f'data:{mime};base64,' + base64.b64encode(data).decode())
        elif s.get('html') or s.get('html_file'):
            if s.get('html_file'):
                s['html'] = (base / s.pop('html_file')).read_text()
        else:
            raise SpecError(f'{sid}: a screen needs an image or html')
        steps = s.get('steps') or []
        if not steps:
            raise SpecError(f'{sid}: a screen needs at least one step')
        fixed = []
        for k, st in enumerate(steps, 1):
            st = dict(st)
            where = f'{sid} step {k}'
            if not st.get('title'):
                raise SpecError(f'{where}: no title')
            boxes = st.pop('boxes', None) or ([st.pop('box')] if st.get('box') else [])
            st.pop('box', None)
            if boxes and not s.get('src'):
                raise SpecError(f'{where}: boxes belong to an image screen; an html screen uses focus')
            if st.get('focus') and s.get('src'):
                raise SpecError(f'{where}: focus belongs to an html screen; an image screen uses box')
            if boxes and s.get('src'):
                for b in boxes:
                    if len(b) == 4:
                        b[0] -= off[0]
                        b[1] -= off[1]
            for b in boxes:
                if len(b) != 4 or any(not isinstance(v, (int, float)) for v in b):
                    raise SpecError(f'{where}: a box is [x, y, width, height], got {b}')
                x, y, bw, bh = b
                if bw <= 0 or bh <= 0 or x < 0 or y < 0 or x + bw > s['w'] or y + bh > s['h']:
                    raise SpecError(f"{where}: box {b} leaves the {s['w']}x{s['h']} image")
            st['boxes'] = boxes
            fixed.append(st)
        s['steps'] = fixed
        s.pop('image', None)
        out.append(s)
    spec['screens'] = out
    return spec


def render(spec, extra_css=''):
    data = json.dumps(spec, ensure_ascii=False).replace('</', '<\\/')
    title = ' · '.join(x for x in (spec.get('tag'), spec['title']) if x)
    html = (HERE / 'template.html').read_text()
    esc = title.replace('&', '&amp;').replace('<', '&lt;')
    css = f'<style>\n{extra_css}\n</style>' if extra_css else ''
    return html.replace('__TITLE__', esc).replace('__EXTRA_CSS__', css).replace('__SPEC__', data)


def build(spec_path):
    spec_path = pathlib.Path(spec_path).resolve()
    base = spec_path.parent
    raw = json.loads(spec_path.read_text())
    spec = normalize(raw, base)
    extra = (base / raw['css']).read_text() if raw.get('css') else ''
    name = raw.get('out') or f"{slug(raw.get('ticket') or raw['title'])}.html"
    out = (base / name).resolve()
    out.write_text(render(spec, extra))
    steps = sum(len(s['steps']) for s in spec['screens'])
    return out, len(spec['screens']), steps


def main(argv):
    if len(argv) != 2:
        sys.exit(__doc__)
    try:
        out, screens, steps = build(argv[1])
    except SpecError as e:
        sys.exit(f'explainer: {e}')
    print(f'{out}  {screens} screens, {steps} parts, {out.stat().st_size // 1024} KB')


if __name__ == '__main__':
    main(sys.argv)
