"""Annotate's flowcharts render exactly as they did before they became shared tools.

golden.json.gz holds every render annotate's suite made on 2026-10-06, captured before the
move: the function, its arguments and its output. Each flowchart must come out byte for byte the
same. Its sequence records are the old grid's, which is gone; annotate's test_vz_blocks still
draws their specs.
"""
import gzip
import json
from pathlib import Path

import pytest

from skills._shared.visuals import flowchart

FUNCS = {"flowchart.render": flowchart.render, "flowchart.render_variants": flowchart.render_variants}
RECORDS = [r for r in json.loads(gzip.decompress((Path(__file__).with_name("golden.json.gz")).read_bytes()))
           if r["fn"] in FUNCS]


@pytest.mark.parametrize("rec", RECORDS, ids=[f"{r['fn']}-{i}" for i, r in enumerate(RECORDS)])
def test_annotate_renders_what_it_rendered_before(rec):
    out = FUNCS[rec["fn"]](*rec["args"], **rec["kwargs"])
    assert json.loads(json.dumps(out)) == rec["out"]
