import json
import struct
import zlib

import pytest

from skills.spotlight import build as B


def png(w, h):
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xFFFFFFFF)
    raw = b''.join(b'\x00' + b'\xff\xff\xff' * w for _ in range(h))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))


def spec_dir(tmp_path, spec, size=(200, 100)):
    (tmp_path / 'a.png').write_bytes(png(*size))
    p = tmp_path / 'spotlight.json'
    p.write_text(json.dumps(spec))
    return p


def one(steps, **screen):
    return {'title': 'T', 'screens': [dict({'id': 's', 'image': 'a.png', 'steps': steps}, **screen)]}


def page_spec(out):
    t = out.read_text()
    return json.loads(t.split('<script id="spec" type="application/json">')[1].split('</script>')[0].replace('<\\/', '</'))


def test_a_box_inside_the_image_builds_and_the_page_carries_it(tmp_path):
    out, screens, parts = B.build(spec_dir(tmp_path, one([{'title': 'x', 'box': [10, 10, 50, 20]}])))
    assert (screens, parts) == (1, 1)
    s = page_spec(out)['screens'][0]
    assert (s['w'], s['h'], s['steps'][0]['boxes']) == (200, 100, [[10, 10, 50, 20]])
    assert s['src'].startswith('data:image/png;base64,')


def test_a_box_that_leaves_the_image_is_refused(tmp_path):
    with pytest.raises(B.SpecError, match=r'box \[190, 10, 20, 20\] leaves the 200x100 image'):
        B.build(spec_dir(tmp_path, one([{'title': 'x', 'box': [190, 10, 20, 20]}])))


def test_a_step_without_a_title_is_refused(tmp_path):
    with pytest.raises(B.SpecError, match='s step 1: no title'):
        B.build(spec_dir(tmp_path, one([{'text': 'x'}])))


def test_a_box_on_an_html_screen_is_refused(tmp_path):
    spec = {'title': 'T', 'screens': [{'id': 'h', 'html': '<p>x</p>', 'steps': [{'title': 'x', 'box': [0, 0, 1, 1]}]}]}
    with pytest.raises(B.SpecError, match='an html screen uses focus'):
        B.build(spec_dir(tmp_path, spec))


def test_a_focus_on_an_image_screen_is_refused(tmp_path):
    with pytest.raises(B.SpecError, match='an image screen uses box'):
        B.build(spec_dir(tmp_path, one([{'title': 'x', 'focus': 'p'}])))


def test_a_crop_moves_the_boxes_into_the_cut(tmp_path):
    pytest.importorskip('PIL')
    out, _, _ = B.build(spec_dir(tmp_path, one([{'title': 'x', 'box': [60, 30, 20, 10]}], crop=[50, 20, 100, 60])))
    s = page_spec(out)['screens'][0]
    assert (s['w'], s['h'], s['steps'][0]['boxes']) == (100, 60, [[10, 10, 20, 10]])


def test_a_box_outside_the_crop_is_refused(tmp_path):
    pytest.importorskip('PIL')
    with pytest.raises(B.SpecError, match=r'leaves the 100x60 image'):
        B.build(spec_dir(tmp_path, one([{'title': 'x', 'box': [10, 30, 20, 10]}], crop=[50, 20, 100, 60])))


def test_a_feature_walkthrough_spec_takes_its_ticket_as_tag_link_and_file_name(tmp_path):
    spec = one([{'title': 'x', 'box': [1, 1, 5, 5]}])
    spec.update(ticket='ABC-1', ticket_url='https://example.com/ABC-1')
    out, _, _ = B.build(spec_dir(tmp_path, spec))
    assert out.name == 'ABC-1.html'
    got = page_spec(out)
    assert (got['tag'], got['link']) == ('ABC-1', 'https://example.com/ABC-1')
    assert '<title>ABC-1 · T</title>' in out.read_text()


def test_text_holding_a_closing_script_tag_cannot_end_the_spec(tmp_path):
    out, _, _ = B.build(spec_dir(tmp_path, one([{'title': 'x</script><b>', 'box': [1, 1, 5, 5]}])))
    assert out.read_text().count('</script>') == 3  # the spec, the shared spotlight and the viewer
    assert page_spec(out)['screens'][0]['steps'][0]['title'] == 'x</script><b>'


def test_the_slides_theme_spotlight_css_is_embedded(tmp_path, monkeypatch):
    theme = tmp_path / 'cfg' / 'slides' / 'themes' / 'brand'
    theme.mkdir(parents=True)
    (theme / 'spotlight.css').write_text(':root{--accent:#6A4DFC}')
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'cfg'))
    p = spec_dir(tmp_path, dict(one([{'title': 'x'}]), theme='brand', out='o.html'))
    out, _, _ = B.build(p)
    assert ':root{--accent:#6A4DFC}' in out.read_text()


def test_a_spec_naming_no_theme_ignores_the_slides_config_theme(tmp_path, monkeypatch):
    cfg = tmp_path / 'cfg' / 'slides'
    (cfg / 'themes' / 'brand').mkdir(parents=True)
    (cfg / 'themes' / 'brand' / 'spotlight.css').write_text(':root{--accent:#6A4DFC}')
    (cfg / 'config.json').write_text('{"theme": "brand"}')
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'cfg'))
    p = spec_dir(tmp_path, dict(one([{'title': 'x'}]), out='o.html'))
    out, _, _ = B.build(p)
    assert '--accent:#6A4DFC' not in out.read_text()


def test_no_theme_file_leaves_the_page_unthemed(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'none'))
    p = spec_dir(tmp_path, dict(one([{'title': 'x'}]), out='o.html'))
    out, _, _ = B.build(p)
    assert '--accent:#6A4DFC' not in out.read_text()
