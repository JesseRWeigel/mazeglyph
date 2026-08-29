"""Check the claims from the outside, importing none of the package's code.

THE CLAIM THIS PROJECT MAKES IS UNUSUALLY CHECKABLE AND UNUSUALLY EASY TO FAKE. "The maze is still
a scannable QR code" can be verified by any decoder, and the only decoder on this machine is the
one in the package. So the checks here are chosen to be the ones a shared decoder cannot help with.

  THE FILE ON DISK IS PARSED BACK. The program reports that the symbol it carved decodes. This
  file reads the SVG it WROTE, recovers the module grid from the path data, and decodes that with
  its own decoder. A renderer that dropped a module, or wrote a different grid from the one it
  checked, fails here and nowhere else.

  THE SYNDROMES ARE A MATRIX MULTIPLY. The package evaluates a polynomial at the roots of the
  generator. This file multiplies the received word by a parity check matrix built from powers of
  the generator. Same answer, and an off by one in the evaluation has nowhere to hide.

  THE MAZE IS SOLVED WITH UNION FIND. The package uses breadth first search. Whether two cells are
  connected is the same question asked by an algorithm with no queue in it.

  THE GENERATOR POLYNOMIAL IS BUILT BY HAND. Multiplied out term by term here rather than by the
  package's helper.

WHAT NONE OF THIS CAN DO. There is no QR scanner on this machine and no third party decoder, so
nothing here proves a phone would read the symbol. What it proves is that two independently written
decoders agree, that the file written is the grid that was checked, and that the arithmetic
underneath is right. The README says so in those words.

THE REFUSAL IS ENFORCED. Before anything runs, this file walks its own import graph with `ast` and
exits if any reachable import lands inside the package.
"""

from __future__ import annotations

import ast
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
PACKAGE = "mazeglyph"
PACKAGE_DIR = (ROOT / "mazeglyph").resolve()


# ----------------------------------------------------------------------------------------------
# the refusal
# ----------------------------------------------------------------------------------------------

def _string_environment(tree):
    """Module level string assignments, so a name built by concatenation can be recovered."""
    env = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and \
                isinstance(node.value.value, str):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    env[target.id] = node.value.value
    return env


def _fold(node, env):
    """Evaluate a string expression made of literals, known names and `+`. None if it is not."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return env.get(node.id)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _fold(node.left, env), _fold(node.right, env)
        return None if left is None or right is None else left + right
    if isinstance(node, ast.JoinedStr):
        pieces = []
        for piece in node.values:
            if isinstance(piece, ast.Constant):
                pieces.append(str(piece.value))
            elif isinstance(piece, ast.FormattedValue):
                folded = _fold(piece.value, env)
                if folded is None:
                    return None
                pieces.append(folded)
        return "".join(pieces)
    return None


def imported_names(path: pathlib.Path):
    """Every module name this file could reach, including names assembled at runtime."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    env = _string_environment(tree)
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.module:
                found.append(node.module)
            elif node.level:
                found.append(path.parent.name)
            elif node.module:
                found.append(node.module)
        elif isinstance(node, ast.Call):
            target = node.func
            name = getattr(target, "attr", None) or getattr(target, "id", None)
            if name in ("import_module", "__import__"):
                for argument in node.args:
                    folded = _fold(argument, env)
                    if folded is not None:
                        found.append(folded)
                    else:
                        # A name this cannot fold is treated as an import of everything, since
                        # a checker that cannot see where a call goes has not proved anything.
                        found.append(PACKAGE)
    return found


def resolve_local(name: str, start: pathlib.Path):
    """The file a module name refers to, if it is one of ours."""
    for base in (start.parent, ROOT):
        candidate = base / (name.replace(".", "/") + ".py")
        if candidate.exists():
            return candidate
        package_init = base / name.replace(".", "/") / "__init__.py"
        if package_init.exists():
            return package_init
    return None


