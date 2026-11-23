import re
import unittest

from skills._shared.visuals import map_svg
from skills.app_map import convert

SPEC = {
    "title": "Orders flow through the service", "subtitle": "a made-up shop",
    "columns": ["Who asks", "Core"],
    "row_labels": ["Main", "Extra"],
    "boxes": [
        {"id": "a", "col": 0, "row": 0, "tone": "blue", "name": "Alpha",
         "lines": ["calls `OrderService` often", {"text": "risky", "tone": "red", "gap": True},
                   {"text": "ok", "tone": "green"}, {"text": "warn", "tone": "amber"}],
         "children": [{"id": "c", "name": "Child", "tone": "green", "lines": ["kid"]}]},
        {"id": "b", "col": 1, "row": 0, "tone": "amber", "name": "Beta"},
        {"id": "d", "col": 1, "row": 1, "tone": "red", "name": "Del", "mono": True},
        {"id": "e", "col": 0, "row": 1, "name": "Eve"},
    ],
    "zones": [{"label": "zone one", "tone": "red", "boxes": ["b", "d"]}],
    "arrows": [
        {"from": "a", "to": "b", "label": "calls", "n": 1},
        {"from": "a", "to": "d", "tone": "amber", "dash": True},
        {"from": "e", "to": "d", "tone": "blue", "label": "a long label to place", "n": 2},
    ],
    "legend": [{"label": "calls"}, {"tone": "blue", "dash": True, "label": "ai"}, {"kind": "box", "tone": "green", "label": "ok"}],
}


def count_drawn(svg):
    body = re.sub(r"<defs>.*?</defs>", "", svg, flags=re.S)
    return len(re.findall(r"<(?:rect|path|line|circle|text)\b", body))


