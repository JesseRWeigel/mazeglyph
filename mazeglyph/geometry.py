"""Where every module of a QR symbol lives, computed from the version rather than tabulated.

A QR symbol is a grid of modules, and they are not all data. The finder patterns in three corners
tell a scanner where the symbol is and which way up. The timing patterns give it the module pitch.
The alignment patterns let it correct for a symbol photographed at an angle. Two copies of the
format information say which error correction level and mask were used, and from version 7 there
are two copies of a version number as well. Everything left over, read in a particular zigzag, is
the data.

THE ALIGNMENT RULE IS DERIVED, AND IT DOES NOT HOLD FOR EVERY VERSION. The centres follow a rule:
the first is at 6, the last is six modules from the far edge, and the ones between are evenly
spaced with the step rounded up to an even number, counted back from the last. That rule reproduces
the published table exactly for versions 1 to 20 and it DISAGREES at versions 32 and 39, where the
standard's table is not what any single rounding rule produces. Version 32's published centres step
by 26 where the rule gives 28, and version 39's step by 28 where it gives 26.

So the rule is used only where it has been checked. `alignment_centres` refuses above the highest
verified version rather than returning a plausible wrong answer, and `scripts/measure.py` prints
the comparison against the published centres for every version it claims. Shipping a rule that is
wrong for two versions out of forty, and silently, is worse than shipping one that says where it
stops.

THE CAPACITY TABLE IS CHECKED AGAINST THIS GEOMETRY. How many codewords a version holds is a
consequence of how many modules are left after the function patterns, so the two must agree. They
are computed independently here and compared, which is what caught a transcription error in the
block table on the day it was written.
"""

from __future__ import annotations

from typing import List, Set, Tuple

FINDER = 7
QUIET_ZONE = 4

# The highest version whose alignment centres this program has checked against the published table.
# Above this the rule below is known to disagree with the standard for at least two versions, so
# `alignment_centres` refuses rather than guessing.
HIGHEST_VERIFIED_VERSION = 20


def size(version: int) -> int:
    """The width of the symbol in modules. Version 1 is 21 and every version adds four."""
    if not 1 <= version <= 40:
        raise ValueError(f"there is no QR version {version}; they run from 1 to 40")
    return 17 + 4 * version


def alignment_centres(version: int) -> List[int]:
    """The row and column coordinates alignment patterns are centred on.

    THE RULE, WHICH IS WHAT THE PUBLISHED TABLE IS A RENDERING OF. Version 1 has none. Otherwise
    there are `version // 7 + 2` centres; the first is 6, the last is `size - 7`, and the rest are
    evenly spaced between them with the step rounded up to an even number, counted back from the
    last so that the gap next to the first centre is the one that absorbs the remainder.
    """
    if version > HIGHEST_VERIFIED_VERSION:
        raise ValueError(
            f"the alignment rule in this program is checked against the published table only up "
            f"to version {HIGHEST_VERIFIED_VERSION}, and it is known to disagree at versions 32 "
            f"and 39, so version {version} is refused rather than answered wrongly")
    if version == 1:
        return []
    count = version // 7 + 2
    first = 6
    last = size(version) - 7
    if count == 2:
        return [first, last]
    step = (last - first) // (count - 1)
    # Rounded UP to even. The centres must sit on even coordinates so that they land on the light
    # modules of the timing pattern rather than straddling it.
    step = step + (step & 1)
    centres = [last - step * index for index in range(count - 1)]
    centres.append(first)
    return sorted(centres)


def finder_modules(version: int) -> Set[Tuple[int, int]]:
    """The three finder patterns and their separators, as (row, column)."""
    width = size(version)
    out = set()
    for base_row, base_column in ((0, 0), (0, width - FINDER), (width - FINDER, 0)):
        for row in range(-1, FINDER + 1):
            for column in range(-1, FINDER + 1):
                here = (base_row + row, base_column + column)
                if 0 <= here[0] < width and 0 <= here[1] < width:
                    out.add(here)
    return out


def alignment_modules(version: int) -> Set[Tuple[int, int]]:
    """The five by five alignment patterns, skipping the three that would sit on a finder."""
    centres = alignment_centres(version)
    width = size(version)
    out = set()
    for row_centre in centres:
        for column_centre in centres:
            # The three corners already have finder patterns, so no alignment pattern is placed
            # there. Checking the CENTRE against the finder area rather than checking each module
            # is what the standard says and is not the same test.
            near_finder = ((row_centre <= FINDER and column_centre <= FINDER)
                           or (row_centre <= FINDER and column_centre >= width - FINDER - 1)
                           or (row_centre >= width - FINDER - 1 and column_centre <= FINDER))
            if near_finder:
                continue
            for row in range(row_centre - 2, row_centre + 3):
                for column in range(column_centre - 2, column_centre + 3):
                    out.add((row, column))
    return out


def timing_modules(version: int) -> Set[Tuple[int, int]]:
    width = size(version)
    out = set()
    for index in range(width):
        out.add((6, index))
        out.add((index, 6))
    return out


def format_modules(version: int) -> Set[Tuple[int, int]]:
    """The two copies of the fifteen format bits, plus the one module that is always dark."""
    width = size(version)
    out = set()
    for index in range(9):
        out.add((8, index))
        out.add((index, 8))
    for index in range(8):
        out.add((8, width - 1 - index))
        out.add((width - 1 - index, 8))
    # The dark module, which is always set and is not part of the format information even though
    # it sits inside the area reserved for it.
    out.add((width - 8, 8))
    return out


def version_modules(version: int) -> Set[Tuple[int, int]]:
    """The two copies of the eighteen version bits, which exist from version 7 onwards."""
    if version < 7:
        return set()
    width = size(version)
    out = set()
    for index in range(18):
        row, column = index // 3, index % 3
        out.add((row, width - 11 + column))
        out.add((width - 11 + column, row))
    return out


def function_modules(version: int) -> Set[Tuple[int, int]]:
    """Every module that is not data."""
    return (finder_modules(version) | alignment_modules(version) | timing_modules(version)
            | format_modules(version) | version_modules(version))


def data_module_count(version: int) -> int:
    return size(version) ** 2 - len(function_modules(version))


def data_capacity_bits(version: int) -> int:
    """How many bits of data and error correction a version holds.

    The remainder bits are subtracted: some versions leave three or four modules over after the
    last whole codeword, and they are set to light and carry nothing.
    """
    return (data_module_count(version) // 8) * 8


def remainder_bits(version: int) -> int:
    return data_module_count(version) % 8


def zigzag(version: int) -> List[Tuple[int, int]]:
    """Every data module in the order the standard places bits into them.

    Two columns at a time from the right, upwards then downwards alternately, right module before
    left within each pair, skipping the function patterns and skipping column 6 entirely, which is
    the vertical timing pattern.
    """
    width = size(version)
    reserved = function_modules(version)
    out = []
    column = width - 1
    upwards = True
    while column > 0:
        if column == 6:
            # The vertical timing pattern is a whole column, so the pairing steps over it rather
            # than treating it as a normal reserved module. Getting this wrong shifts every
            # subsequent bit by one and is invisible until a decoder is written.
            column -= 1
            continue
        rows = range(width - 1, -1, -1) if upwards else range(width)
        for row in rows:
            for offset in (0, 1):
                here = (row, column - offset)
                if here not in reserved:
                    out.append(here)
        column -= 2
        upwards = not upwards
    return out
