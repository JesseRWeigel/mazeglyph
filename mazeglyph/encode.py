"""Text to a QR symbol: bits, blocks, interleaving, placement, masking and format information.

BYTE MODE ONLY, and that is a deliberate limit rather than an oversight. The standard has numeric
and alphanumeric modes that pack more into the same space, and a URL is neither: it has lower case
letters, a colon and slashes, none of which the alphanumeric set contains. Implementing modes this
program would never choose would be code nothing exercises.

THE INTERLEAVING IS THE PART THAT MATTERS FOR THE MAZE. Codewords are not written into the symbol
block by block. The first codeword of every block goes first, then the second of every block, and
so on, and the error correction codewords follow in the same weave. So a region of the symbol
carved into a maze damages every block a little rather than one block a lot, which is exactly what
the correction budget can absorb. Without interleaving, carving one corner would exhaust one
block's budget while the others sat unused.

THE MASK IS CHOSEN BY PENALTY AND THE PENALTY RULES ARE THE STANDARD'S. Eight masks are tried and
the one with the lowest score wins. The rules exist to avoid patterns a scanner would mistake for a
finder, and to keep the light and dark counts roughly balanced. They are implemented here rather
than approximated, because a symbol masked with the wrong choice is still a valid symbol and the
difference only shows up as a scanner that sometimes fails, which is the worst kind of bug to have.
"""

from __future__ import annotations

import dataclasses
from typing import List, Optional, Sequence, Tuple

from . import blocks as blocks_mod, geometry, reedsolomon

BYTE_MODE = 0b0100
PAD_BYTES = (0xEC, 0x11)

# The format information is protected by a BCH(15,5) code and then masked with this constant, so
# that an all-zero format does not produce an all-light region a scanner could misread.
FORMAT_MASK = 0b101010000010010
FORMAT_GENERATOR = 0b10100110111
VERSION_GENERATOR = 0b1111100100101

LEVEL_BITS = {"L": 0b01, "M": 0b00, "Q": 0b11, "H": 0b10}
BITS_LEVEL = {value: key for key, value in LEVEL_BITS.items()}


@dataclasses.dataclass
class Symbol:
    version: int
    level: str
    mask: int
    modules: List[List[bool]]
    layout: blocks_mod.Layout

    @property
    def size(self) -> int:
        return len(self.modules)

    def copy(self) -> "Symbol":
        return Symbol(self.version, self.level, self.mask,
                      [row[:] for row in self.modules], self.layout)


def character_count_bits(version: int) -> int:
    """Byte mode: eight bits up to version 9, sixteen from version 10."""
    return 8 if version <= 9 else 16


def to_bits(payload: bytes, version: int, layout: blocks_mod.Layout) -> List[int]:
    """The bit stream before it is cut into codewords."""
    capacity = layout.data_codewords * 8
    count_bits = character_count_bits(version)
    needed = 4 + count_bits + len(payload) * 8
    if needed > capacity:
        raise ValueError(
            f"{len(payload)} bytes needs {needed} bits and version {version} level "
            f"{layout.level} holds {capacity}")
    bits: List[int] = []
    for index in range(3, -1, -1):
        bits.append((BYTE_MODE >> index) & 1)
    for index in range(count_bits - 1, -1, -1):
        bits.append((len(payload) >> index) & 1)
    for byte in payload:
        for index in range(7, -1, -1):
            bits.append((byte >> index) & 1)
    # The terminator is up to four zero bits, and fewer if there is not room, which is the case
    # this is easy to get wrong: a fixed four would overrun a symbol filled exactly to capacity.
    bits.extend([0] * min(4, capacity - len(bits)))
    while len(bits) % 8:
        bits.append(0)
    index = 0
    while len(bits) < capacity:
        byte = PAD_BYTES[index % 2]
        for shift in range(7, -1, -1):
            bits.append((byte >> shift) & 1)
        index += 1
    return bits


def to_codewords(bits: Sequence[int]) -> List[int]:
    out = []
    for start in range(0, len(bits), 8):
        value = 0
        for bit in bits[start:start + 8]:
            value = (value << 1) | bit
        out.append(value)
    return out


def interleave(data: Sequence[int], layout: blocks_mod.Layout) -> List[int]:
    """Data and error correction codewords woven together, which is how they are written."""
    sizes = layout.block_sizes()
    if sum(sizes) != len(data):
        raise ValueError(f"{len(data)} data codewords for blocks summing to {sum(sizes)}")
    groups: List[List[int]] = []
    at = 0
    for size in sizes:
        groups.append(list(data[at:at + size]))
        at += size
    parity = [reedsolomon.encode(group, layout.ec_per_block) for group in groups]

    out: List[int] = []
    for index in range(max(sizes)):
        for group in groups:
            if index < len(group):
                out.append(group[index])
    for index in range(layout.ec_per_block):
        for group in parity:
            out.append(group[index])
    return out