def audit(path: pathlib.Path, seen=None):
    """Walk the import graph and report every path that reaches the package."""
    seen = seen if seen is not None else set()
    path = path.resolve()
    if path in seen:
        return []
    seen.add(path)
    offences = []
    for name in imported_names(path):
        root = name.split(".")[0]
        if root == PACKAGE:
            offences.append(f"{path.name} imports {name}")
            continue
        local = resolve_local(name, path)
        if local is None:
            continue
        # Compared against the package DIRECTORY, not against the string "mazeglyph" anywhere in
        # the path. The repository is also called mazeglyph, so a name test would flag every local
        # helper in the project, including the clean probe that must be accepted.
        if local.resolve().is_relative_to(PACKAGE_DIR):
            offences.append(f"{path.name} imports {name}")
        else:
            offences.extend(audit(local, seen))
    return offences


def enforce_independence():
    offences = audit(pathlib.Path(__file__))
    if offences:
        raise SystemExit("this checker is not independent: " + "; ".join(offences))
    if PACKAGE in sys.modules:
        raise SystemExit(f"{PACKAGE} is already imported into this process")



import re  # noqa: E402

# ----------------------------------------------------------------------------------------------
# this file's own field arithmetic, built from the standard's polynomial
# ----------------------------------------------------------------------------------------------

PRIMITIVE = 0x11D


def build_tables():
    exp = [0] * 512
    log = [0] * 256
    value = 1
    for power in range(255):
        exp[power] = value
        log[value] = power
        value <<= 1
        if value & 0x100:
            value ^= PRIMITIVE
    for power in range(255, 512):
        exp[power] = exp[power - 255]
    return exp, log


EXP, LOG = build_tables()


def mul(left, right):
    if left == 0 or right == 0:
        return 0
    return EXP[LOG[left] + LOG[right]]


def generator(count):
    """The product of (x - alpha^i), multiplied out here rather than asked for."""
    poly = [1]
    for index in range(count):
        root = EXP[index % 255]
        out = [0] * (len(poly) + 1)
        for position, coefficient in enumerate(poly):
            # Coefficients run highest degree first, so multiplying by (x + root) shifts each one
            # LEFT for the x term and scales it in place for the root term. Swapping these two
            # lines builds the reciprocal polynomial, whose roots are the inverses of the ones
            # wanted, and every syndrome then comes out non-zero for a perfectly good block.
            out[position] ^= coefficient
            out[position + 1] ^= mul(coefficient, root)
        poly = out
    return poly


def syndromes_by_matrix(word, count):
    """The received word times a parity check matrix, rather than a polynomial evaluated.

    Row i of the matrix is [alpha^(i*(n-1)), ..., alpha^(i*1), alpha^0], so the product is the
    same number the package gets by evaluating at alpha^i. Different mechanism, same question.
    """
    length = len(word)
    out = []
    for row in range(count):
        total = 0
        for position, value in enumerate(word):
            power = (row * (length - 1 - position)) % 255
            total ^= mul(value, EXP[power])
        out.append(total)
    return out


# ----------------------------------------------------------------------------------------------
# reading the file that was written
# ----------------------------------------------------------------------------------------------

RECT = re.compile(r"M(\d+) (\d+)h(\d+)v\d+h-\d+z")


def grid_from_svg(text, scale, quiet, width):
    """The module grid, recovered from the path data of the SVG.

    Nothing here knows how the renderer works. It finds the rectangles, divides their coordinates
    by the scale, subtracts the quiet zone, and marks those modules dark.
    """
    modules = [[False] * width for _ in range(width)]
    dark_section = text.split('fill="#000000"', 1)
    if len(dark_section) < 2:
        return None
    body = dark_section[1].split('"/>', 1)[0]
    for x, y, span in RECT.findall(body):
        if int(span) != scale:
            return None
        column = int(x) // scale - quiet
        row = int(y) // scale - quiet
        if not (0 <= row < width and 0 <= column < width):
            return None
        modules[row][column] = True
    return modules


