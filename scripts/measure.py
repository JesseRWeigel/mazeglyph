"""Everything this project decides, printed as data, with a sha256 of it on stderr.

NOTHING HERE VARIES BETWEEN RUNS OR BETWEEN MACHINES. Every maze is seeded, every payload is
written out here, and no time, path or process id appears anywhere. A copy of this tree in a
differently named directory has to produce the same number, which `scripts/sabotage.py` checks
before it trusts a single result.
"""

from __future__ import annotations

import hashlib
import io
import json
import pathlib
import random
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from mazeglyph import (blocks, cli, decode, encode, galois, geometry,  # noqa: E402
                       maze, reedsolomon, svg)

URL = "https://example.invalid/m/7f3a"


def the_field() -> dict:
    """That GF(256) is a field, stated as counts rather than as a claim."""
    inverses = sum(1 for value in range(1, 256)
                   if galois.multiply(value, galois.inverse(value)) == 1)
    commutes = sum(1 for a in range(0, 256, 3) for b in range(0, 256, 5)
                   if galois.multiply(a, b) == galois.multiply(b, a))
    divides = sum(1 for a in range(0, 256, 3) for b in range(1, 256, 5)
                  if galois.divide(galois.multiply(a, b), b) == a)
    return {"primitive_polynomial": f"{galois.PRIMITIVE:#x}",
            "non_zero_elements_with_an_inverse": inverses,
            "pairs_that_commute_of_those_tried": commutes,
            "pairs_where_division_undoes_multiplication": divides,
            "distinct_powers_of_the_generator": len({galois.alpha(p) for p in range(255)}),
            "generator_returns_to_one_after": next(p for p in range(1, 256)
                                                   if galois.alpha(p) == 1)}


def error_correction_boundary() -> dict:
    """Recovery at every error count from none up to capacity, and one past it.

    THE BOUNDARY IS THE CLAIM THE WHOLE PROJECT RESTS ON, because the carving budget is exactly
    this number. A decoder that quietly repaired one error too many would let the carver overspend
    and produce something no scanner could read.
    """
    rng = random.Random(4242)
    out = {}
    for ec_count in (10, 16, 22, 26, 28, 30):
        data = [rng.randrange(256) for _ in range(30)]
        block = data + reedsolomon.encode(data, ec_count)
        capacity = reedsolomon.capacity(ec_count)
        recovered = {}
        for count in range(capacity + 2):
            damaged = list(block)
            for position in rng.sample(range(len(block)), min(count, len(block))):
                damaged[position] ^= rng.randrange(1, 256)
            fixed, found = reedsolomon.correct(damaged, ec_count)
            recovered[f"{count} errors"] = {
                "recovered": fixed == block,
                "refused": fixed is None,
                "reported_error_count": found,
            }
        out[f"{ec_count} correction codewords"] = {"capacity": capacity, "trials": recovered}
    return out


def the_geometry() -> dict:
    """Sizes, alignment centres, module counts and the block table, all against each other."""
    rows = {}
    for version in blocks.VERSIONS:
        rows[f"version {version}"] = {
            "size": geometry.size(version),
            "alignment_centres": geometry.alignment_centres(version),
            "function_modules": len(geometry.function_modules(version)),
            "data_modules": geometry.data_module_count(version),
            "codewords": geometry.data_module_count(version) // 8,
            "remainder_bits": geometry.remainder_bits(version),
            "zigzag_covers_every_data_module_once":
                len(set(geometry.zigzag(version))) == geometry.data_module_count(version),
        }
    return {"per_version": rows, "block_table_disagreements": blocks.validate()}


def the_codes() -> dict:
    """The two BCH codes, described by properties rather than by their tables."""
    format_words = [encode.bch_format((level << 3) | mask)
                    for level in range(4) for mask in range(8)]
    version_words = [encode.bch_version(version) for version in range(7, 41)]

    def distance(words):
        return min(bin(a ^ b).count("1")
                   for index, a in enumerate(words) for b in words[index + 1:])

    return {"format": {"words": len(format_words), "distinct": len(set(format_words)),
                       "minimum_distance": distance(format_words),
                       "all_fifteen_bits": all(word < 1 << 15 for word in format_words)},
            "version": {"words": len(version_words), "distinct": len(set(version_words)),
                        "minimum_distance": distance(version_words),
                        "all_eighteen_bits": all(word < 1 << 18 for word in version_words)}}


