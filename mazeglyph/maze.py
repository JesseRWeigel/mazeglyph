"""Carving a maze into a QR symbol, paid for out of the error correction budget.

THE IDEA THAT MAKES THIS POSSIBLE AT ALL. A QR symbol's data area already looks like noise: rough
half of its modules are light and half are dark, scattered. A maze needs passages, and a passage is
a connected run of light modules. So most of a maze is ALREADY THERE and costs nothing. What costs
something is the dark modules a passage has to cross, because flipping one corrupts the codeword it
belongs to, and there are only so many corrupt codewords the symbol survives.

SO THE CARVING IS A SHORTEST PATH PROBLEM WITH AN UNUSUAL COST. Moving onto a module that is
already light is free. Moving onto a dark one costs one flip. The cheapest route from the entrance
to the exit is therefore the one that threads through the light modules the symbol happens to have,
flipping as few as it can, and that is exactly what "exploit the error correction budget" means
here: the budget is not spent carving a corridor, it is spent only where the existing pattern
refuses to cooperate.

THE BUDGET IS COUNTED IN CODEWORDS AND NOT IN FLIPS, and the difference is large. A codeword is
eight modules, so eight flips that happen to land in one codeword cost the same as one flip. The
accounting below tracks which codeword each module belongs to and which BLOCK that codeword is in,
because the budget is per block: a block with 28 correction codewords survives 14 corrupt ones, and
concentrating damage in one block fails long before the symbol's total is reached.

WHAT IS NEVER TOUCHED. The finder patterns, the separators, the timing patterns, the alignment
patterns and the format information. A scanner uses those to find the symbol at all, they are not
protected by the Reed-Solomon code, and a maze carved through them produces something no scanner
would even recognise as a QR code. They are excluded before anything else happens.
"""

from __future__ import annotations

import collections
import dataclasses
import heapq
from typing import Dict, List, Optional, Sequence, Set, Tuple

from . import blocks as blocks_mod, encode, geometry

Cell = Tuple[int, int]


@dataclasses.dataclass
class Carving:
    """A carved symbol and the full account of what the carving cost."""

    modules: List[List[bool]]
    flipped: List[Cell] = dataclasses.field(default_factory=list)
    entrance: Cell = (0, 0)
    exit: Cell = (0, 0)
    corrupted_per_block: Dict[int, int] = dataclasses.field(default_factory=dict)
    budget_per_block: int = 0
    blocks: int = 0
    path: List[Cell] = dataclasses.field(default_factory=list)
    branches: int = 0
    dead_ends: int = 0
    refused_branches: int = 0
    walkable: int = 0
    loops: int = 0

    @property
    def worst_block(self) -> int:
        return max(self.corrupted_per_block.values()) if self.corrupted_per_block else 0

    @property
    def budget_used(self) -> float:
        return (self.worst_block / self.budget_per_block) if self.budget_per_block else 0.0

    def as_dict(self) -> dict:
        return {"modules_flipped": len(self.flipped),
                "corrupted_codewords": sum(self.corrupted_per_block.values()),
                "worst_block_corrupted": self.worst_block,
                "budget_per_block": self.budget_per_block,
                "blocks": self.blocks,
                "fraction_of_the_worst_block_budget_used": round(self.budget_used, 4),
                "solution_length": len(self.path),
                "walkable_cells": self.walkable,
                "independent_loops": self.loops,
                "branches": self.branches,
                "dead_ends": self.dead_ends,
                "branches_refused_for_want_of_budget": self.refused_branches,
                "entrance": list(self.entrance), "exit": list(self.exit)}


def module_owner(version: int, layout: blocks_mod.Layout) -> Dict[Cell, int]:
    """Which error correction block each data module's codeword belongs to.

    Built by walking the interleave in the same order it is written, so a module's block is a fact
    about where its bit landed rather than a guess from its position on the grid.
    """
    sizes = layout.block_sizes()
    owner_of_stream_position: List[int] = []
    longest = max(sizes)
    for round_index in range(longest):
        for block_index, size in enumerate(sizes):
            if round_index < size:
                owner_of_stream_position.append(block_index)
    for _ in range(layout.ec_per_block):
        for block_index in range(len(sizes)):
            owner_of_stream_position.append(block_index)

    out: Dict[Cell, int] = {}
    for index, cell in enumerate(geometry.zigzag(version)):
        codeword = index // 8
        if codeword < len(owner_of_stream_position):
            out[cell] = owner_of_stream_position[codeword]
    return out