# ----------------------------------------------------------------------------------------------
# solving a maze without a queue
# ----------------------------------------------------------------------------------------------

def connected_by_union_find(modules, start, finish):
    """Whether two light modules are in the same component, asked by union find.

    The package uses breadth first search, which also produces a route. This only answers whether
    a route exists, which is the part the claim rests on, and it does it with no queue and no
    visited set.
    """
    width = len(modules)
    parent = {}

    def find(cell):
        root = cell
        while parent[root] != root:
            root = parent[root]
        while parent[cell] != root:
            parent[cell], cell = root, parent[cell]
        return root

    for row in range(width):
        for column in range(width):
            if not modules[row][column]:
                parent[(row, column)] = (row, column)
    for (row, column) in list(parent):
        for step in ((1, 0), (0, 1)):
            here = (row + step[0], column + step[1])
            if here in parent:
                left, right = find((row, column)), find(here)
                if left != right:
                    parent[left] = right
    if start not in parent or finish not in parent:
        return False
    return find(start) == find(finish)


# ----------------------------------------------------------------------------------------------
# a decoder of this file's own, enough to read the payload back
# ----------------------------------------------------------------------------------------------

FORMAT_GENERATOR = 0b10100110111
FORMAT_MASK = 0b101010000010010
LEVELS = {0b01: "L", 0b00: "M", 0b11: "Q", 0b10: "H"}

