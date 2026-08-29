"""Reading a QR symbol back, written as the inverse of the standard rather than of the encoder.

WHY THIS FILE EXISTS. There is no QR scanner on the machine this was built on and no third party
decoder available to it, so "the maze still scans" cannot be checked by scanning. What can be
checked is that a decoder written from the standard, doing the inverse operations, recovers the
payload from a symbol the encoder produced and from a symbol that has been carved into. That is
weaker than a scanner and it is not nothing, and the README says exactly which of the two it is.

WHAT MAKES IT A SECOND OPINION RATHER THAN THE ENCODER RUN BACKWARDS.

  The encoder's error correction is one polynomial division. This one's is syndromes, Berlekamp
  Massey, a root search and a solved linear system, which share no code with it.

  The encoder writes the format bits from a five bit value through a BCH encoder. This one reads
  fifteen possibly damaged bits and finds the nearest of the thirty two valid words by Hamming
  distance, which is a search rather than an encoding.

  The encoder is told which mask to use. This one reads the mask out of the format information and
  has no idea what the encoder chose.

  The de-interleaving here is written from the standard's description of the weave, not from the
  encoder's `interleave`. The encoder has its own inverse for checking its own work, and the two
  are never called from the same place.

WHAT IT DOES NOT DO. It is given a clean grid of booleans. Finding a symbol in a photograph,
correcting perspective, deciding where the module boundaries are and thresholding grey into black
and white are the hard parts of a real scanner, and none of them is here.
"""

from __future__ import annotations

import dataclasses
from typing import List, Optional, Sequence, Tuple

from . import blocks as blocks_mod, encode, geometry, reedsolomon

FORMAT_MASK = 0b101010000010010
BITS_LEVEL = {0b01: "L", 0b00: "M", 0b11: "Q", 0b10: "H"}


@dataclasses.dataclass
class Reading:
    """What a symbol turned out to say, and what it cost to read it."""

    ok: bool
    payload: Optional[bytes] = None
    version: int = 0
    level: str = ""
    mask: int = -1
    format_bit_errors: int = -1
    corrected_codewords: int = 0
    blocks_repaired: int = 0
    blocks_beyond_repair: int = 0
    problem: str = ""

    def as_dict(self) -> dict:
        return {"ok": self.ok,
                "payload": self.payload.decode("utf-8", "replace") if self.payload else None,
                "version": self.version, "level": self.level, "mask": self.mask,
                "format_bit_errors": self.format_bit_errors,
                "corrected_codewords": self.corrected_codewords,
                "blocks_repaired": self.blocks_repaired,
                "blocks_beyond_repair": self.blocks_beyond_repair,
                "problem": self.problem}


def _valid_format_words():
    """The thirty two format words, generated so they cannot disagree with the encoder's BCH."""
    return {encode.bch_format((level << 3) | mask): (level, mask)
            for level in range(4) for mask in range(8)}


def read_format(modules) -> Tuple[Optional[Tuple[str, int]], int]:
    """(level, mask) and how many bits had to be corrected, or (None, -1).

    BY SEARCH, NOT BY DECODING. Fifteen bits arrive possibly damaged and the answer is whichever of
    the thirty two valid words is closest. The code has a minimum distance of seven, so up to three
    bit errors are unambiguous and four could land exactly between two words. Four or more is
    refused rather than resolved by preferring the lower numbered one.

    BOTH COPIES ARE TRIED and the better reading wins. That is the whole reason the standard writes
    the format twice.
    """
    width = len(modules)
    first = []
    for index in range(15):
        if index < 6:
            first.append(modules[8][index])
        elif index == 6:
            first.append(modules[8][7])
        elif index == 7:
            first.append(modules[8][8])
        elif index == 8:
            first.append(modules[7][8])
        else:
            first.append(modules[14 - index][8])
    second = []
    for index in range(15):
        # Seven up the left edge and eight along the top right. See the note in `encode.py`: this
        # read eight and seven, matching an encoder that wrote eight and seven, and the two agreed
        # with each other while both disagreed with the standard.
        if index < 7:
            second.append(modules[width - 1 - index][8])
        else:
            second.append(modules[8][width - 15 + index])

    # EACH COPY IS READ ON ITS OWN AND THEN THE TWO ARE COMBINED, which is not the same as taking
    # the best match over both at once and is the difference between reading a damaged symbol and
    # reading a wrong one.
    #
    # THE REASON IS A PROPERTY OF THE CODE: the thirty two valid format words are a coset, and
    # COMPLEMENTING ANY OF THEM GIVES ANOTHER VALID ONE. All thirty two. So a copy whose every
    # module has been inverted is at distance zero from a perfectly valid word naming a different
    # level and a different mask, and a search that pooled both copies would take that reading over
    # the correct one whenever it happened to be looked at first. That is exactly what happened
    # here on a fixture that inverted one copy.
    #
    # So: read each copy, and when they disagree prefer the closer one. When they disagree at the
    # same distance the symbol genuinely does not say which is right, and that is refused.
    table = _valid_format_words()
    readings = []
    for bits in (first, second):
        value = 0
        for index, bit in enumerate(bits):
            if bit:
                value |= 1 << index
        closest = min(((bin(value ^ word).count("1"), level, mask)
                       for word, (level, mask) in table.items()),
                      key=lambda row: row[:1] + row[1:])
        readings.append(closest)
    readings.sort(key=lambda row: row[0])
    best = readings[0]
    if len(readings) > 1:
        other = readings[1]
        if (best[1], best[2]) != (other[1], other[2]) and best[0] == other[0]:
            return None, best[0]
    if best[0] > 3:
        return None, best[0]
    return (BITS_LEVEL[best[1]], best[2]), best[0]


