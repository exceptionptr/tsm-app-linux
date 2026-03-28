"""Tests for wow_tooltip._wowhead_to_qt HTML conversion."""

from __future__ import annotations

from tsm.ui.components._wowhead_html import _wowhead_to_qt


def test_strips_html_comments():
    html = "<!--nstart-->Hello<!--ilvl-->"
    result = _wowhead_to_qt(html)
    assert "<!--" not in result
    assert "Hello" in result


def test_money_gold_class():
    html = '<span class="moneygold">10</span>'
    result = _wowhead_to_qt(html)
    assert "#f0c040" in result
    assert "10g" in result


def test_money_silver_class():
    html = '<span class="moneysilver">5</span>'
    result = _wowhead_to_qt(html)
    assert "#c0c0c0" in result
    assert "5s" in result


def test_money_copper_class():
    html = '<span class="moneycopper">3</span>'
    result = _wowhead_to_qt(html)
    assert "#cd7f32" in result
    assert "3c" in result


def test_strips_img_tags():
    html = 'Hello<img src="icon.png"/>World'
    result = _wowhead_to_qt(html)
    assert "<img" not in result
    assert "Hello" in result
    assert "World" in result


def test_strips_link_wrappers_keeps_text():
    html = '<a href="/item=12345">Sword of Power</a>'
    result = _wowhead_to_qt(html)
    assert "<a" not in result
    assert "Sword of Power" in result


def test_quality_class_colorize():
    html = '<span class="q3">Rare Item</span>'
    result = _wowhead_to_qt(html)
    assert "#0070dd" in result
    assert "Rare Item" in result


def test_quality_class_common():
    html = '<span class="q1">Common Item</span>'
    result = _wowhead_to_qt(html)
    assert "#ffffff" in result


def test_strips_table_structure():
    html = "<table><tr><td>Content</td></tr></table>"
    result = _wowhead_to_qt(html)
    assert "<table" not in result
    assert "<tr" not in result
    assert "<td" not in result
    assert "Content" in result


def test_collapses_consecutive_br():
    html = "A<br><br><br>B"
    result = _wowhead_to_qt(html)
    assert result.count("<br>") == 1


def test_strips_leading_trailing_br():
    html = "<br>Content<br>"
    result = _wowhead_to_qt(html)
    assert not result.startswith("<br>")
    assert not result.endswith("<br>")


def test_strips_class_id_href_attributes():
    html = '<span class="q2" id="item-name" href="/foo">Green</span>'
    result = _wowhead_to_qt(html)
    assert 'class=' not in result
    assert 'id=' not in result
    assert 'href=' not in result


def test_empty_input():
    assert _wowhead_to_qt("") == ""


def test_plain_text_passthrough():
    text = "Item Level 50"
    result = _wowhead_to_qt(text)
    assert "Item Level 50" in result