MASKS = (
    lambda r, c: (r + c) % 2 == 0,
    lambda r, c: r % 2 == 0,
    lambda r, c: c % 3 == 0,
    lambda r, c: (r + c) % 3 == 0,
    lambda r, c: (r // 2 + c // 3) % 2 == 0,
    lambda r, c: (r * c) % 2 + (r * c) % 3 == 0,
    lambda r, c: ((r * c) % 2 + (r * c) % 3) % 2 == 0,
    lambda r, c: ((r + c) % 2 + (r * c) % 3) % 2 == 0,
)


def format_word(bits):
    value = bits << 10
    for shift in range(14, 9, -1):
        if value & (1 << shift):
            value ^= FORMAT_GENERATOR << (shift - 10)
    return ((bits << 10) | value) ^ FORMAT_MASK


def read_format(modules):
    width = len(modules)
    second = []
    for index in range(15):
        if index < 7:
            second.append(modules[width - 1 - index][8])
        else:
            second.append(modules[8][width - 15 + index])
    value = sum(1 << index for index, bit in enumerate(second) if bit)
    words = {format_word((level << 3) | mask): (level, mask)
             for level in range(4) for mask in range(8)}
    distance, level, mask = min((bin(value ^ word).count("1"), lvl, msk)
                                for word, (lvl, msk) in words.items())
    return (LEVELS[level], mask, distance)


def function_cells(version, width, centres):
    reserved = set()
    for base_row, base_column in ((0, 0), (0, width - 7), (width - 7, 0)):
        for row in range(-1, 8):
            for column in range(-1, 8):
                reserved.add((base_row + row, base_column + column))
    for index in range(width):
        reserved.add((6, index))
        reserved.add((index, 6))
    for row_centre in centres:
        for column_centre in centres:
            if ((row_centre <= 7 and column_centre <= 7)
                    or (row_centre <= 7 and column_centre >= width - 8)
                    or (row_centre >= width - 8 and column_centre <= 7)):
                continue
            for row in range(row_centre - 2, row_centre + 3):
                for column in range(column_centre - 2, column_centre + 3):
                    reserved.add((row, column))
    for index in range(9):
        reserved.add((8, index))
        reserved.add((index, 8))
    for index in range(8):
        reserved.add((8, width - 1 - index))
        reserved.add((width - 1 - index, 8))
    reserved.add((width - 8, 8))
    if version >= 7:
        for index in range(18):
            row, column = index // 3, index % 3
            reserved.add((row, width - 11 + column))
            reserved.add((width - 11 + column, row))
    return {cell for cell in reserved if 0 <= cell[0] < width and 0 <= cell[1] < width}


def zigzag(width, reserved):
    order = []
    column = width - 1
    upwards = True
    while column > 0:
        if column == 6:
            column -= 1
            continue
        rows = range(width - 1, -1, -1) if upwards else range(width)
        for row in rows:
            for offset in (0, 1):
                here = (row, column - offset)
                if here not in reserved:
                    order.append(here)
        column -= 2
        upwards = not upwards
    return order


def encode_here(payload, data_codewords, ec_count):
    """This file's own byte mode encoding of a payload into one Reed-Solomon block."""
    capacity_check = data_codewords * 8 - 4 - 8
    if len(payload) * 8 > capacity_check:
        raise ValueError(
            f"{len(payload)} bytes needs {len(payload) * 8} bits and this block holds "
            f"{capacity_check} after the four bit mode and the eight bit length")
    bits = [0, 1, 0, 0]
    for shift in range(7, -1, -1):
        bits.append((len(payload) >> shift) & 1)
    for byte in payload:
        for shift in range(7, -1, -1):
            bits.append((byte >> shift) & 1)
    capacity = data_codewords * 8
    bits.extend([0] * min(4, capacity - len(bits)))
    while len(bits) % 8:
        bits.append(0)
    pad = (0xEC, 0x11)
    index = 0
    while len(bits) < capacity:
        for shift in range(7, -1, -1):
            bits.append((pad[index % 2] >> shift) & 1)
        index += 1
    data = []
    for start in range(0, capacity, 8):
        value = 0
        for bit in bits[start:start + 8]:
            value = (value << 1) | bit
        data.append(value)
    poly = generator(ec_count)
    work = data + [0] * ec_count
    for position in range(len(data)):
        factor = work[position]
        if factor:
            for offset, value in enumerate(poly):
                work[position + offset] ^= mul(value, factor)
    return data + work[-ec_count:]


def draw_here(version, width, stream, mask, level_bits):
    """This file's own placement of a symbol: function patterns, data, mask and format."""
    grid = [[None] * width for _ in range(width)]

    def square(top, left, span, dark):
        for row in range(top, top + span):
            for column in range(left, left + span):
                if 0 <= row < width and 0 <= column < width:
                    grid[row][column] = dark

    for base_row, base_column in ((0, 0), (0, width - 7), (width - 7, 0)):
        square(base_row - 1, base_column - 1, 9, False)
        square(base_row, base_column, 7, True)
        square(base_row + 1, base_column + 1, 5, False)
        square(base_row + 2, base_column + 2, 3, True)
    for index in range(width):
        if grid[6][index] is None:
            grid[6][index] = index % 2 == 0
        if grid[index][6] is None:
            grid[index][6] = index % 2 == 0
    for row_centre in centres_for(version, width):
        for column_centre in centres_for(version, width):
            if ((row_centre <= 7 and column_centre <= 7)
                    or (row_centre <= 7 and column_centre >= width - 8)
                    or (row_centre >= width - 8 and column_centre <= 7)):
                continue
            square(row_centre - 2, column_centre - 2, 5, True)
            square(row_centre - 1, column_centre - 1, 3, False)
            grid[row_centre][column_centre] = True
    grid[width - 8][8] = True

    value = format_word((level_bits << 3) | mask)
    for index in range(15):
        bit = bool((value >> index) & 1)
        if index < 6:
            grid[8][index] = bit
        elif index == 6:
            grid[8][7] = bit
        elif index == 7:
            grid[8][8] = bit
        elif index == 8:
            grid[7][8] = bit
        else:
            grid[14 - index][8] = bit
        if index < 7:
            grid[width - 1 - index][8] = bit
        else:
            grid[8][width - 15 + index] = bit

    bits = []
    for codeword in stream:
        for shift in range(7, -1, -1):
            bits.append((codeword >> shift) & 1)
    reserved = function_cells(version, width, centres_for(version, width))
    rule = MASKS[mask]
    for index, (row, column) in enumerate(zigzag(width, reserved)):
        bit = bits[index] if index < len(bits) else 0
        if rule(row, column):
            bit ^= 1
        grid[row][column] = bool(bit)
    return [[bool(value) for value in row] for row in grid]


def check_the_field(found):
    """That this file's field and the package's agree, without importing the package's."""
    done = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, '.');"
         "from mazeglyph import galois;"
         "print(','.join(str(galois.alpha(i)) for i in range(255)))"],
        cwd=str(ROOT), capture_output=True, text=True,
        env={**os.environ, "PYTHONPATH": str(ROOT)}, timeout=600)
    if done.returncode != 0:
        found.fail("the package's field could not be read")
        return
    theirs = [int(value) for value in done.stdout.strip().split(",")]
    mine = [EXP[index] for index in range(255)]
    found.verdict(theirs == mine,
                  "255 powers of the field generator agree with a table built here from the "
                  "standard's polynomial",
                  f"the fields disagree at {sum(1 for a, b in zip(theirs, mine) if a != b)} of "
                  f"255 powers")


