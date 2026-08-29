"""Facts about the symbol's shape, checked directly rather than through a round trip.

WHY THIS FILE HAD TO EXIST. The encoder and the decoder share the geometry, the mask table and the
format code. A change to any of those is applied to both, they agree with each other, and the round
trip that is supposed to be an independent check sees nothing at all. That is a real limit on how
independent a decoder written in the same repository can be, and the answer is to check the SHAPE
of the symbol against the standard rather than against the other half of the program.

It is not a theoretical worry. The second copy of the format information was being written as eight
bits up the left edge and seven along the top, where the standard says seven and eight. The extra
bit landed on the module that is always dark, the decoder read the same displaced positions back,
every payload round tripped perfectly, and no real scanner would have read the symbol.
"""

from __future__ import annotations

import unittest

from mazeglyph import blocks, cli, decode, encode, geometry, maze, svg


class TheZigzagIsTheStandardsOrder(unittest.TestCase):
    def test_it_starts_at_the_bottom_right(self):
        for version in (1, 5, 10):
            with self.subTest(version=version):
                width = geometry.size(version)
                self.assertEqual(geometry.zigzag(version)[0], (width - 1, width - 1))

    def test_within_a_column_pair_the_right_module_comes_first(self):
        order = geometry.zigzag(6)
        steps = [(before, after) for before, after in zip(order, order[1:])
                 if before[0] == after[0]]
        rightward = [1 for before, after in steps if after[1] == before[1] - 1]
        leftward = [1 for before, after in steps if after[1] == before[1] + 1]
        self.assertGreater(len(rightward), 100)
        self.assertEqual(leftward, [], "the order steps from a left module to the right one")

    def test_consecutive_column_pairs_run_in_opposite_directions(self):
        order = geometry.zigzag(8)
        by_pair = {}
        for row, column in order:
            pair = column // 2 if column < 6 else (column + 1) // 2
            by_pair.setdefault(pair, []).append(row)
        directions = ["up" if by_pair[pair][0] > by_pair[pair][-1] else "down"
                      for pair in sorted(by_pair, reverse=True)]
        self.assertGreater(len(directions), 5)
        for before, after in zip(directions, directions[1:]):
            self.assertNotEqual(before, after, f"two column pairs run the same way: {directions}")

    def test_it_never_enters_the_vertical_timing_pattern(self):
        for version in blocks.VERSIONS:
            with self.subTest(version=version):
                self.assertEqual([cell for cell in geometry.zigzag(version) if cell[1] == 6], [])


class TheFunctionPatternsAreWhereTheStandardPutsThem(unittest.TestCase):
    def symbol(self, version=6):
        return encode.build(b"https://example.invalid/m/x", version, "H")

    def test_the_timing_patterns_alternate_and_start_dark_on_an_even_coordinate(self):
        for version in (1, 6, 10):
            symbol = self.symbol(version) if version != 1 else encode.build(b"maze", 1, "H")
            width = symbol.size
            with self.subTest(version=version):
                for index in range(8, width - 8):
                    self.assertEqual(symbol.modules[6][index], index % 2 == 0,
                                     f"the timing row is wrong at column {index}")
                    self.assertEqual(symbol.modules[index][6], index % 2 == 0,
                                     f"the timing column is wrong at row {index}")

    def test_the_module_that_is_always_dark_is_dark(self):
        # It was not, for a while, because the second copy of the format information was one bit
        # too long and wrote over it. Nothing that reads the data would notice, and a scanner
        # would.
        for version in blocks.VERSIONS:
            for level in blocks.LEVELS:
                layout = blocks.layout(version, level)
                room = (layout.data_codewords * 8 - 4
                        - encode.character_count_bits(version)) // 8
                payload = bytes(65 for _ in range(min(room, 4)))
                symbol = encode.build(payload, version, level)
                with self.subTest(version=version, level=level):
                    self.assertIs(symbol.modules[symbol.size - 8][8], True)

    def test_the_finder_patterns_are_three_rings(self):
        symbol = self.symbol()
        width = symbol.size
        for top, left in ((0, 0), (0, width - 7), (width - 7, 0)):
            with self.subTest(corner=(top, left)):
                self.assertIs(symbol.modules[top + 3][left + 3], True, "the centre is light")
                self.assertIs(symbol.modules[top + 2][left + 2], True)
                self.assertIs(symbol.modules[top + 1][left + 1], False, "the inner ring is dark")
                self.assertIs(symbol.modules[top][left], True, "the outer ring is light")

    def test_the_separator_around_each_finder_is_light(self):
        symbol = self.symbol()
        for index in range(8):
            self.assertIs(symbol.modules[7][index], False)
            self.assertIs(symbol.modules[index][7], False)