class Convert(unittest.TestCase):
    def setUp(self):
        self.svg = map_svg.render(SPEC, "m", keyed=True)
        self.d = convert.svg_to_drawing(self.svg)
        self.shapes = self.d["shapes"]

    def of(self, kind, **kw):
        return [s for s in self.shapes if s["kind"] == kind and all(s.get(k) == v for k, v in kw.items())]

    def test_every_drawn_element_survives(self):
        self.assertEqual(len(self.shapes), count_drawn(self.svg))

    def test_size_comes_from_the_view_box(self):
        m = re.search(r'viewBox="0 0 (\d+) (\d+)"', self.svg)
        self.assertEqual((self.d["width"], self.d["height"]), (int(m[1]), int(m[2])))

    def test_only_known_kinds_and_fields(self):
        fields = {
            "rect": {"kind", "x", "y", "w", "h", "r", "role", "tone", "dashed", "key"},
            "path": {"kind", "points", "role", "tone", "dashed", "arrow", "key"},
            "circle": {"kind", "x", "y", "r", "role", "tone", "dashed", "key"},
            "text": {"kind", "x", "y", "anchor", "role", "size", "weight", "tone", "key", "runs"},
        }
        for s in self.shapes:
            self.assertEqual(set(s), fields[s["kind"]], s)

    def test_boxes_are_keyed_rects(self):
        for bid in "abcde":
            r = self.of("rect", key=f"box:{bid}")
            self.assertEqual(len(r), 1, bid)
            self.assertEqual(r[0]["role"], "box")
        self.assertEqual(self.of("rect", key="box:a")[0]["tone"], "blue")
        self.assertEqual(self.of("rect", key="box:c")[0]["tone"], "green")
        self.assertEqual(self.of("rect", key="box:a")[0]["r"], 8)
        self.assertEqual(self.of("rect", key="box:c")[0]["r"], 6)
        zone = self.of("rect", key="zone:0")[0]
        self.assertEqual((zone["role"], zone["tone"], zone["dashed"]), ("zone", "red", True))

    def test_the_legend_box_has_no_key(self):
        legend = [s for s in self.of("rect", role="box") if s["key"] is None]
        self.assertEqual(len(legend), 1)

    def test_text_roles_sizes_and_weights(self):
        title = self.of("text", role="title")[0]
        self.assertEqual((title["size"], title["weight"]), (22, 700))
        self.assertEqual(self.of("text", role="subtitle")[0]["size"], 13)
        cols = self.of("text", role="column")
        self.assertEqual(sorted(c["runs"][0]["text"] for c in cols), ["CORE", "EXTRA", "MAIN", "WHO ASKS"])
        self.assertEqual((cols[0]["size"], cols[0]["weight"]), (12.5, 600))
        names = {s["runs"][0]["text"]: s for s in self.of("text", role="name")}
        self.assertEqual((names["Alpha"]["size"], names["Alpha"]["weight"]), (15.5, 600))
        self.assertEqual(names["Del"]["size"], 14.5)
        self.assertEqual(names["Del"]["runs"], [{"text": "Del", "mono": True}])
        self.assertEqual(self.of("text", role="zone")[0]["runs"][0]["text"], "zone one")
        self.assertEqual(self.of("text", role="badge")[0]["size"], 12.5)

    def test_code_spans_make_mono_runs(self):
        line = [s for s in self.of("text", role="line") if s["key"] == "box:a" and len(s["runs"]) == 3][0]
        self.assertEqual(line["runs"], [{"text": "calls ", "mono": False}, {"text": "OrderService", "mono": True},
                                        {"text": " often", "mono": False}])
        self.assertEqual(line["size"], 13)

    def test_line_tones(self):
        tones = {s["runs"][0]["text"]: s["tone"] for s in self.of("text", role="line") if s["key"] == "box:a"}
        self.assertEqual((tones["risky"], tones["ok"], tones["warn"]), ("red", "green", "amber"))

    def test_arrows(self):
        a = self.of("path", key="edge:a->b#0")[0]
        self.assertTrue(a["arrow"])
        self.assertEqual(a["role"], "arrow")
        self.assertGreaterEqual(len(a["points"]), 2)
        self.assertTrue(all(len(p) == 2 for p in a["points"]))
        dashed = self.of("path", key="edge:a->d#0")[0]
        self.assertEqual((dashed["dashed"], dashed["tone"]), (True, "amber"))

    def test_label_and_badge_carry_the_edge_key(self):
        label = [s for s in self.of("text", role="label") if s["key"] == "edge:a->b#0"]
        self.assertEqual(label[0]["runs"][0]["text"], "calls")
        badge = self.of("circle", key="edge:a->b#0")
        self.assertEqual(len(badge), 1)
        self.assertEqual(badge[0]["role"], "badge")
        self.assertEqual(len(self.of("text", role="badge", key="edge:a->b#0")), 1)

    def test_legend_arrows_are_paths_with_a_legend_role(self):
        leg = self.of("path", role="legend")
        self.assertEqual(len(leg), 2)
        self.assertTrue(all(s["arrow"] and s["key"] is None for s in leg))
        self.assertTrue(any(s["dashed"] and s["tone"] == "blue" for s in leg))

    def test_a_leader_line_is_a_leader_path(self):
        svg = ('<svg viewBox="0 0 100 50"><line class="lk" x1="1" y1="2" x2="30" y2="40" data-key="edge:a->b#0"/></svg>')
        s = convert.svg_to_drawing(svg)["shapes"][0]
        self.assertEqual((s["kind"], s["role"], s["points"], s["arrow"], s["key"]),
                         ("path", "leader", [[1, 2], [30, 40]], False, "edge:a->b#0"))

    def test_entities_in_a_key_are_decoded(self):
        self.assertIn("edge:a->b#0", [s["key"] for s in self.shapes])


class Refusals(unittest.TestCase):
    def test_an_ellipse_fails_naming_it(self):
        with self.assertRaisesRegex(ValueError, "ellipse"):
            convert.svg_to_drawing('<svg viewBox="0 0 10 10"><ellipse cx="1" cy="1" rx="2" ry="2"/></svg>')

    def test_an_unknown_class_fails_naming_it(self):
        with self.assertRaisesRegex(ValueError, "wobble"):
            convert.svg_to_drawing('<svg viewBox="0 0 10 10"><rect class="bx wobble" x="1" y="1" width="2" height="2" rx="1"/></svg>')

    def test_an_unknown_text_class_fails(self):
        with self.assertRaisesRegex(ValueError, "zzz"):
            convert.svg_to_drawing('<svg viewBox="0 0 10 10"><text class="zzz" x="1" y="1">a</text></svg>')

    def test_a_path_with_a_curve_fails(self):
        with self.assertRaisesRegex(ValueError, "C"):
            convert.svg_to_drawing('<svg viewBox="0 0 10 10"><path class="ar" d="M1,1 C2,2 3,3 4,4"/></svg>')