def encode_then_decode() -> dict:
    """Every version and level, at three payload sizes, through a decoder written separately."""
    rng = random.Random(99)
    rows = {}
    for version in blocks.VERSIONS:
        for level in blocks.LEVELS:
            layout = blocks.layout(version, level)
            room = (layout.data_codewords * 8 - 4 - encode.character_count_bits(version)) // 8
            sizes = sorted({1, max(1, room // 2), room})
            results = {}
            for size in sizes:
                payload = bytes((index * 7 + size) % 90 + 33 for index in range(size))
                symbol = encode.build(payload, version, level)
                reading = decode.read(symbol.modules)
                results[f"{size} bytes"] = {
                    "read_back": reading.ok and reading.payload == payload,
                    "level_read": reading.level,
                    "mask_read_matches_mask_used": reading.mask == symbol.mask,
                }
            rows[f"version {version} level {level}"] = {
                "layout": layout.as_dict(), "payloads": results}
    return rows


def carving_by_version() -> dict:
    """What a maze costs at each size, and whether the symbol survives it."""
    rows = {}
    for version in blocks.VERSIONS[3:]:
        symbol = encode.build(URL.encode(), version, "H")
        carving = maze.carve(symbol, seed=7)
        reading = decode.read(carving.modules)
        body = carving.as_dict()
        body["decodes"] = reading.ok
        body["decodes_to_the_url"] = reading.ok and reading.payload == URL.encode()
        body["codewords_the_decoder_had_to_correct"] = reading.corrected_codewords
        rows[f"version {version} level H"] = body
    return rows


def how_much_maze_the_budget_buys() -> dict:
    """The trade-off, which is the interesting result: more carving costs more budget.

    The row with no branch attempts is the finding worth stating: a QR symbol's data area is
    already about half light modules, so a handful of flips is all it takes to connect one corner
    to the other, and the maze that results is already full of junctions.
    """
    rows = {}
    symbol = encode.build(URL.encode(), 8, "H")
    for attempts in (0, 10, 40, 120, 400):
        carving = maze.carve(symbol, seed=7, branch_attempts=attempts)
        reading = decode.read(carving.modules)
        rows[f"{attempts} branch attempts"] = {
            "modules_flipped": len(carving.flipped),
            "corrupted_codewords": sum(carving.corrupted_per_block.values()),
            "worst_block": carving.worst_block,
            "budget_per_block": carving.budget_per_block,
            "walkable_cells": carving.walkable,
            "solution_length": len(carving.path),
            "branches": carving.branches,
            "dead_ends": carving.dead_ends,
            "independent_loops": carving.loops,
            "refused_for_want_of_budget": carving.refused_branches,
            "still_decodes": reading.ok and reading.payload == URL.encode(),
        }
    return rows


def what_the_carving_never_touches() -> dict:
    """That no function module changes, checked module by module rather than asserted."""
    rows = {}
    for version in (6, 8, 10):
        symbol = encode.build(URL.encode(), version, "H")
        carving = maze.carve(symbol, seed=3)
        reserved = geometry.function_modules(version)
        changed = [cell for cell in reserved
                   if carving.modules[cell[0]][cell[1]] != symbol.modules[cell[0]][cell[1]]]
        rows[f"version {version}"] = {
            "function_modules": len(reserved),
            "function_modules_changed": len(changed),
            "flips_inside_the_function_patterns":
                len([cell for cell in carving.flipped if cell in reserved]),
        }
    return rows


def the_stranded_strips() -> dict:
    """How much of the data area no maze can ever reach, and why."""
    rows = {}
    for version in blocks.VERSIONS:
        whole = maze.carvable(version)
        biggest = maze.largest_region(whole)
        stranded = whole - biggest
        rows[f"version {version}"] = {
            "carvable_modules": len(whole),
            "largest_connected_region": len(biggest),
            "stranded": len(stranded),
            "stranded_left_of_the_timing_column":
                len([cell for cell in stranded if cell[1] < 6]),
            "stranded_above_the_timing_row":
                len([cell for cell in stranded if cell[0] < 6]),
        }
    return rows


def command_line() -> dict:
    """Every documented invocation, its exit code and what it decided."""
    runs = {
        "an ordinary run": [URL, "--version", "6", "--json"],
        "the smallest version that fits": [URL, "--json"],
        "a bigger version": [URL, "--version", "10", "--json"],
        "a lower correction level": [URL, "--version", "8", "--level", "L", "--json"],
        "no branches at all": [URL, "--version", "8", "--branches", "0", "--json"],
        "a different seed": [URL, "--version", "8", "--seed", "5", "--json"],
        "too much text for the version": ["x" * 400, "--version", "1"],
        "too much text for any version": ["x" * 5000],
        "a negative branch count": [URL, "--version", "6", "--branches", "-1"],
        "a scale of zero": [URL, "--version", "6", "--scale", "0"],
    }
    out = {}
    for label, argv in runs.items():
        stdout, stderr = io.StringIO(), io.StringIO()
        code = cli.main(argv, stdout=stdout, stderr=stderr)
        body = {"argv": [a for a in argv if not a.startswith("http") and len(a) < 40],
                "exit_code": code}
        text = stdout.getvalue()
        if text.strip().startswith("{"):
            report = json.loads(text)
            for key in ("modules_flipped", "corrupted_codewords", "worst_block_corrupted",
                        "budget_per_block", "walkable_cells", "solution_length",
                        "independent_loops", "decodes_to_the_url", "maze_is_solvable",
                        "version", "level", "size"):
                body[key] = report.get(key)
        out[label] = body
    return out


def the_svg() -> dict:
    """That the file written is the symbol that was checked, read back out of the file."""
    symbol = encode.build(URL.encode(), 6, "H")
    carving = maze.carve(symbol, seed=7)
    plain = svg.render(carving.modules, scale=4)
    annotated = svg.render(carving.modules, scale=4, path=carving.path,
                           flipped=carving.flipped, entrance=carving.entrance,
                           exit_at=carving.exit, annotate=True)
    body = annotated.replace('xmlns="http://www.w3.org/2000/svg"', "")
    dark = sum(1 for row in carving.modules for value in row if value)
    return {
        "dark_modules_in_the_symbol": dark,
        "rectangles_in_the_plain_file": plain.count("h4v4h-4z"),
        "plain_file_reaches_for_the_network":
            any(token in plain.replace('xmlns="http://www.w3.org/2000/svg"', "")
                for token in ("http://", "https://", "<script", "@import", "<image", "url(")),
        "annotated_file_reaches_for_the_network":
            any(token in body for token in ("http://", "https://", "<script", "@import",
                                            "<image", "url(")),
        "annotated_file_says_it_is_not_scannable": "NOT SCANNABLE" in annotated,
    }


def the_zigzag_structure() -> dict:
    """What the placement order looks like, asked directly rather than through a round trip.

    THE ENCODER AND THE DECODER SHARE THIS FUNCTION, so a change to it is applied consistently to
    both and a round trip cannot see it. That is a real limit on how independent the decoder is,
    and the answer is to check the order's SHAPE here: where it starts, that it alternates
    direction, and that within each column pair the right module comes before the left. Those are
    properties of the standard, not of this implementation.
    """
    rows = {}
    for version in (1, 5, 7, 10):
        order = geometry.zigzag(version)
        width = geometry.size(version)
        # Which way each column pair runs, and whether the pairs alternate. Counting direction
        # changes between consecutive entries counted one, because within a column pair the row
        # only advances every other step and the first version of this looked at the wrong pairs.
        by_pair = {}
        for index, (row, column) in enumerate(order):
            pair = column // 2 if column < 6 else (column + 1) // 2
            by_pair.setdefault(pair, []).append(row)
        directions = []
        for pair in sorted(by_pair, reverse=True):
            rows_here = by_pair[pair]
            directions.append("up" if rows_here[0] > rows_here[-1] else "down")
        turns = sum(1 for a, b in zip(directions, directions[1:]) if a != b)
        # Within a pair the right module comes first, so the first two entries of any column pair
        # differ by one column with the larger column first.
        right_first = sum(1 for before, after in zip(order, order[1:])
                          if before[0] == after[0] and after[1] == before[1] - 1)
        rows[f"version {version}"] = {
            "first_module": list(order[0]),
            "starts_at_the_bottom_right": order[0] == (width - 1, width - 1),
            "modules": len(order),
            "column_pairs": len(directions),
            "direction_changes": turns,
            "every_pair_reverses_the_last": turns == len(directions) - 1,
            "steps_from_a_right_module_to_the_left_one_beside_it": right_first,
            "never_uses_column_six": all(cell[1] != 6 for cell in order),
        }
    return rows


def the_timing_and_the_dark_module() -> dict:
    """Structural facts a decoder that shares the encoder's tables cannot check by round trip."""
    rows = {}
    for version in (1, 6, 10):
        # A version 1 symbol at level H holds nine bytes, so the URL does not fit and a shorter
        # payload is used. The structural facts being checked here do not depend on the content.
        payload = b"maze" if version == 1 else URL.encode()
        symbol = encode.build(payload, version, "H")
        width = symbol.size
        horizontal = [symbol.modules[6][index] for index in range(8, width - 8)]
        vertical = [symbol.modules[index][6] for index in range(8, width - 8)]
        rows[f"version {version}"] = {
            # PARENTHESISED. `value == (8 + index) % 2 == 0` is a chained comparison in Python
            # and means `value == ((8+index) % 2) and ((8+index) % 2) == 0`, which is False for
            # every dark module and reported a correct timing pattern as broken.
            "timing_row_alternates": all(value == ((8 + index) % 2 == 0)
                                         for index, value in enumerate(horizontal)),
            "timing_column_alternates": all(value == ((8 + index) % 2 == 0)
                                            for index, value in enumerate(vertical)),
            "timing_row_starts_dark_at_an_even_coordinate": symbol.modules[6][8] is True,
            "the_module_that_is_always_dark_is_dark": symbol.modules[width - 8][8] is True,
            "finder_centre_is_dark": symbol.modules[3][3] is True,
            "separator_is_light": symbol.modules[7][7] is False,
        }
    return rows


def the_format_mask_constant() -> dict:
    """The one published constant this program cannot derive, checked against its consequences.

    Masking every format word by the same value cannot change the distance between them, so the
    minimum distance check elsewhere would not notice a wrong constant. What it does change is the
    words themselves, and the standard publishes the one for level M with mask 0.
    """
    return {
        "mask_constant": f"{encode.FORMAT_MASK:015b}",
        "level_M_mask_0": f"{encode.bch_format((encode.LEVEL_BITS['M'] << 3) | 0):015b}",
        "level_M_mask_0_is_the_published_word":
            encode.bch_format((encode.LEVEL_BITS["M"] << 3) | 0) == 0b101010000010010,
        "an_all_zero_format_does_not_produce_an_all_zero_word":
            encode.bch_format(0) != 0,
        "level_L_mask_0": f"{encode.bch_format((encode.LEVEL_BITS['L'] << 3) | 0):015b}",
    }


def the_padding() -> dict:
    """The two pad bytes, and the terminator on a symbol filled exactly to capacity."""
    rows = {}
    layout = blocks.layout(10, "H")
    short = b"x"
    bits = encode.to_bits(short, 10, layout)
    words = encode.to_codewords(bits)
    tail = words[3:11]
    rows["a nearly empty symbol"] = {
        "pad_bytes_seen": [f"{value:#04x}" for value in tail],
        "they_alternate": all(tail[index] != tail[index + 1] for index in range(len(tail) - 1)),
    }
    for version in (1, 5, 10):
        layout = blocks.layout(version, "H")
        room = (layout.data_codewords * 8 - 4 - encode.character_count_bits(version)) // 8
        payload = bytes((index % 90) + 33 for index in range(room))
        symbol = encode.build(payload, version, "H")
        reading = decode.read(symbol.modules)
        rows[f"version {version} filled to capacity"] = {
            "payload_bytes": room,
            "read_back": reading.ok and reading.payload == payload,
            "problem": reading.problem,
        }
    return rows


def a_damaged_format_and_a_ruined_block() -> dict:
    """The decoder's refusals, which nothing else in the measurement reaches."""
    symbol = encode.build(URL.encode(), 6, "H")
    out = {}

    # One copy of the format destroyed. The other must carry the reading.
    modules = [row[:] for row in symbol.modules]
    for index in range(15):
        if index < 6:
            modules[8][index] = not modules[8][index]
        elif index == 6:
            modules[8][7] = not modules[8][7]
        elif index == 7:
            modules[8][8] = not modules[8][8]
        elif index == 8:
            modules[7][8] = not modules[7][8]
        else:
            modules[14 - index][8] = not modules[14 - index][8]
    reading = decode.read(modules)
    out["one copy of the format destroyed"] = {
        "read": reading.ok, "level": reading.level, "mask": reading.mask,
        "format_bit_errors": reading.format_bit_errors}

    # Three bits of one copy flipped, which the BCH code can repair.
    modules = [row[:] for row in symbol.modules]
    for index in (0, 1, 2):
        modules[8][index] = not modules[8][index]
    reading = decode.read(modules)
    out["three bits of the format flipped"] = {
        "read": reading.ok, "format_bit_errors": reading.format_bit_errors}

    # Both copies destroyed beyond the code's reach.
    modules = [row[:] for row in symbol.modules]
    width = symbol.size
    for index in range(9):
        modules[8][index] = True
        modules[index][8] = True
    for index in range(8):
        modules[8][width - 1 - index] = True
        modules[width - 1 - index][8] = True
    reading = decode.read(modules)
    out["both copies of the format destroyed"] = {
        "read": reading.ok, "problem_mentions_the_format": "format" in reading.problem}

    # One block flooded past its capacity while the others are untouched.
    from mazeglyph import maze as maze_mod
    owner = maze_mod.module_owner(6, symbol.layout)
    modules = [row[:] for row in symbol.modules]
    ruined = 0
    for cell, block in sorted(owner.items()):
        if block == 0:
            modules[cell[0]][cell[1]] = not modules[cell[0]][cell[1]]
            ruined += 1
    reading = decode.read(modules)
    out["one block flooded"] = {
        "modules_flipped": ruined,
        "read": reading.ok,
        "blocks_beyond_repair": reading.blocks_beyond_repair,
        "problem_mentions_repair": "repair" in reading.problem}

    # A header claiming more bytes than the symbol holds.
    out["a length longer than the symbol"] = {
        "parsed": decode.parse_payload([0x4F, 0xFF] + [0] * 5, 1)[0] is not None,
        "reason": decode.parse_payload([0x4F, 0xFF] + [0] * 5, 1)[1]}
    return out


def the_alignment_table_for_every_version() -> dict:
    """All forty versions, so the rounding rule is exercised rather than only the first ten.

    Versions one to ten never need the step rounded up, so a measurement that stopped there could
    not tell the rule from a plain division. The published centres for the higher versions are the
    only thing that separates them.
    """
    published = {
        13: [6, 34, 62], 20: [6, 34, 62, 90],
        # Above the verified range, kept here to record WHY it stops: the rule gives
        # [6, 26, 54, 82, 110, 138] for version 32 and [6, 36, 62, ...] for version 39, and the
        # standard's table says otherwise for both.
        27: [6, 34, 62, 90, 118], 32: [6, 34, 60, 86, 112, 138],
        39: [6, 26, 54, 82, 110, 138, 166], 40: [6, 30, 58, 86, 114, 142, 170],
    }
    top = geometry.HIGHEST_VERIFIED_VERSION
    rows = {"every version this program will answer for":
                {str(version): geometry.alignment_centres(version)
                 for version in range(1, top + 1)},
            "highest_version_the_rule_is_checked_to": top}
    rows["against the published centres"] = {
        str(version): geometry.alignment_centres(version) == expected
        for version, expected in published.items() if version <= top}
    refused = {}
    for version in sorted(published):
        if version <= top:
            continue
        try:
            geometry.alignment_centres(version)
            refused[str(version)] = "answered"
        except ValueError:
            refused[str(version)] = "refused"
    rows["versions above the verified range"] = refused
    return rows


def the_command_line_checks_its_own_work() -> dict:
    """That a run which produced something unreadable would say so.

    Reached by asking the pieces directly, because the tool never produces one: if it did, this
    project would not work. What is recorded is that the check exists and what it decides.
    """
    symbol = encode.build(URL.encode(), 6, "H")
    carving = maze.carve(symbol, seed=7)
    reading = decode.read(carving.modules)
    ruined = [row[:] for row in carving.modules]
    for cell in sorted(maze.carvable(6))[:400]:
        ruined[cell[0]][cell[1]] = not ruined[cell[0]][cell[1]]
    ruined_reading = decode.read(ruined)
    return {
        "the_carving_decodes": reading.ok and reading.payload == URL.encode(),
        "a_ruined_symbol_does_not": not (ruined_reading.ok
                                         and ruined_reading.payload == URL.encode()),
        "the_carving_is_solvable": bool(carving.path),
        "an_empty_path_is_falsy": not bool([]),
    }


def the_default_quiet_zone() -> dict:
    """The quiet zone, taken from the default rather than passed in.

    A QR code printed hard against another mark is one a scanner will not find, and four modules
    is what the standard requires. Every other call in this file passes it explicitly, so without
    this row the default is never exercised.
    """
    symbol = encode.build(b"maze", 1, "H")
    text = svg.render(symbol.modules, scale=1)
    return {"default": svg.QUIET_ZONE,
            "symbol_modules": symbol.size,
            "svg_width_at_scale_one": symbol.size + svg.QUIET_ZONE * 2,
            "declared_width": int(text.split('width="')[1].split('"')[0])}


def which_polynomials_generate_the_field() -> dict:
    """Whether 2 generates the field for each candidate primitive polynomial.

    THE PROOF THAT ONE GUARD IS SILENT. `galois._build` refuses if the generator does not reach
    every element, and it cannot fire for the standard's polynomial or for the one a sabotage
    substitutes, because both are primitive. Recorded here so that a substitution which DID break
    it would move the fingerprint rather than passing unnoticed.
    """
    def generates(poly: int) -> bool:
        value = 1
        for _ in range(255):
            value <<= 1
            if value & 0x100:
                value ^= poly
        return value == 1

    return {f"{poly:#x}": generates(poly)
            for poly in (0x11D, 0x11B, 0x12B, 0x12D, 0x100, 0x101)}


def spare_bits_after_a_full_payload() -> dict:
    """How many bits are left over when a symbol is filled to the last whole byte.

    THE PROOF THAT ANOTHER GUARD IS SILENT. The terminator is up to four bits and fewer if there is
    no room. In byte mode the header is 12 or 20 bits and a codeword is 8, so the spare is always
    exactly four and the guard never binds. It stays because the modes this program does not
    implement have different header widths.
    """
    rows = {}
    seen = set()
    for version in blocks.VERSIONS:
        for level in blocks.LEVELS:
            layout = blocks.layout(version, level)
            capacity = layout.data_codewords * 8
            header = 4 + encode.character_count_bits(version)
            room = (capacity - header) // 8
            spare = capacity - (header + room * 8)
            seen.add(spare)
            rows[f"version {version} level {level}"] = spare
    return {"per_combination": rows, "distinct_values": sorted(seen),
            "the_guard_can_bind": min(seen) < 4}


def what_the_decoder_does_with_too_much_damage() -> dict:
    """Every error count from capacity to well past it, and what comes back.

    THE THREE OUTCOMES ARE DIFFERENT AND ONLY ONE IS ACCEPTABLE. Recovered means the original came
    back. Refused means the decoder said it could not. WRONG means it produced a different block
    and claimed success, which a caller cannot tell from the first, and no count of it above zero
    is tolerable.
    """
    rng = random.Random(31337)
    rows = {}
    for ec_count in (16, 26, 30):
        data = [rng.randrange(256) for _ in range(40)]
        block = data + reedsolomon.encode(data, ec_count)
        capacity = reedsolomon.capacity(ec_count)
        counts = {"recovered": 0, "refused": 0, "wrong": 0}
        detail = {}
        for extra in range(0, 12):
            errors = capacity + extra
            if errors > len(block):
                break
            here = {"recovered": 0, "refused": 0, "wrong": 0}
            for trial in range(12):
                damaged = list(block)
                for position in rng.sample(range(len(block)), errors):
                    damaged[position] ^= rng.randrange(1, 256)
                fixed, _ = reedsolomon.correct(damaged, ec_count)
                if fixed is None:
                    here["refused"] += 1
                elif fixed == block:
                    here["recovered"] += 1
                else:
                    here["wrong"] += 1
            for key in counts:
                counts[key] += here[key]
            detail[f"{errors} errors"] = here
        rows[f"{ec_count} correction codewords"] = {
            "capacity": capacity, "totals": counts, "by_error_count": detail}
    return rows


def the_run_checks_its_own_work() -> dict:
    """The command line's own gate, asked directly about symbols it would never produce."""
    symbol = encode.build(URL.encode(), 6, "H")
    carving = maze.carve(symbol, seed=7)
    good_reading = decode.read(carving.modules)

    ruined = [row[:] for row in carving.modules]
    for cell in sorted(maze.carvable(6))[:400]:
        ruined[cell[0]][cell[1]] = not ruined[cell[0]][cell[1]]
    ruined_reading = decode.read(ruined)

    other = decode.read(encode.build(b"something else entirely", 6, "H").modules)

    return {
        "a good carving passes": cli.is_good(good_reading, URL.encode(), True),
        "a ruined symbol fails": cli.is_good(ruined_reading, URL.encode(), True),
        "an unsolvable maze fails": cli.is_good(good_reading, URL.encode(), False),
        "a symbol saying something else fails": cli.is_good(other, URL.encode(), True),
    }


def main() -> int:
    report = {
        "a_damaged_format_and_a_ruined_block": a_damaged_format_and_a_ruined_block(),
        "carving_by_version": carving_by_version(),
        "the_alignment_table_for_every_version": the_alignment_table_for_every_version(),
        "the_command_line_checks_its_own_work": the_command_line_checks_its_own_work(),
        "the_default_quiet_zone": the_default_quiet_zone(),
        "the_format_mask_constant": the_format_mask_constant(),
        "the_padding": the_padding(),
        "the_timing_and_the_dark_module": the_timing_and_the_dark_module(),
        "the_run_checks_its_own_work": the_run_checks_its_own_work(),
        "the_zigzag_structure": the_zigzag_structure(),
        "spare_bits_after_a_full_payload": spare_bits_after_a_full_payload(),
        "what_the_decoder_does_with_too_much_damage": what_the_decoder_does_with_too_much_damage(),
        "which_polynomials_generate_the_field": which_polynomials_generate_the_field(),
        "command_line": command_line(),
        "encode_then_decode": encode_then_decode(),
        "error_correction_boundary": error_correction_boundary(),
        "how_much_maze_the_budget_buys": how_much_maze_the_budget_buys(),
        "the_codes": the_codes(),
        "the_field": the_field(),
        "the_geometry": the_geometry(),
        "the_stranded_strips": the_stranded_strips(),
        "the_svg": the_svg(),
        "what_the_carving_never_touches": what_the_carving_never_touches(),
    }
    text = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False)
    sys.stdout.write(text)
    print("FINGERPRINT " + hashlib.sha256(text.encode("utf-8")).hexdigest(), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