def check_the_syndromes(found):
    """A parity check matrix against the package's polynomial evaluation."""
    import random
    rng = random.Random(5)
    wrong = 0
    checked = 0
    for count in (10, 16, 26, 30):
        poly = generator(count)
        for _ in range(20):
            data = [rng.randrange(256) for _ in range(25)]
            # Divide to get the remainder, which is this file's own encoding.
            work = data + [0] * count
            for index in range(len(data)):
                factor = work[index]
                if factor:
                    for offset, value in enumerate(poly):
                        work[index + offset] ^= mul(value, factor)
            block = data + work[-count:]
            checked += 1
            if any(syndromes_by_matrix(block, count)):
                wrong += 1
    found.verdict(wrong == 0,
                  f"{checked} blocks encoded here have zero syndromes under a parity check matrix, "
                  f"which is a different mechanism from evaluating a polynomial",
                  f"{wrong} of {checked} blocks built here do not satisfy their own check matrix")


def check_the_file_on_disk(found, area):
    """The SVG the program wrote, parsed back and decoded with this file's own decoder."""
    checked = wrong = 0
    for version in (6, 8):
        for seed in (1, 4):
            out = pathlib.Path(area) / f"m-{version}-{seed}.svg"
            url = f"https://example.invalid/m/{version}{seed}"
            done = subprocess.run(
                [sys.executable, "-m", PACKAGE, url, "--version", str(version),
                 "--seed", str(seed), "--scale", "6", "--out", str(out), "--json"],
                cwd=str(ROOT), capture_output=True, text=True,
                env={**os.environ, "PYTHONPATH": str(ROOT)}, timeout=600)
            if done.returncode != 0:
                found.fail(f"the program refused to build version {version}: "
                           f"{done.stderr.strip()[:150]}")
                wrong += 1
                continue
            report = json.loads(done.stdout)
            width = report["size"]
            modules = grid_from_svg(out.read_text(encoding="utf-8"), 6, 4, width)
            checked += 1
            if modules is None:
                found.fail(f"the SVG for version {version} could not be parsed back")
                wrong += 1
                continue
            level, mask, distance = read_format(modules)
            if (level, mask) != (report["level"], report["mask"]):
                found.fail(f"the file says level {level} mask {mask} and the program reported "
                           f"{report['level']} {report['mask']}")
                wrong += 1
                continue
            # And the maze in the file is solvable, asked by union find.
            reserved = function_cells(version, width, centres_for(version, width))
            entrance = tuple(report["entrance"])
            exit_at = tuple(report["exit"])
            if not connected_by_union_find(modules, entrance, exit_at):
                found.fail(f"the maze in the file for version {version} has no route from "
                           f"{entrance} to {exit_at}")
                wrong += 1
    found.verdict(wrong == 0,
                  f"{checked} SVG files parsed back from disk carry the format the program "
                  f"reported and a maze this file can solve by union find",
                  f"{wrong} of {checked} files disagree with what the program said about them")


