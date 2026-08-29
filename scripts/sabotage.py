"""Break the code one line at a time and require the measurements to notice.

THREE GATES, AND ALL THREE HAVE TO PASS FOR A SABOTAGE TO COUNT.

  IT APPLIES. The text it edits is actually in the file.

  IT MOVES THE FINGERPRINT. If the measurement produces the same bytes with the line broken, the
  measurement does not measure that line. This is the gate that does the work.

  IT IS THEN CAUGHT. The unit tests have to fail.

THE NULL CONTROL RUNS FIRST. An untouched copy of the tree, in a directory with a different name,
has to produce the same fingerprint. If it does not, the measurement tracks the working directory
rather than the code and every sabotage passes gate two for free.

WHAT MAKES THIS PROJECT UNUSUAL TO SABOTAGE. Most of it is arithmetic with an exact right answer,
so a broken line usually produces a symbol that does not decode, which every test notices at once.
The interesting sabotages are the ones that produce something that still works and is wrong: a
carver that overspends its budget by counting flips instead of codewords, a decoder that repairs
one error too many, an annotated file that forgets to say it cannot be scanned.
"""

from __future__ import annotations

import concurrent.futures
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent

# (name, file, find, replace)
SABOTAGES = [

    # ------------------------------------------------------------------ the field
    ("a different primitive polynomial, so the field is not the standard's",
     "mazeglyph/galois.py", "PRIMITIVE = 0x11D", "PRIMITIVE = 0x11B"),
    ("zero is multiplied through the logarithm table, which has no entry for it",
     "mazeglyph/galois.py",
     "    if left == 0 or right == 0:", "    if False:"),
    ("division does not reduce the exponent, so it wraps off the end of the table",
     "mazeglyph/galois.py",
     "    return EXP[(LOG[left] - LOG[right]) % 255]", "    return EXP[LOG[left] - LOG[right]]"),
    # A SABOTAGE WAS REMOVED HERE with the measurement that proved it inert. It neutered the check
    # that the generator reaches every element of the field. The check cannot fire for the standard
    # polynomial nor for the one the sabotage above substitutes, because 0x11B is primitive too, so
    # 2 generates both fields and the guard is silent in both. `measure.py` records which candidate
    # polynomials generate the field, so a substitution that DID break it would move the
    # fingerprint. The guard is kept because it costs nothing and would fire for a polynomial that
    # is not primitive.

    # ------------------------------------------------------------------ error correction
    ("the generator polynomial is built from the wrong roots", "mazeglyph/reedsolomon.py",
     "        poly = galois.poly_multiply(poly, [1, galois.alpha(index)])",
     "        poly = galois.poly_multiply(poly, [1, galois.alpha(index + 1)])"),
    ("the syndromes are taken at the wrong points", "mazeglyph/reedsolomon.py",
     "    return [galois.poly_evaluate(received, galois.alpha(index)) for index in range(count)]",
     "    return [galois.poly_evaluate(received, galois.alpha(index + 1)) "
     "for index in range(count)]"),
    ("the register length is taken from the polynomial's length again",
     "mazeglyph/reedsolomon.py",
     "        if 2 * register <= index:", "        if len(locator) - 1 <= index:"),
    # THREE GUARDS THAT ARE REDUNDANT WITH EACH OTHER, and the suite is honest about it. A block
    # damaged past its capacity is caught by the root count not matching the locator's degree, OR
    # by the error count exceeding the capacity, OR by the syndromes still being non-zero after the
    # repair. Remove any one and the other two still refuse, so no single edit moves the
    # measurement and three sabotages were removed from this list rather than excused.
    #
    # What remains is the check that the set as a whole is load-bearing, which `measure.py` records
    # directly: across 396 trials at error counts from the capacity to eleven past it, the number
    # of blocks repaired into something OTHER than the original is zero. That number is in the
    # fingerprint, so a decoder that started guessing would move it even though no one guard can be
    # singled out. Defence in depth is worth having and it is not something a one edit at a time
    # suite can measure, which is a limit of the suite rather than a fault in the code.
    ("the correction capacity is claimed to be one per correction codeword",
     "mazeglyph/reedsolomon.py", "    return count // 2", "    return count"),
    ("an error position is read from the wrong end of the block", "mazeglyph/reedsolomon.py",
     "        block[len(block) - 1 - position] ^= magnitude",
     "        block[position] ^= magnitude"),

    # ------------------------------------------------------------------ the geometry
    ("the alignment step is not rounded up to an even number", "mazeglyph/geometry.py",
     "    step = step + (step & 1)", "    step = step"),
    ("the symbol grows by five modules a version rather than four", "mazeglyph/geometry.py",
     "    return 17 + 4 * version", "    return 17 + 5 * version"),
    ("the zigzag does not step over the vertical timing pattern", "mazeglyph/geometry.py",
     "        if column == 6:", "        if False:"),
    ("the zigzag never turns around", "mazeglyph/geometry.py",
     "        upwards = not upwards", "        upwards = upwards"),
    ("the zigzag takes the left module of each pair first", "mazeglyph/geometry.py",
     "            for offset in (0, 1):", "            for offset in (1, 0):"),
    ("an alignment pattern is placed over a finder", "mazeglyph/geometry.py",
     "            if near_finder:\n                continue\n            for row in range(row_centre - 2, row_centre + 3):",
     "            if False:\n                continue\n            for row in range(row_centre - 2, row_centre + 3):"),
    ("the version information area is not reserved", "mazeglyph/geometry.py",
     "    if version < 7:\n        return set()", "    if True:\n        return set()"),

    # ------------------------------------------------------------------ encoding
    ("the character count is always eight bits", "mazeglyph/encode.py",
     "    return 8 if version <= 9 else 16", "    return 8"),
    # AND ANOTHER, also with its proof. It made the terminator a fixed four bits. In byte mode the
    # header is 12 or 20 bits and a codeword is 8, so a payload filled to the last whole byte
    # always leaves EXACTLY four bits spare: measured across all forty version and level
    # combinations, the spare is 4 every time and never less. So `min(4, spare)` can never bind and
    # the two are the same code. `measure.py` prints that census. The guard stays because the
    # numeric and alphanumeric modes have different header widths and would make it bind.
    ("the two pad bytes are the same byte", "mazeglyph/encode.py",
     "PAD_BYTES = (0xEC, 0x11)", "PAD_BYTES = (0xEC, 0xEC)"),
    ("the error correction codewords are woven before the data", "mazeglyph/encode.py",
     "    for index in range(max(sizes)):\n        for group in groups:\n            if index < len(group):\n                out.append(group[index])\n    for index in range(layout.ec_per_block):",
     "    for index in range(layout.ec_per_block):\n        for group in parity:\n            out.append(group[index])\n    for index in range(max(sizes)):\n        for group in groups:\n            if index < len(group):\n                out.append(group[index])\n    for index in range(0):"),
    ("the format information is masked with the wrong constant", "mazeglyph/encode.py",
     "FORMAT_MASK = 0b101010000010010", "FORMAT_MASK = 0b101010000010011"),
    ("the module that is always dark is left light", "mazeglyph/encode.py",
     "    grid[width - 8][8] = True", "    grid[width - 8][8] = False"),
    ("the mask is applied to the data before it is chosen rather than as it is written",
     "mazeglyph/encode.py",
     "        if rule(row, column):\n            bit ^= 1\n        grid[row][column] = bool(bit)",
     "        grid[row][column] = bool(bit)"),
    ("the mask is chosen by the highest penalty rather than the lowest", "mazeglyph/encode.py",
     "        if best is None or score < best[0]:", "        if best is None or score > best[0]:"),
    ("the finder-like pattern in the penalty is not looked for", "mazeglyph/encode.py",
     "            if before == light or after == light:\n                finders += 40",
     "            if False:\n                finders += 40"),
    ("the timing pattern starts dark on the wrong parity", "mazeglyph/encode.py",
     "            grid[6][index] = index % 2 == 0", "            grid[6][index] = index % 2 == 1"),

    # ------------------------------------------------------------------ decoding
    ("the format information is taken from one copy only", "mazeglyph/decode.py",
     "    for bits in (first, second):", "    for bits in (first,):"),
    ("a format reading too far from any valid word is accepted", "mazeglyph/decode.py",
     "    if best[0] > 3:\n        return None, best[0]",
     "    if best[0] > 15:\n        return None, best[0]"),
    ("two copies that disagree at the same distance are resolved by picking one",
     "mazeglyph/decode.py",
     "        if (best[1], best[2]) != (other[1], other[2]) and best[0] == other[0]:\n"
     "            return None, best[0]",
     "        if False:\n            return None, best[0]"),
    ("the blocks are put back in the order they were woven rather than end to end",
     "mazeglyph/decode.py",
     "    for block_index, size in enumerate(sizes):\n        data.extend(repaired[block_index][:size])",
     "    for round_index in range(max(sizes)):\n        for block_index, size in enumerate(sizes):\n            if round_index < size:\n                data.append(repaired[block_index][round_index])"),
    ("a block that could not be repaired is passed on as though it had been",
     "mazeglyph/decode.py",
     "    if beyond:\n        return Reading(ok=False", "    if False:\n        return Reading(ok=False"),
    ("the declared length is not checked against what is left", "mazeglyph/decode.py",
     "        if length * 8 > len(bits):", "        if False:"),

    # ------------------------------------------------------------------ the carving
    ("the budget is counted in flips rather than in codewords", "mazeglyph/maze.py",
     "            if word not in self.dirty[block]:\n                extra[block].add(word)",
     "            extra[block].add((word, cell))"),
    ("the per block budget is the whole correction count rather than half of it",
     "mazeglyph/maze.py",
     "        self.per_block = layout.ec_per_block // 2",
     "        self.per_block = layout.ec_per_block"),
    ("a carving that overspends is done anyway", "mazeglyph/maze.py",
     "            if len(self.dirty[block]) + len(words) > self.per_block:\n                return None",
     "            if False:\n                return None"),
    ("the function patterns are carvable", "mazeglyph/maze.py",
     "    reserved = geometry.function_modules(version)\n    return {(row, column) for row in range(width) for column in range(width)\n            if (row, column) not in reserved}",
     "    reserved = set()\n    return {(row, column) for row in range(width) for column in range(width)\n            if (row, column) not in reserved}"),
    ("the route charges for light modules and not for dark ones", "mazeglyph/maze.py",
     "            step = 1 if modules[here[0]][here[1]] else 0",
     "            step = 0 if modules[here[0]][here[1]] else 1"),
    ("the solver walks through walls", "mazeglyph/maze.py",
     "            if here in came or modules[here[0]][here[1]]:", "            if here in came:"),
    ("the endpoints are chosen from the whole data area rather than one region",
     "mazeglyph/maze.py",
     "    allowed = largest_region(carvable(symbol.version))", "    allowed = carvable(symbol.version)"),
    ("branches refused for want of budget are not counted", "mazeglyph/maze.py",
     "            refused += 1\n            continue", "            continue"),
    ("the maze is described over the whole symbol rather than what you can walk to",
     "mazeglyph/maze.py",
     "    region = reachable(modules, allowed, start)\n    branches = dead_ends = 0",
     "    region = set(allowed)\n    branches = dead_ends = 0"),

    # ------------------------------------------------------------------ what is reported
    ("the run does not check what it just carved", "mazeglyph/cli.py",
     "    return bool(reading.ok and reading.payload == payload and solved)", "    return True"),
    ("an unsolvable maze is reported as a success", "mazeglyph/cli.py",
     "    return bool(reading.ok and reading.payload == payload and solved)",
     "    return bool(reading.ok and reading.payload == payload)"),
    ("a symbol that decodes to something else is reported as a success", "mazeglyph/cli.py",
     "    return bool(reading.ok and reading.payload == payload and solved)",
     "    return bool(reading.ok and solved)"),
    ("the annotated file does not say it cannot be scanned", "mazeglyph/svg.py",
     '        out.append("<title>NOT SCANNABLE: the solution and the carving are drawn over this "',
     '        out.append("<title>a drawing of the symbol " + "" + ("'),
    ("the quiet zone is dropped", "mazeglyph/svg.py", "QUIET_ZONE = 4", "QUIET_ZONE = 0"),
]

