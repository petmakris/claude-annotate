"""A map or a lane sequence in a /slides deck: every part with a step is a frag the deck reveals."""
import re

from skills._shared.visuals import player
from skills._shared.visuals.tests.test_vz import MAP, SEQ


def frags(svg):
    return [int(n) for n in re.findall(r'data-frag="(\d+)"', svg)]


def test_a_built_map_is_a_frag_per_part_with_its_build_step():
    svg = player.deck_svg(MAP, "d1", "build")
    assert sorted(set(frags(svg))) == [1, 2, 3]
    for tag in re.findall(r"<[^>]*data-frag=[^>]*>", svg):
        assert re.search(r'class="[^"]*\bfrag\b', tag)
        assert re.search(r'data-b="(\d+)"', tag).group(1) == re.search(r'data-frag="(\d+)"', tag).group(1)


def test_a_routed_map_steps_by_route_and_shows_its_route_arrows():
    svg = player.deck_svg(MAP, "d1", "route")
    assert svg.startswith('<svg class="vz mode-route"')
    assert sorted(set(frags(svg))) == [1, 2, 3, 4]


def test_a_lane_sequence_steps_by_its_numbers_in_either_mode():
    assert sorted(set(frags(player.deck_svg(SEQ, "d2", "build")))) == [1, 2]


def test_the_slide_states_the_claim_so_the_drawing_drops_its_title():
    plain = player.deck_svg(MAP, "d1")
    titled = player.deck_svg(MAP, "d1", title=True)
    assert 'class="ttl"' not in plain and 'class="ttl"' in titled
    top = lambda s: float(re.search(r'viewBox="0 ([\d.]+)', s).group(1))
    assert top(plain) > 0 and top(titled) == 0