class TheFormatInformation(unittest.TestCase):
    def test_the_published_word_for_level_M_and_mask_zero(self):
        # The mask constant cannot be derived and masking cannot change the distance between
        # words, so the minimum distance check would not notice a wrong one. This would.
        self.assertEqual(encode.bch_format((encode.LEVEL_BITS["M"] << 3) | 0),
                         0b101010000010010)

    def test_masking_stops_an_all_zero_format_being_all_light(self):
        self.assertNotEqual(encode.bch_format(0), 0)

    def test_the_second_copy_is_seven_bits_and_then_eight(self):
        # Seven up the left edge from the bottom, eight along the top right. Eight and seven
        # reaches the module that is always dark.
        symbol = encode.build(b"maze", 4, "H")
        width = symbol.size
        left_edge = {(width - 1 - index, 8) for index in range(7)}
        self.assertNotIn((width - 8, 8), left_edge)
        self.assertIs(symbol.modules[width - 8][8], True)

    def test_every_complement_of_a_valid_format_word_is_also_valid(self):
        # A property of the code and the reason the two copies are read separately: a copy whose
        # every module has been inverted is at distance zero from a valid word naming the wrong
        # level and the wrong mask.
        words = {encode.bch_format((level << 3) | mask)
                 for level in range(4) for mask in range(8)}
        complements = {word ^ 0b111111111111111 for word in words}
        self.assertEqual(complements, words)

    def test_one_copy_inverted_does_not_produce_a_confident_wrong_reading(self):
        symbol = encode.build(b"https://example.invalid/m/x", 6, "H")
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
        found, _ = decode.read_format(modules)
        self.assertNotEqual(found, ("L", 7),
                            "the inverted copy was taken as a confident reading")

    def test_three_bits_of_damage_are_repaired(self):
        symbol = encode.build(b"https://example.invalid/m/x", 6, "H")
        modules = [row[:] for row in symbol.modules]
        for index in (0, 1, 2):
            modules[8][index] = not modules[8][index]
        reading = decode.read(modules)
        self.assertTrue(reading.ok, reading.problem)
        self.assertEqual(reading.mask, symbol.mask)


class ThePaddingAndTheMask(unittest.TestCase):
    def test_the_two_pad_bytes_alternate(self):
        # 0xEC and 0x11, alternating, which is what the standard says. One repeated byte would
        # make a large blank region a scanner has to work harder on.
        layout = blocks.layout(10, "H")
        words = encode.to_codewords(encode.to_bits(b"x", 10, layout))
        tail = words[4:12]
        self.assertEqual(set(tail), {0xEC, 0x11})
        for index in range(len(tail) - 1):
            self.assertNotEqual(tail[index], tail[index + 1])

    def test_the_mask_with_the_lowest_penalty_is_the_one_used(self):
        payload = b"https://example.invalid/m/penalty"
        symbol = encode.build(payload, 6, "H")
        scores = {}
        for mask in range(8):
            scores[mask] = encode.penalty(encode.build(payload, 6, "H", mask=mask).modules)
        self.assertEqual(symbol.mask, min(scores, key=lambda mask: (scores[mask], mask)))

    def test_the_penalty_punishes_a_finder_like_run(self):
        # Rule three exists so that nothing inside the data looks like a finder pattern to a
        # scanner hunting for one. Asked of that rule alone, because the four rules interact: in a
        # blank grid, planting this pattern breaks long runs and the TOTAL goes down while rule
        # three goes up.
        width = 21
        clean = [[False] * width for _ in range(width)]
        planted = [row[:] for row in clean]
        for index, value in enumerate([True, False, True, True, True, False, True] +
                                      [False] * 4):
            planted[10][index] = value
        self.assertEqual(encode.penalty_parts(clean)["finder_like"], 0)
        self.assertGreaterEqual(encode.penalty_parts(planted)["finder_like"], 40)

    def test_the_penalty_punishes_a_long_run_of_one_colour(self):
        width = 21
        # A TRUE checkerboard. `column % 2` makes every column a constant run of 21 modules, so
        # the "clean" grid scores 399 on the run rule and a planted run scores less than it.
        clean = [[(row + column) % 2 == 0 for column in range(width)] for row in range(width)]
        run = [row[:] for row in clean]
        for index in range(width):
            run[5][index] = True
        self.assertGreater(encode.penalty_parts(run)["runs"],
                           encode.penalty_parts(clean)["runs"])

    def test_the_penalty_punishes_a_block_of_one_colour(self):
        width = 21
        # A TRUE checkerboard. `column % 2` makes every column a constant run of 21 modules, so
        # the "clean" grid scores 399 on the run rule and a planted run scores less than it.
        clean = [[(row + column) % 2 == 0 for column in range(width)] for row in range(width)]
        blocky = [row[:] for row in clean]
        for row in range(4, 8):
            for column in range(4, 8):
                blocky[row][column] = True
        self.assertGreater(encode.penalty_parts(blocky)["squares"],
                           encode.penalty_parts(clean)["squares"])

    def test_the_penalty_punishes_being_far_from_half_dark(self):
        width = 21
        even = [[(row + column) % 2 == 0 for column in range(width)] for row in range(width)]
        alldark = [[True] * width for _ in range(width)]
        self.assertGreater(encode.penalty_parts(alldark)["balance"],
                           encode.penalty_parts(even)["balance"])