def module_codeword(version: int) -> Dict[Cell, int]:
    """Which codeword each data module is a bit of."""
    return {cell: index // 8 for index, cell in enumerate(geometry.zigzag(version))}


def carvable(version: int) -> Set[Cell]:
    """Every module a maze may touch: the data area and nothing else."""
    width = geometry.size(version)
    reserved = geometry.function_modules(version)
    return {(row, column) for row in range(width) for column in range(width)
            if (row, column) not in reserved}


class Budget:
    """How much of each block's correction capacity has been spent, and what is left."""

    def __init__(self, version: int, layout: blocks_mod.Layout):
        self.owner = module_owner(version, layout)
        self.codeword = module_codeword(version)
        self.per_block = layout.ec_per_block // 2
        self.blocks = layout.block_count
        self.dirty: Dict[int, Set[int]] = {index: set() for index in range(self.blocks)}

    def cost_of(self, cells: Sequence[Cell]) -> Optional[Dict[int, Set[int]]]:
        """Which codewords a set of flips would newly dirty, per block, or None if unaffordable."""
        extra: Dict[int, Set[int]] = collections.defaultdict(set)
        for cell in cells:
            block = self.owner.get(cell)
            if block is None:
                continue
            word = self.codeword[cell]
            if word not in self.dirty[block]:
                extra[block].add(word)
        for block, words in extra.items():
            if len(self.dirty[block]) + len(words) > self.per_block:
                return None
        return dict(extra)

    def spend(self, extra: Dict[int, Set[int]]) -> None:
        for block, words in extra.items():
            self.dirty[block] |= words

    def spent(self) -> Dict[int, int]:
        return {block: len(words) for block, words in self.dirty.items()}


def largest_region(allowed: Set[Cell]) -> Set[Cell]:
    """The biggest connected run of carvable modules.

    THE DATA AREA IS NOT ONE PIECE, which is not obvious and which broke the first version of this
    file. Both timing patterns run the full width of the symbol: the vertical one walls off the six
    columns to its left, and the horizontal one walls off the six rows above it. For a version 6
    symbol that is 144 modules stranded in each strip, exactly symmetric, and neither can ever be
    part of a maze that crosses the symbol. A maze whose entrance landed in one of them could never
    be solved, and the carver reported that there was no route through the data area at all, which
    sounded like a bug in the search rather than a fact about the symbol.

    So the endpoints are chosen inside one region, and which region is decided here rather than
    assumed.
    """
    seen: Set[Cell] = set()
    best: Set[Cell] = set()
    for cell in sorted(allowed):
        if cell in seen:
            continue
        region = {cell}
        queue = collections.deque([cell])
        while queue:
            here = queue.popleft()
            for other in _neighbours(here, allowed):
                if other not in region:
                    region.add(other)
                    queue.append(other)
        seen |= region
        if len(region) > len(best):
            best = region
    return best


def _neighbours(cell: Cell, allowed: Set[Cell]) -> List[Cell]:
    row, column = cell
    out = []
    for step in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        here = (row + step[0], column + step[1])
        if here in allowed:
            out.append(here)
    return out


def cheapest_path(modules, allowed: Set[Cell], start: Cell, finish: Cell):
    """The route from start to finish that flips the fewest dark modules.

    Dijkstra with a cost of zero for a module that is already light and one for a dark one. A plain
    breadth first search would find the SHORTEST route, which is a different thing and usually a
    much more expensive one: the shortest route ignores what the symbol already looks like and
    charges for every dark module in a straight line.
    """
    if start not in allowed or finish not in allowed:
        return None
    seen: Dict[Cell, int] = {start: 0 if not modules[start[0]][start[1]] else 1}
    came: Dict[Cell, Optional[Cell]] = {start: None}
    queue = [(seen[start], start)]
    while queue:
        cost, cell = heapq.heappop(queue)
        if cost > seen.get(cell, cost + 1):
            continue
        if cell == finish:
            break
        for here in _neighbours(cell, allowed):
            step = 1 if modules[here[0]][here[1]] else 0
            fresh = cost + step
            if fresh < seen.get(here, fresh + 1):
                seen[here] = fresh
                came[here] = cell
                heapq.heappush(queue, (fresh, here))
    if finish not in came:
        return None
    path = []
    cell: Optional[Cell] = finish
    while cell is not None:
        path.append(cell)
        cell = came[cell]
    path.reverse()
    return path


def solve(modules, allowed: Set[Cell], start: Cell, finish: Cell) -> Optional[List[Cell]]:
    """The shortest route through modules that are ALREADY light, or None if there is not one.

    This is the check that the maze is a maze. It never flips anything, so it answers the question
    a person with a pencil would ask.
    """
    if start not in allowed or finish not in allowed:
        return None
    if modules[start[0]][start[1]] or modules[finish[0]][finish[1]]:
        return None
    came: Dict[Cell, Optional[Cell]] = {start: None}
    queue = collections.deque([start])
    while queue:
        cell = queue.popleft()
        if cell == finish:
            break
        for here in _neighbours(cell, allowed):
            if here in came or modules[here[0]][here[1]]:
                continue
            came[here] = cell
            queue.append(here)
    if finish not in came:
        return None
    path = []
    cell: Optional[Cell] = finish
    while cell is not None:
        path.append(cell)
        cell = came[cell]
    path.reverse()
    return path


def reachable(modules, allowed: Set[Cell], start: Cell) -> Set[Cell]:
    """Every light module a walker starting at `start` can get to."""
    if start not in allowed or modules[start[0]][start[1]]:
        return set()
    seen = {start}
    queue = collections.deque([start])
    while queue:
        cell = queue.popleft()
        for here in _neighbours(cell, allowed):
            if here not in seen and not modules[here[0]][here[1]]:
                seen.add(here)
                queue.append(here)
    return seen


def describe(modules, allowed: Set[Cell], start: Cell) -> Tuple[int, int, int, int]:
    """(cells, branch points, dead ends, independent loops) reachable FROM THE ENTRANCE.

    THE LOOP COUNT IS THE HONEST DESCRIPTION OF WHAT THIS PRODUCES. A perfect maze is a tree: one
    route between any two points and no loops at all. What comes out of here is not that, and
    saying so is better than implying otherwise. A QR symbol's data area is about half light
    modules already, so the light region is a large connected blob before anything is carved, and
    the carving only widens it. Turning it into a tree would mean ADDING walls, light modules
    flipped to dark, and every one of those costs the same as a passage does; the budget will not
    buy both.

    So this is a braid maze: solvable, full of junctions, full of loops, and harder to solve by eye
    than a perfect maze of the same size for exactly that reason. The number of independent loops
    is edges minus cells plus one for a connected region, which is the standard count, and it is
    reported rather than hidden.

    COUNTED OVER THE REACHABLE REGION AND NOT OVER THE WHOLE SYMBOL, which is the difference
    between describing the maze and describing the noise. A QR symbol's data area is about half
    light modules scattered at random, so counting every light module with three open neighbours
    anywhere in the symbol reported 190 branch points for a maze with about forty. They were real
    junctions and almost none of them was in anything a person could walk to.
    """
    region = reachable(modules, allowed, start)
    branches = dead_ends = 0
    degree_total = 0
    for cell in region:
        open_ways = sum(1 for here in _neighbours(cell, allowed)
                        if here in region)
        degree_total += open_ways
        if open_ways >= 3:
            branches += 1
        elif open_ways <= 1:
            dead_ends += 1
    edges = degree_total // 2
    loops = edges - len(region) + 1 if region else 0
    return len(region), branches, dead_ends, loops


def carve(symbol: encode.Symbol, entrance: Optional[Cell] = None, exit_at: Optional[Cell] = None,
          branch_attempts: int = 400, seed: int = 0) -> Carving:
    """Open a route from entrance to exit, then spend what is left of the budget on branches."""
    import random

    modules = [row[:] for row in symbol.modules]
    allowed = largest_region(carvable(symbol.version))
    budget = Budget(symbol.version, symbol.layout)
    width = symbol.size

    # The two corners of the region that are furthest apart in the obvious sense, so the maze
    # crosses the symbol rather than cutting a corner off it.
    if entrance is None:
        entrance = min(allowed, key=lambda cell: (cell[0] + cell[1], cell))
    if exit_at is None:
        exit_at = max(allowed, key=lambda cell: (cell[0] + cell[1], cell))

    route = cheapest_path(modules, allowed, entrance, exit_at)
    if route is None:
        raise ValueError("there is no route through the data area at all, which should be "
                         "impossible for a symbol of this size")
    needed = [cell for cell in route if modules[cell[0]][cell[1]]]
    extra = budget.cost_of(needed)
    if extra is None:
        raise ValueError(
            f"the cheapest route from {entrance} to {exit_at} needs {len(needed)} flips and the "
            f"correction budget is {budget.per_block} corrupt codewords per block; a larger "
            f"version or a higher correction level would give more room")
    budget.spend(extra)
    flipped = []
    for cell in needed:
        modules[cell[0]][cell[1]] = False
        flipped.append(cell)

    # WHAT IS LEFT OF THE BUDGET GOES ON DEAD ENDS, because a single corridor is a corridor. Each
    # branch is a short cheapest path from a point on the route to somewhere else, taken only if
    # it fits in what remains. A branch that does not fit is counted and skipped rather than
    # trimmed to fit, so the report can say how much maze the budget actually bought.
    rng = random.Random(seed)
    open_cells = [cell for cell in route]
    refused = 0
    for _ in range(branch_attempts):
        if not open_cells:
            break
        start = rng.choice(open_cells)
        target = (start[0] + rng.randint(-6, 6), start[1] + rng.randint(-6, 6))
        if target not in allowed or target == start:
            continue
        branch = cheapest_path(modules, allowed, start, target)
        if branch is None:
            continue
        needed = [cell for cell in branch if modules[cell[0]][cell[1]]]
        if not needed:
            continue
        extra = budget.cost_of(needed)
        if extra is None:
            refused += 1
            continue
        budget.spend(extra)
        for cell in needed:
            modules[cell[0]][cell[1]] = False
            flipped.append(cell)
        open_cells.extend(branch)

    solution = solve(modules, allowed, entrance, exit_at) or []
    walkable, branches, dead_ends, loops = describe(modules, allowed, entrance)
    return Carving(modules=modules, flipped=flipped, entrance=entrance, exit=exit_at,
                   corrupted_per_block=budget.spent(), budget_per_block=budget.per_block,
                   blocks=budget.blocks, path=solution, branches=branches, dead_ends=dead_ends,
                   refused_branches=refused, walkable=walkable, loops=loops)
