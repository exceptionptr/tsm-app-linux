"""Column width arithmetic for SharedTableHeader. No Qt, so it tests headless."""

from __future__ import annotations

# Column specs: a positive int is a fixed width in pixels.
STRETCH = -1  # takes what the other columns leave
CONTENTS = -2  # as wide as the widest content across all tables


def column_widths(
    specs: list[int], content_widths: list[int], total: int, minimum: int
) -> list[int]:
    """Width of every column, given the widest content of each and the total width."""
    widths = []
    for spec, content in zip(specs, content_widths, strict=True):
        if spec == STRETCH:
            widths.append(0)
        elif spec == CONTENTS:
            widths.append(max(minimum, content))
        else:
            widths.append(spec)

    stretch = [i for i, spec in enumerate(specs) if spec == STRETCH]
    if stretch:
        free = total - sum(widths)
        share, extra = divmod(max(0, free), len(stretch))
        for n, i in enumerate(stretch):
            # The pixels a division leaves over go to the first stretch columns,
            # so the columns add up to the total exactly.
            widths[i] = max(minimum, share + (1 if n < extra else 0))
    return widths
