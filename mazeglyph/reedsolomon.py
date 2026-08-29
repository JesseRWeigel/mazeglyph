"""Reed-Solomon over GF(256): making error correction codewords, and spending them.

WHAT THE ERROR CORRECTION IS FOR HERE, WHICH IS NOT WHAT IT IS USUALLY FOR. In an ordinary QR code
the correction codewords exist so that a scratched or partly obscured code still reads. In this
project they are a BUDGET TO SPEND. Carving a maze into a QR code means flipping modules, every
flipped module is a corrupted bit, and the question the whole program turns on is how many can be
flipped before the code stops decoding. Reed-Solomon answers it exactly: a block with `n` error
correction codewords survives `n // 2` corrupted codewords and no more.

TWO CODEWORDS ARE SPENT PER ERROR, and that is the fact that shapes everything downstream. The
decoder is not told where the errors are, so each one costs one codeword to locate and one to
correct. A block with 28 correction codewords tolerates 14 bad codewords. If the standard also
reserves some for misdecode protection, fewer.

A CODEWORD IS EIGHT MODULES, AND THEY ARE NOT ADJACENT ON THE GRID. Flipping one module ruins one
codeword, so eight flips inside one codeword cost the same as one flip. The maze carver exploits
that, and it is the reason the budget is counted in corrupted CODEWORDS rather than in flipped
modules.

ENCODING AND DECODING ARE DELIBERATELY DIFFERENT CODE. Encoding is one polynomial division.
Decoding is syndromes, then Berlekamp-Massey to find the error locator, then Chien search to find
the positions, then Forney to find the magnitudes. They share the field and nothing else, so a
mistake in one does not hide in the other. That is the whole reason the decoder in this project is
worth anything as a check on the encoder.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from . import galois


def generator_polynomial(count: int) -> List[int]:
    """The product of (x - alpha^i) for i below `count`, which is the RS generator.

    Built rather than looked up, so it cannot disagree with the field it is built in.
    """
    poly = [1]
    for index in range(count):
        poly = galois.poly_multiply(poly, [1, galois.alpha(index)])
    return poly


def encode(data: List[int], count: int) -> List[int]:
    """The `count` error correction codewords for a block of data codewords."""
    if count <= 0:
        raise ValueError("a block with no error correction codewords corrects nothing")
    padded = list(data) + [0] * count
    return galois.poly_remainder(padded, generator_polynomial(count))


def syndromes(received: List[int], count: int) -> List[int]:
    """The received polynomial evaluated at each root of the generator.

    All zero means the block is consistent with some codeword, which is the decoder's first and
    cheapest question.
    """
    return [galois.poly_evaluate(received, galois.alpha(index)) for index in range(count)]


def berlekamp_massey(syndrome: List[int]) -> List[int]:
    """The shortest polynomial whose roots are the reciprocals of the error positions.

    This is the part that has no counterpart in the encoder at all, which is what makes the
    decoder an independent opinion rather than the encoder run backwards.
    """
    locator = [1]
    previous = [1]
    shift = 1
    discrepancy_previous = 1
    # THE REGISTER LENGTH IS TRACKED SEPARATELY FROM THE POLYNOMIAL'S LENGTH, and conflating the
    # two was a real bug here. Adding two polynomials can lengthen the list without changing the
    # length of the shift register the algorithm is building, so `len(locator) - 1` is not L. The
    # symptom was precise and easy to miss: at exactly the correction capacity the locator came
    # out one degree too high, the root search found the wrong number of roots, and the block was
    # declared beyond repair. Below capacity there is enough slack that it still worked, so 383 of
    # 400 random trials passed and the 17 that failed were all at the boundary.
    register = 0
    for index, value in enumerate(syndrome):
        discrepancy = value
        for offset in range(1, register + 1):
            if offset < len(locator):
                discrepancy ^= galois.multiply(locator[len(locator) - 1 - offset],
                                               syndrome[index - offset])
        if discrepancy == 0:
            shift += 1
            continue
        scaled = galois.poly_scale(previous, galois.divide(discrepancy, discrepancy_previous))
        scaled = scaled + [0] * shift
        if 2 * register <= index:
            keep = locator
            locator = galois.poly_add(scaled, locator)
            register = index + 1 - register
            previous = keep
            discrepancy_previous = discrepancy
            shift = 1
        else:
            locator = galois.poly_add(scaled, locator)
            shift += 1
    # Leading zeros can accumulate from the additions and would inflate the apparent degree, which
    # the root count is then compared against.
    while len(locator) > 1 and locator[0] == 0:
        locator = locator[1:]
    return locator


def error_positions(locator: List[int], length: int) -> Optional[List[int]]:
    """Chien search: which positions the locator's roots point at, or None if it is inconsistent.

    None rather than a partial answer. A locator whose degree does not match the number of roots
    found describes more errors than it can locate, which means the block is corrupted beyond what
    this code can repair, and returning the roots it did find would produce a confident wrong
    answer.
    """
    degree = len(locator) - 1
    found = []
    for position in range(length):
        if galois.poly_evaluate(locator, galois.alpha(255 - position)) == 0:
            found.append(position)
    if len(found) != degree:
        return None
    return found


def correct(received: List[int], count: int) -> Tuple[Optional[List[int]], int]:
    """(repaired block, how many codewords were wrong), or (None, -1) if it cannot be repaired."""
    block = list(received)
    syndrome = syndromes(block, count)
    if not any(syndrome):
        return block, 0
    locator = berlekamp_massey(syndrome)
    positions = error_positions(locator, len(block))
    if positions is None or not positions:
        return None, -1
    if len(positions) > count // 2:
        # More errors than the block can carry. Repairing anyway would produce a block that
        # satisfies the syndromes and is not the one that was sent.
        return None, -1

    # THE MAGNITUDES ARE SOLVED FOR RATHER THAN COMPUTED BY FORNEY'S ALGORITHM, and the reason
    # is honesty about what this code can be trusted to do. Forney is two lines shorter and has
    # several conventions in circulation that differ by a factor of the error position, so an
    # implementation of it can be wrong in a way that still produces plausible bytes. It was, on
    # the first attempt here: locations were correct and every magnitude was not.
    #
    # With the positions already known, the magnitudes are the solution of a small linear system.
    # An error of size e at position p contributes e * alpha^(i*p) to syndrome i, because
    # `poly_evaluate` reads the block highest degree first, so the codeword at index k carries
    # x^(len - 1 - k) and the root search reports p = len - 1 - k. So:
    #
    #     sum over errors of  e_j * alpha^(i * p_j)  =  S_i        for i = 0 .. count - 1
    #
    # which is a Vandermonde system in the field, solved here by plain Gaussian elimination. For
    # the fifteen or so errors a QR block can carry that is a handful of microseconds, and it is
    # arithmetic a reader can check line by line against the sentence above.
    rows = []
    for index in range(count):
        row = [galois.power(galois.alpha(position), index) for position in positions]
        row.append(syndrome[index])
        rows.append(row)

    width = len(positions)
    pivot_row = 0
    where = []
    for column in range(width):
        found = None
        for candidate in range(pivot_row, len(rows)):
            if rows[candidate][column] != 0:
                found = candidate
                break
        if found is None:
            return None, -1
        rows[pivot_row], rows[found] = rows[found], rows[pivot_row]
        factor = galois.inverse(rows[pivot_row][column])
        rows[pivot_row] = [galois.multiply(value, factor) for value in rows[pivot_row]]
        for other in range(len(rows)):
            if other == pivot_row or rows[other][column] == 0:
                continue
            scale = rows[other][column]
            rows[other] = [a ^ galois.multiply(b, scale)
                           for a, b in zip(rows[other], rows[pivot_row])]
        where.append(pivot_row)
        pivot_row += 1

    magnitudes = [rows[where[index]][width] for index in range(width)]
    # Every remaining row must now be all zero. A non-zero one means the syndromes cannot be
    # explained by errors at these positions at all, so the block is beyond repair rather than
    # repaired approximately.
    for index in range(pivot_row, len(rows)):
        if any(rows[index]):
            return None, -1

    for position, magnitude in zip(positions, magnitudes):
        if magnitude == 0:
            # A located error of size zero is not an error, so the locator was wrong about it.
            return None, -1
        block[len(block) - 1 - position] ^= magnitude

    if any(syndromes(block, count)):
        # The repair did not produce a consistent block, so it was not a repair.
        return None, -1
    return block, len(positions)


def capacity(count: int) -> int:
    """How many corrupted codewords a block with `count` correction codewords survives.

    Two per error, because the decoder is not told where they are: one codeword to locate each
    error and one to correct it.
    """
    return count // 2