def read_codewords(modules, version: int, mask: int) -> List[int]:
    """The data modules in zigzag order, unmasked, packed into bytes."""
    rule = encode.MASKS[mask]
    bits = []
    for row, column in geometry.zigzag(version):
        bit = 1 if modules[row][column] else 0
        if rule(row, column):
            bit ^= 1
        bits.append(bit)
    out = []
    for start in range(0, len(bits) - 7, 8):
        value = 0
        for bit in bits[start:start + 8]:
            value = (value << 1) | bit
        out.append(value)
    return out


def unweave(stream: Sequence[int], layout: blocks_mod.Layout) -> List[List[int]]:
    """The interleaved stream back into blocks, from the standard's description of the weave.

    The data codewords come first, one from each block in turn, and a block that is shorter than
    the longest simply has nothing to give on the last pass. Then the error correction codewords,
    the same way, and every block has the same number of those.
    """
    sizes = layout.block_sizes()
    longest = max(sizes)
    data: List[List[int]] = [[] for _ in sizes]
    at = 0
    for round_index in range(longest):
        for block_index, size in enumerate(sizes):
            if round_index < size:
                data[block_index].append(stream[at])
                at += 1
    parity: List[List[int]] = [[] for _ in sizes]
    for _ in range(layout.ec_per_block):
        for block_index in range(len(sizes)):
            parity[block_index].append(stream[at])
            at += 1
    return [d + p for d, p in zip(data, parity)]


def parse_payload(codewords: Sequence[int], version: int) -> Tuple[Optional[bytes], str]:
    """The mode, the length and the bytes, or a reason it is not readable."""
    bits = []
    for value in codewords:
        for shift in range(7, -1, -1):
            bits.append((value >> shift) & 1)

    def take(count):
        nonlocal bits
        if len(bits) < count:
            raise IndexError("the symbol ran out of bits")
        value = 0
        for bit in bits[:count]:
            value = (value << 1) | bit
        bits = bits[count:]
        return value

    try:
        mode = take(4)
        if mode != encode.BYTE_MODE:
            return None, (f"mode {mode:04b} is not byte mode, which is the only one this program "
                          f"writes or reads")
        length = take(encode.character_count_bits(version))
        if length * 8 > len(bits):
            return None, (f"the header says {length} bytes and only {len(bits) // 8} are left in "
                          f"the symbol")
        return bytes(take(8) for _ in range(length)), ""
    except IndexError as error:
        return None, str(error)


def read(modules, version: Optional[int] = None) -> Reading:
    """Everything, from a grid of booleans to the bytes that were encoded."""
    width = len(modules)
    if any(len(row) != width for row in modules):
        return Reading(ok=False, problem="the grid is not square")
    if version is None:
        if (width - 17) % 4 or not 1 <= (width - 17) // 4 <= 40:
            return Reading(ok=False, problem=f"{width} modules is not a QR symbol size")
        version = (width - 17) // 4

    found, distance = read_format(modules)
    if found is None:
        return Reading(ok=False, version=version, format_bit_errors=distance,
                       problem=(f"the format information is {distance} bits from the nearest "
                                f"valid word, which is too far to resolve"))
    level, mask = found
    try:
        layout = blocks_mod.layout(version, level)
    except ValueError as error:
        return Reading(ok=False, version=version, level=level, mask=mask,
                       format_bit_errors=distance, problem=str(error))

    stream = read_codewords(modules, version, mask)
    stream = stream[:layout.total_codewords]
    if len(stream) != layout.total_codewords:
        return Reading(ok=False, version=version, level=level, mask=mask,
                       format_bit_errors=distance,
                       problem=(f"the symbol holds {len(stream)} codewords and version "
                                f"{version} level {level} needs {layout.total_codewords}"))

    repaired = []
    corrected = 0
    beyond = 0
    fixed_blocks = 0
    for block in unweave(stream, layout):
        result, count = reedsolomon.correct(block, layout.ec_per_block)
        if result is None:
            beyond += 1
            repaired.append(None)
            continue
        if count:
            fixed_blocks += 1
            corrected += count
        repaired.append(result)
    if beyond:
        return Reading(ok=False, version=version, level=level, mask=mask,
                       format_bit_errors=distance, corrected_codewords=corrected,
                       blocks_repaired=fixed_blocks, blocks_beyond_repair=beyond,
                       problem=(f"{beyond} of {layout.block_count} blocks carry more errors than "
                                f"their {layout.ec_per_block} correction codewords can repair"))

    # CONCATENATED, NOT RE-INTERLEAVED. The blocks were cut out of one sequential run of data
    # codewords, so putting them back means laying them end to end. Reading them round by round
    # here, the way the weave writes them, gives back the interleaved order and a header that
    # says a length nobody asked for. Every single block layout works either way, which is why
    # twelve of forty version and level combinations passed with this wrong.
    sizes = layout.block_sizes()
    data: List[int] = []
    for block_index, size in enumerate(sizes):
        data.extend(repaired[block_index][:size])
    payload, problem = parse_payload(data, version)
    if payload is None:
        return Reading(ok=False, version=version, level=level, mask=mask,
                       format_bit_errors=distance, corrected_codewords=corrected,
                       blocks_repaired=fixed_blocks, problem=problem)
    return Reading(ok=True, payload=payload, version=version, level=level, mask=mask,
                   format_bit_errors=distance, corrected_codewords=corrected,
                   blocks_repaired=fixed_blocks)
