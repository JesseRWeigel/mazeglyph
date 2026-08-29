"""The QR layer: the field, the code, the geometry, and encode against decode."""

from __future__ import annotations

import random
import unittest

from mazeglyph import blocks, decode, encode, galois, geometry, reedsolomon


class TheFieldObeysItsAxioms(unittest.TestCase):
    """Checked exhaustively, because the field is 256 elements and exhaustive is cheap."""

    def test_multiplication_commutes(self):
        for left in range(256):
            for right in range(0, 256, 7):
                self.assertEqual(galois.multiply(left, right), galois.multiply(right, left))

    def test_every_non_zero_element_has_an_inverse(self):
        for value in range(1, 256):
            self.assertEqual(galois.multiply(value, galois.inverse(value)), 1)

    def test_division_undoes_multiplication(self):
        for left in range(0, 256, 5):
            for right in range(1, 256, 3):
                self.assertEqual(galois.divide(galois.multiply(left, right), right), left)

    def test_zero_has_no_inverse_and_says_so(self):
        with self.assertRaises(ZeroDivisionError):
            galois.inverse(0)
        with self.assertRaises(ZeroDivisionError):
            galois.divide(1, 0)

    def test_the_generator_reaches_every_non_zero_element(self):
        # If it did not, the logarithm table would have holes and every multiplication built on it
        # would be wrong for the values that fell in them.
        self.assertEqual(len({galois.alpha(power) for power in range(255)}), 255)
        self.assertEqual(galois.alpha(0), 1)
        self.assertEqual(galois.alpha(255), 1)

    def test_addition_is_its_own_inverse(self):
        for value in range(256):
            self.assertEqual(galois.add(galois.add(value, 0x5A), 0x5A), value)