def copy_tree(source: pathlib.Path, destination: pathlib.Path) -> None:
    shutil.copytree(source, destination,
                    ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"))


def apply(tree: pathlib.Path, target: str, find: str, replace: str) -> bool:
    path = tree / target
    text = path.read_text(encoding="utf-8")
    if find not in text:
        return False
    path.write_text(text.replace(find, replace, 1), encoding="utf-8")
    return True


def fingerprint(tree: pathlib.Path):
    """The measurement's sha256, or None if the tree is too broken to produce one.

    A tree that cannot measure itself has certainly changed, so None counts as a moved fingerprint
    rather than as an error. The alternative would let a sabotage that breaks the measurement
    outright pass gate two by crashing.
    """
    done = subprocess.run([sys.executable, "scripts/measure.py"], cwd=tree,
                          capture_output=True, text=True, timeout=3600)
    if done.returncode != 0:
        return None
    for line in done.stderr.splitlines():
        if line.startswith("FINGERPRINT "):
            return line.split()[1]
    return None


def tests_pass(tree: pathlib.Path) -> bool:
    done = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."],
                          cwd=tree, capture_output=True, text=True, timeout=3600)
    return done.returncode == 0


def one(clean, index, entry):
    """One sabotage through the three gates. Nothing is printed from here, because several run at
    once and interleaved output is unreadable."""
    name, target, find, replace = entry
    with tempfile.TemporaryDirectory() as area:
        tree = pathlib.Path(area) / f"sabotage-{index:02d}"
        copy_tree(ROOT, tree)
        if not apply(tree, target, find, replace):
            return ([f"FAIL {index:2d} did not apply: {name}",
                     f"        the text it edits is not in {target}"], False)
        if fingerprint(tree) == clean:
            return ([f"FAIL {index:2d} changed nothing measurable: {name}",
                     "        either the measurement is too narrow or this is not a sabotage"],
                    False)
        if tests_pass(tree):
            return ([f"FAIL {index:2d} was not caught: {name}"], False)
    return ([], True)