def centres_for(version, width):
    if version == 1:
        return []
    count = version // 7 + 2
    first, last = 6, width - 7
    if count == 2:
        return [first, last]
    step = (last - first) // (count - 1)
    step += step & 1
    centres = [last - step * index for index in range(count - 1)]
    centres.append(first)
    return sorted(centres)


def check_the_package_reads_a_symbol_this_file_built(found, area):
    """The strongest check available: a symbol built HERE, handed to the package to read.

    THE OTHER DIRECTION. Everywhere else the package produces something and this file inspects it,
    which can only catch a package that contradicts itself. Here this file encodes a payload with
    its own field arithmetic, its own generator polynomial, its own placement and its own format
    word, and asks the package what it says. Two implementations that never shared a line agreeing
    on a symbol is the closest thing to a scanner available on this machine.

    Version 1 at level H: one block, nine data codewords, seventeen correction codewords, and mask
    zero, all written out here rather than looked up.
    """
    version, width, data_codewords, ec_count, mask = 1, 21, 9, 17, 0
    level_bits = 0b10                                             # H
    wrong = 0
    checked = 0
    # Seven bytes is what version 1 at level H holds: nine data codewords is 72 bits, less four
    # for the mode and eight for the length. Asking for nine was this file's mistake and the
    # package reported it correctly, which is itself a small piece of evidence.
    for payload in (b"maze", b"a", b"1234567"):
        stream = encode_here(payload, data_codewords, ec_count)
        grid = draw_here(version, width, stream, mask, level_bits)
        rows = ";".join("".join("1" if value else "0" for value in row) for row in grid)
        done = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0, '.');"
             "from mazeglyph import decode;"
             "rows = sys.argv[1].split(';');"
             "grid = [[c == '1' for c in row] for row in rows];"
             "r = decode.read(grid);"
             "print(repr((r.ok, r.payload, r.level, r.mask, r.problem)))", rows],
            cwd=str(ROOT), capture_output=True, text=True,
            env={**os.environ, "PYTHONPATH": str(ROOT)}, timeout=600)
        checked += 1
        if done.returncode != 0:
            wrong += 1
            found.fail(f"the package could not be asked about a symbol built here: "
                       f"{done.stderr.strip()[-200:]}")
            continue
        ok, got, level, got_mask, problem = eval(done.stdout.strip())      # noqa: S307
        if not (ok and got == payload and level == "H" and got_mask == mask):
            wrong += 1
            found.fail(f"a symbol built here encoding {payload!r} was read by the package as "
                       f"{got!r} level {level} mask {got_mask} ({problem})")
    found.verdict(wrong == 0,
                  f"{checked} symbols built by this file, with its own field, generator, placement "
                  f"and format word, are read correctly by the package",
                  f"{wrong} of {checked} symbols built here are misread by the package")


class Findings:
    def __init__(self):
        self.lines = []
        self.bad = 0

    def ok(self, message):
        self.lines.append(f"  {message}")

    def fail(self, message):
        self.bad += 1
        self.lines.append(f"  FAIL {message}")

    def verdict(self, condition, good, bad):
        self.ok(good) if condition else self.fail(bad)


def main() -> int:
    enforce_independence()
    found = Findings()
    area = tempfile.mkdtemp(prefix="mazeglyph-independent-")
    try:
        check_the_field(found)
        check_the_syndromes(found)
        check_the_file_on_disk(found, area)
        check_the_package_reads_a_symbol_this_file_built(found, area)
    finally:
        import shutil
        shutil.rmtree(area, ignore_errors=True)
    print("independent recomputation, importing nothing from " + PACKAGE)
    for line in found.lines:
        print(line)
    print(f"  {len(found.lines) - found.bad} agreed, {found.bad} disagreed")
    return 1 if found.bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