def deinterleave(stream: Sequence[int], layout: blocks_mod.Layout):
    """The inverse weave: back to a list of blocks, each data followed by its parity.

    Written here beside `interleave` on purpose. The decoder has its own, written from the
    standard rather than from this one, and the two agreeing is worth something. This one exists
    so the encoder can check its own work.
    """
    sizes = layout.block_sizes()
    groups: List[List[int]] = [[] for _ in sizes]
    at = 0
    for index in range(max(sizes)):
        for position, size in enumerate(sizes):
            if index < size:
                groups[position].append(stream[at])
                at += 1
    parity: List[List[int]] = [[] for _ in sizes]
    for index in range(layout.ec_per_block):
        for position in range(len(sizes)):
            parity[position].append(stream[at])
            at += 1
    return [group + par for group, par in zip(groups, parity)]


# ------------------------------------------------------------------------------------ the grid

def blank(version: int) -> List[List[Optional[bool]]]:
    width = geometry.size(version)
    return [[None] * width for _ in range(width)]


def draw_function_patterns(grid, version: int) -> None:
    width = geometry.size(version)

    def square(top: int, left: int, span: int, dark: bool):
        for row in range(top, top + span):
            for column in range(left, left + span):
                if 0 <= row < width and 0 <= column < width:
                    grid[row][column] = dark

    for base_row, base_column in ((0, 0), (0, width - 7), (width - 7, 0)):
        square(base_row - 1, base_column - 1, 9, False)      # separator
        square(base_row, base_column, 7, True)
        square(base_row + 1, base_column + 1, 5, False)
        square(base_row + 2, base_column + 2, 3, True)

    for index in range(width):
        if grid[6][index] is None:
            grid[6][index] = index % 2 == 0
        if grid[index][6] is None:
            grid[index][6] = index % 2 == 0

    centres = geometry.alignment_centres(version)
    for row_centre in centres:
        for column_centre in centres:
            near_finder = ((row_centre <= 7 and column_centre <= 7)
                           or (row_centre <= 7 and column_centre >= width - 8)
                           or (row_centre >= width - 8 and column_centre <= 7))
            if near_finder:
                continue
            square(row_centre - 2, column_centre - 2, 5, True)
            square(row_centre - 1, column_centre - 1, 3, False)
            grid[row_centre][column_centre] = True

    grid[width - 8][8] = True                                 # the module that is always dark


def bch_format(bits: int) -> int:
    """The fifteen bit format value: five data bits, ten of BCH, then masked."""
    value = bits << 10
    for shift in range(14, 9, -1):
        if value & (1 << shift):
            value ^= FORMAT_GENERATOR << (shift - 10)
    return ((bits << 10) | value) ^ FORMAT_MASK


def bch_version(version: int) -> int:
    """The eighteen bit version value: six data bits and twelve of BCH."""
    value = version << 12
    for shift in range(17, 11, -1):
        if value & (1 << shift):
            value ^= VERSION_GENERATOR << (shift - 12)
    return (version << 12) | value


def draw_format(grid, version: int, level: str, mask: int) -> None:
    width = geometry.size(version)
    value = bch_format((LEVEL_BITS[level] << 3) | mask)
    for index in range(15):
        bit = (value >> index) & 1
        # The first copy runs down the left of the top-left finder and along the top, stepping
        # over the timing pattern at row and column 6.
        if index < 6:
            grid[8][index] = bool(bit)
        elif index == 6:
            grid[8][7] = bool(bit)
        elif index == 7:
            grid[8][8] = bool(bit)
        elif index == 8:
            grid[7][8] = bool(bit)
        else:
            grid[14 - index][8] = bool(bit)
        # The second copy is split between the other two finders: SEVEN bits up the left edge
        # from the bottom, and eight along the top right. Not eight and seven.
        #
        # This was wrong here and it is the kind of wrong a round trip cannot see. Writing eight
        # bits up the left edge reaches row `width - 8`, which is the module the standard says is
        # ALWAYS DARK, so the encoder overwrote it with a format bit and the decoder read the same
        # displaced positions back and agreed with itself. Every payload round tripped perfectly
        # and no real scanner would have read the symbol, because a scanner checks that module.
        if index < 7:
            grid[width - 1 - index][8] = bool(bit)
        else:
            grid[8][width - 15 + index] = bool(bit)


