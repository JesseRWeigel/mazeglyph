"""The symbol as a single self-contained SVG, suitable for a laser cutter or a browser.

NO EXTERNAL ANYTHING. No fonts, no scripts, no stylesheet, no images. A file that needs the network
to render is a file that stops rendering, and this one is meant to be printed, cut, or opened in
ten years.

TWO WAYS OF DRAWING THE SAME THING, and which one you want depends on what you are doing with it.
The plain rendering is what a scanner sees: dark modules filled, light modules not. The annotated
rendering adds the solution path, the entrance and the exit, and marks the modules that were
carved, which is for a person checking the work rather than for a scanner. The annotated one is
NOT scannable and says so in its own title, because a coloured overlay on a QR code is exactly the
kind of thing somebody would try to scan and then wonder about.
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

QUIET_ZONE = 4


def render(modules, scale: int = 8, quiet: int = QUIET_ZONE, path=None, flipped=None,
           entrance=None, exit_at=None, annotate: bool = False, title: str = "") -> str:
    """One SVG. With `annotate`, the solution and the carving are drawn over it in colour."""
    width = len(modules)
    span = (width + quiet * 2) * scale
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{span}" height="{span}" '
           f'viewBox="0 0 {span} {span}" shape-rendering="crispEdges">']
    if annotate:
        # THE WARNING IS NOT THE CALLER'S TO REMEMBER. An annotated symbol has a red line and
        # coloured squares drawn over it, which is exactly the sort of image somebody points a
        # phone at, and it will not scan. The first version of this put the warning in a title the
        # caller passed in, so a caller that forgot produced a file that looked authoritative and
        # was not. It is emitted here whenever the overlay is, and the title the caller gave
        # follows it.
        out.append("<title>NOT SCANNABLE: the solution and the carving are drawn over this "
                   "symbol. Use the plain rendering to scan it.</title>")
        out.append("<desc>NOT SCANNABLE. This is the diagnostic rendering.</desc>")
    if title:
        out.append(f"<title>{title}</title>" if not annotate else f"<desc>{title}</desc>")
    # The quiet zone is part of the symbol, not padding. A QR code printed hard against another
    # mark is one a scanner will not find, and four modules is what the standard requires.
    out.append(f'<rect width="{span}" height="{span}" fill="#ffffff"/>')

    dark = []
    for row in range(width):
        for column in range(width):
            if modules[row][column]:
                x = (column + quiet) * scale
                y = (row + quiet) * scale
                dark.append(f"M{x} {y}h{scale}v{scale}h-{scale}z")
    # One path element rather than thousands of rects. A version 10 symbol is 3,249 modules and a
    # rect each makes a file no editor enjoys.
    out.append(f'<path fill="#000000" d="{"".join(dark)}"/>')

    if annotate:
        if flipped:
            marks = []
            for row, column in flipped:
                x = (column + quiet) * scale
                y = (row + quiet) * scale
                marks.append(f"M{x} {y}h{scale}v{scale}h-{scale}z")
            out.append(f'<path fill="#d8e8ff" d="{"".join(marks)}"/>')
        if path:
            points = " ".join(f"{(c + quiet) * scale + scale / 2},{(r + quiet) * scale + scale / 2}"
                              for r, c in path)
            out.append(f'<polyline points="{points}" fill="none" stroke="#c02020" '
                       f'stroke-width="{max(1, scale // 3)}" stroke-linejoin="round" '
                       f'stroke-linecap="round"/>')
        for cell, colour in ((entrance, "#20a020"), (exit_at, "#c02020")):
            if cell is None:
                continue
            cx = (cell[1] + quiet) * scale + scale / 2
            cy = (cell[0] + quiet) * scale + scale / 2
            out.append(f'<circle cx="{cx}" cy="{cy}" r="{scale * 0.6}" fill="none" '
                       f'stroke="{colour}" stroke-width="{max(1, scale // 4)}"/>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


def as_text(modules, path=None) -> str:
    """The symbol as characters, for reading in a terminal and for pasting into a test.

    Two characters per module, because a terminal cell is about half as wide as it is tall and a
    symbol drawn one character per module comes out squashed to half its height and unreadable.
    """
    on_path = set(path or ())
    rows = []
    for row_index, row in enumerate(modules):
        line = []
        for column_index, value in enumerate(row):
            if (row_index, column_index) in on_path:
                line.append("··")
            else:
                line.append("██" if value else "  ")
        rows.append("".join(line))
    return "\n".join(rows) + "\n"