class TheReportedNumbersAreTheRealOnes(unittest.TestCase):
    def test_branches_refused_for_want_of_budget_are_counted(self):
        # A carver that dropped this number would look like one that never runs out.
        symbol = encode.build(b"https://example.invalid/m/x", 6, "H")
        carving = maze.carve(symbol, seed=7, branch_attempts=400)
        self.assertGreater(carving.refused_branches, 0,
                           "the budget was never exhausted, so this fixture proves nothing")
        self.assertEqual(carving.worst_block, carving.budget_per_block)

    def test_the_quiet_zone_default_is_four_modules(self):
        self.assertEqual(svg.QUIET_ZONE, 4)
        symbol = encode.build(b"maze", 1, "H")
        text = svg.render(symbol.modules, scale=1)
        width = int(text.split('width="')[1].split('"')[0])
        self.assertEqual(width, symbol.size + 8)

    def test_the_declared_length_is_checked_against_what_is_left(self):
        # A header claiming more bytes than the symbol holds must be refused, not read past the
        # end of the data.
        payload, reason = decode.parse_payload([0x4F, 0xFF] + [0] * 5, 1)
        self.assertIsNone(payload)
        self.assertIn("only", reason)

    def test_a_mode_this_program_does_not_write_is_refused(self):
        payload, reason = decode.parse_payload([0x10, 0x00, 0x00], 1)
        self.assertIsNone(payload)
        self.assertIn("byte mode", reason)


