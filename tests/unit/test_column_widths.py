"""Column widths shared by one header and the section tables under it."""

from __future__ import annotations

from tsm.ui.components._column_widths import CONTENTS, STRETCH, column_widths


def test_fixed_and_content_columns_keep_their_width_and_stretch_takes_the_rest():
    # Region/Realm (stretch), AuctionDB (120), Last Updated (contents), delete (22)
    widths = column_widths([STRETCH, 120, CONTENTS, 22], [0, 0, 90, 0], total=600, minimum=16)
    assert widths == [368, 120, 90, 22]
    assert sum(widths) == 600


def test_stretch_never_drops_below_the_minimum():
    widths = column_widths([STRETCH, 300, 300], [0, 0, 0], total=400, minimum=16)
    assert widths == [16, 300, 300]


def test_several_stretch_columns_share_the_rest_without_losing_pixels():
    widths = column_widths([STRETCH, STRETCH, 100], [0, 0, 0], total=301, minimum=16)
    assert widths == [101, 100, 100]


def test_content_column_never_drops_below_the_minimum():
    assert column_widths([CONTENTS, STRETCH], [3, 0], total=100, minimum=16) == [16, 84]
