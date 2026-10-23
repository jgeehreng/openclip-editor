"""Timecode maths, parsing and display helpers."""
import xml.etree.ElementTree as ET

import pytest

from conftest import oce


@pytest.mark.parametrize("rate,drop", [(24, False), (25, False), (30, False),
                                       (30, True), (60, True)])
def test_round_trip(rate, drop):
    for nb in range(0, rate * 3600 * 2, 7):
        assert oce.tc_to_ticks(*oce.ticks_to_tc(nb, rate, drop), rate, drop) == nb


@pytest.mark.parametrize("nb,expected", [
    (1799, (0, 0, 59, 29)),
    (1800, (0, 1, 0, 2)),          # ;00 and ;01 are skipped at minute 1
    (17982, (0, 10, 0, 0)),        # ...but not at minute 10
    (107892, (1, 0, 0, 0)),
])
def test_drop_frame_29_97(nb, expected):
    assert oce.ticks_to_tc(nb, 30, True) == expected


def test_rate_parsing():
    assert oce.tc_rate(ET.fromstring("<t><rate>23.976</rate></t>")) == 24
    assert oce.tc_rate(ET.fromstring("<t><rate>abc</rate></t>")) == 24
    assert oce.tc_rate(ET.fromstring("<t/>")) == 24


def test_separators():
    assert oce.tc_separator(24) == "+"
    assert oce.tc_separator(25) == ":"
    assert oce.tc_separator(30) == ":"
    assert oce.tc_separator(30, True) == ";"
    assert oce.tc_separator(60, True) == ";"
    assert oce.tc_separator(24, True) == "+"      # 24 has no drop-frame variant
    # The XML label keeps Flame's notation regardless of display
    assert oce.tc_to_str(1, 0, 0, 0) == "01:00:00:00"
    assert oce.tc_to_str(1, 0, 0, 0, True) == "01:00:00;00"


@pytest.mark.parametrize("text,expected", [
    ("01:02:03:04", (1, 2, 3, 4)),
    ("01:02:03+04", (1, 2, 3, 4)),
    (" 01;02;03;04 ", (1, 2, 3, 4)),
    ("01.02.03.04", (1, 2, 3, 4)),
    ("1000000", (1, 0, 0, 0)),
    ("abc", None),
    ("123456789", None),
])
def test_parse_tc_text(text, expected):
    assert oce.parse_tc_text(text) == expected


def test_validity():
    assert not oce.tc_is_valid(0, 0, 0, 24, 24)
    assert oce.tc_is_valid(0, 0, 0, 23, 24)
    assert not oce.tc_is_valid(0, 60, 0, 0, 24)
    assert not oce.tc_is_valid(0, 1, 0, 0, 30, True)
    assert not oce.tc_is_valid(0, 1, 0, 1, 30, True)
    assert oce.tc_is_valid(0, 1, 0, 2, 30, True)
    assert oce.tc_is_valid(0, 10, 0, 0, 30, True)