def draw_version(grid, version: int) -> None:
    if version < 7:
        return
    width = geometry.size(version)
    value = bch_version(version)
    for index in range(18):
        bit = bool((value >> index) & 1)
        row, column = index // 3, index % 3
        grid[row][width - 11 + column] = bit
        grid[width - 11 + column][row] = bit


MASKS = (
    lambda row, column: (row + column) % 2 == 0,
    lambda row, column: row % 2 == 0,
    lambda row, column: column % 3 == 0,
    lambda row, column: (row + column) % 3 == 0,
    lambda row, column: (row // 2 + column // 3) % 2 == 0,
    lambda row, column: (row * column) % 2 + (row * column) % 3 == 0,
    lambda row, column: ((row * column) % 2 + (row * column) % 3) % 2 == 0,
    lambda row, column: ((row + column) % 2 + (row * column) % 3) % 2 == 0,
)


def place_data(grid, version: int, stream: Sequence[int], mask: int) -> None:
    bits: List[int] = []
    for codeword in stream:
        for shift in range(7, -1, -1):
            bits.append((codeword >> shift) & 1)
    positions = geometry.zigzag(version)
    rule = MASKS[mask]
    for index, (row, column) in enumerate(positions):
        bit = bits[index] if index < len(bits) else 0
        if rule(row, column):
            bit ^= 1
        grid[row][column] = bool(bit)


def penalty_parts(grid) -> dict:
    """The standard's four penalty rules, scored separately.

    SEPARATELY, because they interact and a total tells you nothing about any one of them. Testing
    rule three by planting a finder-like run in a blank grid and watching the total move fails: the
    blank grid's rule one score is enormous, planting anything breaks its long runs, and the total
    goes DOWN while rule three goes up. Each rule is returned on its own so a test can ask about
    the one it means.
    """
    width = len(grid)
    lines = list(grid) + [list(column) for column in zip(*grid)]

    # Rule one: runs of five or more of the same colour, in rows and in columns.
    runs = 0
    for line in lines:
        run = 1
        for index in range(1, width):
            if line[index] == line[index - 1]:
                run += 1
            else:
                if run >= 5:
                    runs += 3 + (run - 5)
                run = 1
        if run >= 5:
            runs += 3 + (run - 5)

    # Rule two: every two by two block of one colour.
    squares = 0
    for row in range(width - 1):
        for column in range(width - 1):
            here = grid[row][column]
            if (grid[row][column + 1] == here and grid[row + 1][column] == here
                    and grid[row + 1][column + 1] == here):
                squares += 3

    # Rule three: the finder-like sequence with four light modules on one side, in either
    # direction, in rows and columns. This is the rule that keeps a scanner from finding a finder
    # pattern in the middle of the data.
    pattern = [True, False, True, True, True, False, True]
    light = [False] * 4
    finders = 0
    for line in lines:
        for index in range(width):
            if list(line[index:index + 7]) != pattern:
                continue
            before = list(line[max(0, index - 4):index])
            after = list(line[index + 7:index + 11])
            if before == light or after == light:
                finders += 40

    # Rule four: how far the proportion of dark modules is from a half.
    dark = sum(1 for row in grid for value in row if value)
    percent = dark * 100 // (width * width)
    balance = 10 * (abs(percent - 50) // 5)

    return {"runs": runs, "squares": squares, "finder_like": finders, "balance": balance}


def penalty(grid) -> int:
    return sum(penalty_parts(grid).values())


def build(payload: bytes, version: int, level: str = "H",
          mask: Optional[int] = None) -> Symbol:
    """A complete symbol, with the mask chosen by penalty unless one is given."""
    layout = blocks_mod.layout(version, level)
    bits = to_bits(payload, version, layout)
    data = to_codewords(bits)
    stream = interleave(data, layout)

    best = None
    for candidate in (range(8) if mask is None else [mask]):
        grid = blank(version)
        draw_function_patterns(grid, version)
        draw_version(grid, version)
        draw_format(grid, version, level, candidate)
        place_data(grid, version, stream, candidate)
        filled = [[bool(value) for value in row] for row in grid]
        score = penalty(filled)
        if best is None or score < best[0]:
            best = (score, candidate, filled)
    _, chosen, modules = best
    return Symbol(version=version, level=level, mask=chosen, modules=modules, layout=layout)


def smallest_version(payload: bytes, level: str = "H") -> int:
    for version in blocks_mod.VERSIONS:
        layout = blocks_mod.layout(version, level)
        needed = 4 + character_count_bits(version) + len(payload) * 8
        if needed <= layout.data_codewords * 8:
            return version
    raise ValueError(f"{len(payload)} bytes does not fit in any version this program knows at "
                     f"level {level}")