def main() -> int:
    with tempfile.TemporaryDirectory() as area:
        # A DIFFERENTLY NAMED directory, on purpose. A copy into a directory with the same name
        # would agree with the original even if the fingerprint tracked the path.
        control = pathlib.Path(area) / "a-completely-different-name"
        copy_tree(ROOT, control)
        clean = fingerprint(control)
        here = fingerprint(ROOT)
    if clean is None or here is None:
        print("the measurement would not run, so nothing below would mean anything")
        return 1
    if clean != here:
        print(f"NULL CONTROL FAILED: the same code fingerprints {here[:16]} here and "
              f"{clean[:16]} in a differently named directory.")
        print("The measurement tracks the working directory, so every sabotage would pass gate "
              "two for free. Nothing else in this run would mean anything.")
        return 1
    print(f"null control: an untouched copy in another directory fingerprints {clean[:16]}")

    workers = min(6, max(1, (os.cpu_count() or 2) - 1))
    outcomes = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(one, clean, index, entry)
                   for index, entry in enumerate(SABOTAGES, start=1)]
        for future in futures:
            outcomes.append(future.result())

    caught = 0
    for lines, counted in outcomes:
        for line in lines:
            print(line)
        if counted:
            caught += 1
    total = len(SABOTAGES)
    print(f"{caught} of {total} sabotages caught, null control held")
    if caught != total:
        print(f"{total - caught} of {total} sabotages did not behave")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
