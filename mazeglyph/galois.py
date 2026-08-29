"""Arithmetic in GF(256), which is where Reed-Solomon lives and where QR error correction is done.

WHY A FIELD AT ALL. Reed-Solomon treats a block of bytes as the coefficients of a polynomial and
its error correction as polynomial division. For that to work, the bytes have to be elements of a
field: every non-zero value needs a multiplicative inverse, and ordinary integer arithmetic modulo
256 does not provide one, because 2 has no inverse there. GF(256) is built instead from
polynomials over GF(2) reduced by an irreducible polynomial, and then every non-zero byte has an
inverse and division is total.

THE PRIMITIVE POLYNOMIAL IS PART OF THE STANDARD AND NOT A CHOICE. QR uses x^8 + x^4 + x^3 + x^2 +
1, which is 0x11D. A different irreducible polynomial gives a different field with different
multiplication tables, and a decoder using one cannot read an encoder using the other. It is
written here as a constant with its name on it so that it cannot be mistaken for something
tuneable.

WHY THE TABLES ARE BUILT RATHER THAN WRITTEN DOWN. The exponential and logarithm tables are
generated at import from the primitive element 2, so they cannot disagree with the polynomial
above. A pasted table is a claim about arithmetic that nothing checks; a generated one is the
arithmetic.
"""

from __future__ import annotations

# x^8 + x^4 + x^3 + x^2 + 1. The QR standard's field, not a parameter.
PRIMITIVE = 0x11D

# 2 generates the whole multiplicative group under this polynomial, which is what makes the
# logarithm table possible. `_build` checks it rather than assuming it.
GENERATOR = 2


def _build():
    exp = [0] * 512
    log = [0] * 256
    value = 1
    for power in range(255):
        exp[power] = value
        log[value] = power
        value <<= 1
        if value & 0x100:
            value ^= PRIMITIVE
    if value != 1:
        raise RuntimeError(
            f"{GENERATOR} does not generate the field defined by {PRIMITIVE:#x}: after 255 "
            f"multiplications it reached {value} rather than returning to 1, so the logarithm "
            f"table would be missing values and every multiplication built on it would be wrong")
    # The second half repeats the first, so `exp[a + b]` never needs a modulo. The cost is 256
    # bytes and the saving is a branch in the innermost loop of every polynomial multiply.
    for power in range(255, 512):
        exp[power] = exp[power - 255]
    return exp, log


EXP, LOG = _build()


def add(left: int, right: int) -> int:
    """Addition in a field of characteristic two, which is exclusive or.

    Subtraction is the same operation, which is why there is no `subtract` here. A reader looking
    for one should know that its absence is deliberate rather than an oversight.
    """
    return left ^ right


def multiply(left: int, right: int) -> int:
    if left == 0 or right == 0:
        # Zero has no logarithm, so this cannot go through the tables. Without the guard it would
        # read LOG[0], which is a real entry holding a meaningless value, and the result would be
        # plausible and wrong.
        return 0
    return EXP[LOG[left] + LOG[right]]


def divide(left: int, right: int) -> int:
    if right == 0:
        raise ZeroDivisionError("division by zero in GF(256)")
    if left == 0:
        return 0
    return EXP[(LOG[left] - LOG[right]) % 255]


def inverse(value: int) -> int:
    if value == 0:
        raise ZeroDivisionError("zero has no inverse in GF(256)")
    return EXP[255 - LOG[value]]


def power(base: int, exponent: int) -> int:
    """`base` raised to a possibly negative exponent."""
    if base == 0:
        return 0 if exponent != 0 else 1
    return EXP[(LOG[base] * exponent) % 255]


def alpha(exponent: int) -> int:
    """The generator raised to a power, which is how the standard names field elements."""
    return EXP[exponent % 255]


# ------------------------------------------------------------------------------- polynomials
# Coefficients are HIGHEST DEGREE FIRST throughout this project. That is the order the QR standard
# writes them in and the order the codewords come out in, and mixing the two conventions inside one
# program is the classic way to produce a Reed-Solomon implementation that works on symmetric test
# data and fails on real data.


def poly_multiply(left, right):
    out = [0] * (len(left) + len(right) - 1)
    for i, a in enumerate(left):
        if a == 0:
            continue
        for j, b in enumerate(right):
            out[i + j] ^= multiply(a, b)
    return out


def poly_add(left, right):
    size = max(len(left), len(right))
    out = [0] * size
    for index, value in enumerate(left):
        out[index + size - len(left)] = value
    for index, value in enumerate(right):
        out[index + size - len(right)] ^= value
    return out


def poly_evaluate(poly, at: int) -> int:
    """Horner's rule, which is the cheapest way and also the one with no intermediate powers."""
    result = 0
    for coefficient in poly:
        result = multiply(result, at) ^ coefficient
    return result


def poly_scale(poly, by: int):
    return [multiply(value, by) for value in poly]


def poly_remainder(dividend, divisor):
    """The remainder of polynomial division, which is what Reed-Solomon encoding produces."""
    out = list(dividend)
    steps = len(dividend) - len(divisor) + 1
    for index in range(steps):
        factor = out[index]
        if factor == 0:
            continue
        for offset, value in enumerate(divisor):
            out[index + offset] ^= multiply(value, factor)
    return out[-(len(divisor) - 1):] if len(divisor) > 1 else []