class BothCopiesOfTheFormatAreUsed(unittest.TestCase):
    """The standard writes it twice, and the second copy has to be able to carry the reading."""

    def symbol(self):
        return encode.build(b"https://example.invalid/m/x", 6, "H")

    def wreck_first_copy(self, modules):
        for index in range(15):
            if index < 6:
                modules[8][index] = True
            elif index == 6:
                modules[8][7] = True
            elif index == 7:
                modules[8][8] = True
            elif index == 8:
                modules[7][8] = True
            else:
                modules[14 - index][8] = True

    def test_the_second_copy_carries_the_reading_when_the_first_is_destroyed(self):
        symbol = self.symbol()
        modules = [row[:] for row in symbol.modules]
        self.wreck_first_copy(modules)
        reading = decode.read(modules)
        self.assertTrue(reading.ok, reading.problem)
        self.assertEqual(reading.mask, symbol.mask)
        self.assertEqual(reading.level, "H")

    def test_the_first_copy_alone_would_not_have_read_it(self):
        # The control. Without it, a decoder that ignored both copies and guessed would pass.
        symbol = self.symbol()
        modules = [row[:] for row in symbol.modules]
        self.wreck_first_copy(modules)
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
        value = sum(1 << index for index, bit in enumerate(first) if bit)
        words = {encode.bch_format((level << 3) | mask): (level, mask)
                 for level in range(4) for mask in range(8)}
        closest = min((bin(value ^ word).count("1"), level, mask)
                      for word, (level, mask) in words.items())
        self.assertNotEqual((encode.BITS_LEVEL[closest[1]], closest[2]), ("H", symbol.mask),
                            "the wrecked copy still reads correctly, so this fixture is not "
                            "testing what it claims")

    def test_a_format_too_damaged_to_resolve_is_refused_rather_than_guessed(self):
        # The code has a minimum distance of seven, so up to three bit errors are unambiguous and
        # four could sit exactly between two words. Accepting anything closer than fifteen bits
        # means accepting every possible reading, including the wrong one.
        symbol = self.symbol()
        modules = [row[:] for row in symbol.modules]
        width = symbol.size
        for index in range(9):
            modules[8][index] = True
            modules[index][8] = True
        for index in range(8):
            modules[8][width - 1 - index] = True
            modules[width - 1 - index][8] = True
        reading = decode.read(modules)
        self.assertFalse(reading.ok)
        self.assertIn("format", reading.problem)
        self.assertGreater(reading.format_bit_errors, 3)

    def test_a_format_within_three_bits_is_still_accepted(self):
        # The pair. A decoder that refused everything would pass the case above.
        symbol = self.symbol()
        modules = [row[:] for row in symbol.modules]
        for index in (0, 1, 2):
            modules[8][index] = not modules[8][index]
            modules[symbol.size - 1 - index][8] = not modules[symbol.size - 1 - index][8]
        reading = decode.read(modules)
        self.assertTrue(reading.ok, reading.problem)

    def test_two_copies_that_disagree_at_the_same_distance_are_refused(self):
        # Every complement of a valid word is valid, so an inverted copy is a confident wrong
        # answer. When both copies are equally confident and disagree, the symbol does not say
        # which is right.
        symbol = self.symbol()
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
        found, distance = decode.read_format(modules)
        self.assertIsNone(found, f"an ambiguous format was resolved to {found}")


class TheRunChecksItsOwnWork(unittest.TestCase):
    """The gate that separates "I made a maze" from "I made a maze that still scans"."""

    def setUp(self):
        self.payload = b"https://example.invalid/m/x"
        symbol = encode.build(self.payload, 6, "H")
        self.carving = maze.carve(symbol, seed=7)
        self.reading = decode.read(self.carving.modules)

    def test_a_good_carving_passes(self):
        self.assertTrue(cli.is_good(self.reading, self.payload, True))

    def test_an_unsolvable_maze_fails_even_though_the_symbol_reads(self):
        self.assertFalse(cli.is_good(self.reading, self.payload, False))

    def test_a_symbol_that_says_something_else_fails_even_though_it_reads(self):
        self.assertFalse(cli.is_good(self.reading, b"a different url", True))

    def test_a_symbol_that_does_not_read_fails(self):
        ruined = [row[:] for row in self.carving.modules]
        for cell in sorted(maze.carvable(6))[:400]:
            ruined[cell[0]][cell[1]] = not ruined[cell[0]][cell[1]]
        self.assertFalse(cli.is_good(decode.read(ruined), self.payload, True))


class TheAlignmentRuleStopsWhereItIsChecked(unittest.TestCase):
    def test_it_matches_the_published_centres_where_it_claims_to(self):
        published = {2: [6, 18], 7: [6, 22, 38], 10: [6, 28, 50], 13: [6, 34, 62],
                     14: [6, 26, 46, 66], 20: [6, 34, 62, 90]}
        for version, expected in published.items():
            with self.subTest(version=version):
                self.assertEqual(geometry.alignment_centres(version), expected)

    def test_it_refuses_above_the_version_it_has_been_checked_to(self):
        # The rule disagrees with the standard at versions 32 and 39. Refusing is better than
        # answering plausibly and wrongly.
        for version in (geometry.HIGHEST_VERIFIED_VERSION + 1, 32, 39, 40):
            with self.subTest(version=version):
                with self.assertRaises(ValueError):
                    geometry.alignment_centres(version)

    def test_the_step_is_rounded_up_to_an_even_number(self):
        # Version 14 is where the rounding first changes the answer: the plain division gives 20
        # and the centres are twenty modules apart only if it is rounded to an even step.
        for version in range(2, geometry.HIGHEST_VERIFIED_VERSION + 1):
            centres = geometry.alignment_centres(version)
            with self.subTest(version=version):
                self.assertTrue(all(centre % 2 == 0 for centre in centres),
                                f"an alignment centre is on an odd coordinate: {centres}")


if __name__ == "__main__":
    unittest.main()
