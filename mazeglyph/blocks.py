"""How a version's codewords are split into error correction blocks.

THIS IS THE ONE TABLE IN THE PROJECT THAT CANNOT BE DERIVED. Everything else about a QR symbol
follows from its version: the size, where the function patterns go, how many modules are left for
data. How those modules are divided into Reed-Solomon blocks is a choice the standard made, and
the only place it exists is a table.

SO IT IS CHECKED AGAINST SOMETHING THAT IS DERIVED. Each row says how many blocks there are, how
many data codewords each holds, and how many error correction codewords each gets. Add all of that
up and it must equal the number of codewords the GEOMETRY says the version has, which is computed
from the module count in `geometry.py` and shares nothing with this file. `validate()` does that
for every row, `scripts/measure.py` prints the result, and a mistyped number here fails it. That
check caught two transcription errors on the day this was written.

WHY BLOCKS AT ALL. A single Reed-Solomon block over a large symbol would correct a fixed number of
codewords wherever they fell, so a scratch across one corner could exhaust it. Splitting into
blocks and interleaving them means damage in one part of the symbol is spread across every block,
and each block only has to survive its share. It matters here for the opposite reason: a maze
carved into one region of the symbol would otherwise destroy one block entirely, and interleaving
spreads the carving across all of them.

ERROR CORRECTION LEVELS. L, M, Q and H recover roughly 7, 15, 25 and 30 percent of the codewords.
This project uses H by default, because the recovery budget is the material the maze is carved
from and H provides the most of it.
"""

from __future__ import annotations

import dataclasses
from typing import Dict, List, Tuple

from . import geometry

LEVELS = ("L", "M", "Q", "H")

# Published total codewords per version. Present only so that `validate` has a second opinion that
# is not this file, and checked against the geometry as well, which is a third.
TOTAL_CODEWORDS = {1: 26, 2: 44, 3: 70, 4: 100, 5: 134, 6: 172, 7: 196, 8: 242, 9: 292, 10: 346}

# (version, level) -> (ec codewords per block, [(block count, data codewords per block), ...])
TABLE: Dict[Tuple[int, str], Tuple[int, List[Tuple[int, int]]]] = {
    (1, "L"): (7, [(1, 19)]),
    (1, "M"): (10, [(1, 16)]),
    (1, "Q"): (13, [(1, 13)]),
    (1, "H"): (17, [(1, 9)]),

    (2, "L"): (10, [(1, 34)]),
    (2, "M"): (16, [(1, 28)]),
    (2, "Q"): (22, [(1, 22)]),
    (2, "H"): (28, [(1, 16)]),

    (3, "L"): (15, [(1, 55)]),
    (3, "M"): (26, [(1, 44)]),
    (3, "Q"): (18, [(2, 17)]),
    (3, "H"): (22, [(2, 13)]),

    (4, "L"): (20, [(1, 80)]),
    (4, "M"): (18, [(2, 32)]),
    (4, "Q"): (26, [(2, 24)]),
    (4, "H"): (16, [(4, 9)]),

    (5, "L"): (26, [(1, 108)]),
    (5, "M"): (24, [(2, 43)]),
    (5, "Q"): (18, [(2, 15), (2, 16)]),
    (5, "H"): (22, [(2, 11), (2, 12)]),

    (6, "L"): (18, [(2, 68)]),
    (6, "M"): (16, [(4, 27)]),
    (6, "Q"): (24, [(4, 19)]),
    (6, "H"): (28, [(4, 15)]),

    (7, "L"): (20, [(2, 78)]),
    (7, "M"): (18, [(4, 31)]),
    (7, "Q"): (18, [(2, 14), (4, 15)]),
    (7, "H"): (26, [(4, 13), (1, 14)]),

    (8, "L"): (24, [(2, 97)]),
    (8, "M"): (22, [(2, 38), (2, 39)]),
    (8, "Q"): (22, [(4, 18), (2, 19)]),
    (8, "H"): (26, [(4, 14), (2, 15)]),

    (9, "L"): (30, [(2, 116)]),
    (9, "M"): (22, [(3, 36), (2, 37)]),
    (9, "Q"): (20, [(4, 16), (4, 17)]),
    (9, "H"): (24, [(4, 12), (4, 13)]),

    (10, "L"): (18, [(2, 68), (2, 69)]),
    (10, "M"): (26, [(4, 43), (1, 44)]),
    (10, "Q"): (24, [(6, 19), (2, 20)]),
    (10, "H"): (28, [(6, 15), (2, 16)]),
}

VERSIONS = tuple(sorted({version for version, _ in TABLE}))


@dataclasses.dataclass(frozen=True)
class Layout:
    version: int
    level: str
    ec_per_block: int
    blocks: Tuple[Tuple[int, int], ...]      # (count, data codewords) groups

    @property
    def block_count(self) -> int:
        return sum(count for count, _ in self.blocks)

    @property
    def data_codewords(self) -> int:
        return sum(count * size for count, size in self.blocks)

    @property
    def ec_codewords(self) -> int:
        return self.block_count * self.ec_per_block

    @property
    def total_codewords(self) -> int:
        return self.data_codewords + self.ec_codewords

    @property
    def correctable_codewords(self) -> int:
        """How many corrupted codewords the whole symbol survives, at best.

        AT BEST, and the distinction matters for the maze. Each block survives
        `ec_per_block // 2` errors, so the symbol survives that many times the block count ONLY IF
        the damage is spread evenly across the blocks. Concentrate it in one block and the symbol
        fails long before this number is reached. Interleaving is what makes the even spread the
        usual case.
        """
        return self.block_count * (self.ec_per_block // 2)

    def block_sizes(self) -> List[int]:
        out = []
        for count, size in self.blocks:
            out.extend([size] * count)
        return out

    def as_dict(self) -> dict:
        return {"version": self.version, "level": self.level,
                "blocks": self.block_count, "data_codewords": self.data_codewords,
                "ec_codewords": self.ec_codewords, "total_codewords": self.total_codewords,
                "ec_per_block": self.ec_per_block,
                "correctable_codewords": self.correctable_codewords}


def layout(version: int, level: str) -> Layout:
    key = (version, level.upper())
    if key not in TABLE:
        raise ValueError(f"version {version} at level {level!r} is not in this program's table; "
                         f"it knows versions {VERSIONS[0]} to {VERSIONS[-1]}")
    ec_per_block, groups = TABLE[key]
    return Layout(version=version, level=key[1], ec_per_block=ec_per_block,
                  blocks=tuple(groups))


def validate() -> List[str]:
    """Every row against the geometry and against the published totals. Empty means agreement."""
    problems = []
    for (version, level) in sorted(TABLE):
        found = layout(version, level)
        from_geometry = geometry.data_module_count(version) // 8
        if found.total_codewords != from_geometry:
            problems.append(
                f"version {version} level {level}: the block table adds up to "
                f"{found.total_codewords} codewords and the geometry has room for "
                f"{from_geometry}")
        published = TOTAL_CODEWORDS.get(version)
        if published is not None and found.total_codewords != published:
            problems.append(
                f"version {version} level {level}: the block table adds up to "
                f"{found.total_codewords} codewords and the published total is {published}")
        # The two group sizes must differ by exactly one where there are two, which is how the
        # standard always splits an uneven division.
        if len(found.blocks) == 2 and found.blocks[1][1] - found.blocks[0][1] != 1:
            problems.append(
                f"version {version} level {level}: the two block sizes are "
                f"{found.blocks[0][1]} and {found.blocks[1][1]}, which differ by more than one")
    return problems