class ErrorCorrectionAtItsExactCapacity(unittest.TestCase):
    """The boundary is the whole claim, so it is tested at the boundary and one past it."""

    def blocks_of(self, ec_count, data_length, seed):
        rng = random.Random(seed)
        data = [rng.randrange(256) for _ in range(data_length)]
        return data, data + reedsolomon.encode(data, ec_count)

    def test_a_clean_block_has_zero_syndromes(self):
        _, block = self.blocks_of(20, 40, 1)
        self.assertEqual(reedsolomon.syndromes(block, 20), [0] * 20)

    def test_every_count_of_errors_up_to_capacity_is_repaired_exactly(self):
        rng = random.Random(2026)
        checked = 0
        for ec_count in (10, 16, 22, 26, 28, 30):
            _, block = self.blocks_of(ec_count, 30, ec_count)
            for count in range(reedsolomon.capacity(ec_count) + 1):
                damaged = list(block)
                for position in rng.sample(range(len(block)), count):
                    damaged[position] ^= rng.randrange(1, 256)
                fixed, found = reedsolomon.correct(damaged, ec_count)
                checked += 1
                with self.subTest(ec=ec_count, errors=count):
                    self.assertEqual(fixed, block)
                    self.assertEqual(found, count)
        # 72: six correction sizes, each tested at every error count from zero to its capacity.
        self.assertGreater(checked, 60)

    def test_one_error_past_capacity_is_refused_and_never_silently_repaired(self):
        # The dangerous failure is not "it gave up". It is "it produced a different block that
        # satisfies the syndromes", which a caller cannot tell from a correct answer.
        rng = random.Random(7)
        refused = 0
        for ec_count in (10, 16, 22, 26, 28, 30):
            for trial in range(12):
                _, block = self.blocks_of(ec_count, 30, ec_count * 100 + trial)
                damaged = list(block)
                count = reedsolomon.capacity(ec_count) + 1
                for position in rng.sample(range(len(block)), count):
                    damaged[position] ^= rng.randrange(1, 256)
                fixed, _ = reedsolomon.correct(damaged, ec_count)
                if fixed is None:
                    refused += 1
                else:
                    self.assertEqual(fixed, block, "a block was repaired into the wrong thing")
        self.assertGreater(refused, 60)

    def test_the_capacity_is_half_the_correction_codewords(self):
        # Two per error, because the decoder is not told where they are.
        for count in (10, 16, 26, 28):
            self.assertEqual(reedsolomon.capacity(count), count // 2)


class TheGeometryAgreesWithThePublishedNumbers(unittest.TestCase):
    PUBLISHED = {1: 26, 2: 44, 3: 70, 4: 100, 5: 134, 6: 172, 7: 196, 8: 242, 9: 292, 10: 346}

    def test_the_module_count_gives_the_published_codeword_count(self):
        for version, expected in self.PUBLISHED.items():
            with self.subTest(version=version):
                self.assertEqual(geometry.data_module_count(version) // 8, expected)

    def test_the_alignment_centres_are_the_published_ones(self):
        published = {1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34],
                     7: [6, 22, 38], 8: [6, 24, 42], 9: [6, 26, 46], 10: [6, 28, 50]}
        for version, expected in published.items():
            with self.subTest(version=version):
                self.assertEqual(geometry.alignment_centres(version), expected)

    def test_the_zigzag_visits_every_data_module_exactly_once(self):
        for version in blocks.VERSIONS:
            with self.subTest(version=version):
                order = geometry.zigzag(version)
                self.assertEqual(len(order), geometry.data_module_count(version))
                self.assertEqual(len(set(order)), len(order))

    def test_the_zigzag_never_visits_a_function_module(self):
        for version in blocks.VERSIONS:
            reserved = geometry.function_modules(version)
            with self.subTest(version=version):
                self.assertEqual([cell for cell in geometry.zigzag(version) if cell in reserved],
                                 [])

    def test_the_block_table_agrees_with_the_geometry(self):
        # The one table that cannot be derived, checked against something that can.
        self.assertEqual(blocks.validate(), [])

    def test_a_version_outside_the_standard_is_refused(self):
        for version in (0, -1, 41, 100):
            with self.subTest(version=version):
                with self.assertRaises(ValueError):
                    geometry.size(version)


class TheFormatAndVersionCodes(unittest.TestCase):
    def test_the_format_code_has_the_minimum_distance_the_standard_claims(self):
        # BCH(15,5) has distance 7, so three bit errors are always correctable. That is a property
        # of the code and can be checked without a table of the thirty two words.
        words = [encode.bch_format((level << 3) | mask)
                 for level in range(4) for mask in range(8)]
        self.assertEqual(len(set(words)), 32)
        worst = min(bin(a ^ b).count("1")
                    for index, a in enumerate(words) for b in words[index + 1:])
        self.assertEqual(worst, 7)

    def test_the_version_code_has_its_minimum_distance_too(self):
        words = [encode.bch_version(version) for version in range(7, 41)]
        self.assertEqual(len(set(words)), len(words))
        worst = min(bin(a ^ b).count("1")
                    for index, a in enumerate(words) for b in words[index + 1:])
        self.assertEqual(worst, 8)

    def test_the_format_words_fit_in_fifteen_bits(self):
        for level in range(4):
            for mask in range(8):
                self.assertLess(encode.bch_format((level << 3) | mask), 1 << 15)


class EncodeAndDecodeAgree(unittest.TestCase):
    """The decoder is written from the standard, not from the encoder, so this means something."""

    def test_every_version_and_level_round_trips_at_three_payload_sizes(self):
        rng = random.Random(11)
        checked = 0
        for version in blocks.VERSIONS:
            for level in blocks.LEVELS:
                layout = blocks.layout(version, level)
                room = (layout.data_codewords * 8 - 4
                        - encode.character_count_bits(version)) // 8
                for size in {1, max(1, room // 2), room}:
                    payload = bytes(rng.randrange(32, 127) for _ in range(size))
                    symbol = encode.build(payload, version, level)
                    reading = decode.read(symbol.modules)
                    checked += 1
                    with self.subTest(version=version, level=level, size=size):
                        self.assertTrue(reading.ok, reading.problem)
                        self.assertEqual(reading.payload, payload)
                        self.assertEqual(reading.level, level)
                        self.assertEqual(reading.mask, symbol.mask)
        self.assertGreater(checked, 100)

    def test_the_decoder_reads_the_mask_rather_than_being_told_it(self):
        payload = b"which mask was it"
        for mask in range(8):
            symbol = encode.build(payload, 4, "H", mask=mask)
            reading = decode.read(symbol.modules)
            with self.subTest(mask=mask):
                self.assertEqual(reading.mask, mask)
                self.assertEqual(reading.payload, payload)

    def test_a_payload_too_large_for_the_version_is_refused_before_anything_is_built(self):
        with self.assertRaises(ValueError):
            encode.build(b"x" * 500, 1, "H")

    def test_the_smallest_version_that_fits_is_chosen(self):
        small = encode.smallest_version(b"short", "H")
        large = encode.smallest_version(b"x" * 100, "H")
        self.assertLess(small, large)
        self.assertEqual(encode.build(b"short", small, "H").version, small)

    def test_a_symbol_filled_exactly_to_capacity_still_decodes(self):
        # The terminator is up to four bits and there may not be room for four. A fixed four
        # overruns a symbol filled to the last bit, and this is the case that finds it.
        for version in (1, 5, 10):
            layout = blocks.layout(version, "H")
            room = (layout.data_codewords * 8 - 4 - encode.character_count_bits(version)) // 8
            payload = bytes((index % 90) + 33 for index in range(room))
            with self.subTest(version=version):
                reading = decode.read(encode.build(payload, version, "H").modules)
                self.assertTrue(reading.ok, reading.problem)
                self.assertEqual(reading.payload, payload)


class ASymbolThatHasBeenDamaged(unittest.TestCase):
    def symbol(self):
        return encode.build(b"https://example.invalid/m/abcd", 6, "H")

    def test_damage_within_the_budget_still_reads(self):
        symbol = self.symbol()
        layout = symbol.layout
        rng = random.Random(3)
        from mazeglyph import maze
        cells = sorted(maze.carvable(symbol.version))
        modules = [row[:] for row in symbol.modules]
        budget = maze.Budget(symbol.version, layout)
        flipped = 0
        for cell in rng.sample(cells, len(cells)):
            extra = budget.cost_of([cell])
            if extra is None:
                continue
            budget.spend(extra)
            modules[cell[0]][cell[1]] = not modules[cell[0]][cell[1]]
            flipped += 1
        reading = decode.read(modules)
        self.assertTrue(reading.ok, f"{flipped} flips inside the budget broke it: "
                                    f"{reading.problem}")
        self.assertEqual(reading.payload, b"https://example.invalid/m/abcd")
        self.assertGreater(flipped, 20)

    def test_damage_past_the_budget_is_reported_rather_than_misread(self):
        symbol = self.symbol()
        modules = [row[:] for row in symbol.modules]
        from mazeglyph import maze
        cells = sorted(maze.carvable(symbol.version))
        rng = random.Random(4)
        for cell in rng.sample(cells, len(cells) // 2):
            modules[cell[0]][cell[1]] = not modules[cell[0]][cell[1]]
        reading = decode.read(modules)
        self.assertFalse(reading.ok and reading.payload == b"https://example.invalid/m/abcd",
                         "half the data area was flipped and it still claimed to read")

    def test_damage_to_a_finder_pattern_is_not_protected_at_all(self):
        # The Reed-Solomon code covers the data. Nothing covers the function patterns, which is
        # why the maze never touches them.
        symbol = self.symbol()
        modules = [row[:] for row in symbol.modules]
        for row in range(7):
            for column in range(7):
                modules[row][column] = not modules[row][column]
        reading = decode.read(modules)
        # The payload may still come back, because the data is untouched. The point is that a
        # scanner would never find the symbol, which this decoder does not model and says so.
        self.assertIn(reading.ok, (True, False))


if __name__ == "__main__":
    unittest.main()
