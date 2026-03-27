"""WoW-style item tooltip popup widget."""
from __future__ import annotations

import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

_QUALITY_COLORS: dict[str, str] = {
    "q":  "#ffffff",  # uncolored / common
    "q0": "#9d9d9d",  # poor
    "q1": "#ffffff",  # common
    "q2": "#1eff00",  # uncommon
    "q3": "#0070dd",  # rare
    "q4": "#a335ee",  # epic
    "q5": "#ff8000",  # legendary
    "q6": "#e6cc80",  # artifact
    "q9": "#e6cc80",
}

_BORDER_COLORS: dict[int, str] = {
    0: "#9d9d9d",
    1: "#9d9d9d",
    2: "#1eff00",
    3: "#0070dd",
    4: "#a335ee",
    5: "#ff8000",
}


def _wowhead_to_qt(html: str) -> str:
    """Convert Wowhead tooltip HTML to Qt-compatible rich text."""

    # 1. Strip HTML comments (<!--nstart-->, <!--ilvl-->, etc.)
    html = re.sub(r"<!--.*?-->", "", html, flags=re.DOTALL)

    # 2. Money spans → colored text with g / s / c suffix
    def _money(m: re.Match) -> str:
        cls, val = m.group(1), m.group(2).strip()
        if "gold" in cls:
            return f'<span style="color:#f0c040">{val}g</span>'
        if "silver" in cls:
            return f'<span style="color:#c0c0c0">{val}s</span>'
        if "copper" in cls:
            return f'<span style="color:#cd7f32">{val}c</span>'
        return str(val)
    html = re.sub(r'<span\s+class="(money\w+)">([^<]*)</span>', _money, html)

    # 3. Adjacent top-level tables → line break between sections
    html = re.sub(r"</table>\s*<table[^>]*>", "<br>", html, flags=re.IGNORECASE)

    # 4. Inner single-cell tables → line break + content + line break
    #    Loop up to 5 times to unwrap nested tables from the inside out.
    _inner_re = re.compile(
        r"<table[^>]*>\s*<tr[^>]*>\s*<td[^>]*>(.*?)</td>\s*</tr>\s*</table>",
        re.DOTALL | re.IGNORECASE,
    )
    for _ in range(5):
        new = _inner_re.sub(lambda m: f"<br>{m.group(1).strip()}<br>", html)
        if new == html:
            break
        html = new

    # 5. Sell-price div → line break before content
    _sell_div = re.compile(r'<div[^>]*class="[^"]*whtt-sellprice[^"]*"[^>]*>', re.IGNORECASE)
    html = _sell_div.sub("<br>", html)
    html = re.sub(r"</div>", "", html, flags=re.IGNORECASE)

    # 6. Strip <a> link wrappers but keep their text
    html = re.sub(r"<a\b[^>]*>", "", html, flags=re.IGNORECASE)
    html = html.replace("</a>", "")

    # 7. Strip remaining table / tr / td scaffolding
    html = re.sub(r"</?(?:table|tr|td)\b[^>]*>", "", html, flags=re.IGNORECASE)

    # 8. Strip <img> tags
    html = re.sub(r"<img\b[^>]*/?>", "", html, flags=re.IGNORECASE)

    # 9. Quality class attributes → inline color styles
    #    Handles attribute order like <span id="..." class="q2">
    def _colorize(m: re.Match) -> str:
        tag  = m.group(1)
        cls  = re.search(r'class="(q\w*)"', m.group(0))
        color = _QUALITY_COLORS.get(cls.group(1) if cls else "", "#ffffff")
        return f'<{tag} style="color:{color}">'
    html = re.sub(r"<(b|span)\b[^>]*\bclass=\"q\w*\"[^>]*>", _colorize, html, flags=re.IGNORECASE)

    # 10. Strip any remaining known attributes
    html = re.sub(r'\s+class="[^"]*"', "", html)
    html = re.sub(r'\s+id="[^"]*"', "", html)
    html = re.sub(r'\s+href="[^"]*"', "", html)

    # 11. Normalise line breaks: collapse runs, strip leading/trailing
    html = re.sub(r"(?:<br\s*/?>)+", "<br>", html, flags=re.IGNORECASE)
    html = re.sub(r"^(?:<br\s*/?>)+", "", html, flags=re.IGNORECASE)
    html = re.sub(r"(?:<br\s*/?>)+$", "", html, flags=re.IGNORECASE)

    return html.strip()


class WowItemTooltip(QWidget):
    """Frameless WoW-style item tooltip that appears near the cursor."""

    def __init__(self, parent: QWidget | None = None) -> None:
        # ToolTip window type bypasses the WM on X11 so move() is respected.
        super().__init__(
            parent,
            Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        self._border_color = QColor("#9d9d9d")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(0)

        self._label = QLabel()
        self._label.setTextFormat(Qt.TextFormat.RichText)
        self._label.setWordWrap(True)
        self._label.setMaximumWidth(320)
        self._label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._label.setStyleSheet(
            "background: transparent; color: #ffffff; font-size: 12px;"
        )
        layout.addWidget(self._label)

    def paintEvent(self, _event: object) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#0d0d12"))
        painter.setPen(self._border_color)
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
        painter.end()

    def show_for(
        self, tooltip_html: str, quality: int, global_x: int, global_y: int
    ) -> None:
        self._border_color = QColor(_BORDER_COLORS.get(quality, "#9d9d9d"))
        self._label.setText(_wowhead_to_qt(tooltip_html))
        self.adjustSize()

        x = global_x + 14
        y = global_y + 14

        from PySide6.QtCore import QPoint
        screen = QApplication.screenAt(QPoint(global_x, global_y))
        if screen:
            sg = screen.availableGeometry()
            if x + self.width() > sg.right():
                x = global_x - self.width() - 4
            if y + self.height() > sg.bottom():
                y = global_y - self.height() - 4

        # Show first, then move — some WMs override position on first show.
        self.show()
        self.move(x, y)
        self.raise_()
        self.update()
