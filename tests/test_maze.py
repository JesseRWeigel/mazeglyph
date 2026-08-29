"""The carving: what it costs, what it leaves, and whether the symbol still says what it said."""

from __future__ import annotations

import io
import json
import unittest

from mazeglyph import blocks, cli, decode, encode, geometry, maze, svg

URL = b"https://example.invalid/m/7f3a"


class TheDataAreaIsNotOnePiece(unittest.TestCase):
    """The fact that broke the first carver, kept as a test so it cannot come back."""

    def test_the_timing_patterns_wall_off_two_strips_of_the_data_area(self):
        # BOTH of them, which is the part that took a second look. The vertical timing pattern is a
        # whole column from top to bottom and strands the six columns to its left; the horizontal
        # one is a whole row and strands the six rows above it. For version 6 that is 144 modules
        # each, exactly symmetric, and neither can ever be part of a maze that crosses the symbol.
        for version in (6, 8, 10):
            with self.subTest(version=version):
                whole = maze.carvable(version)
                biggest = maze.largest_region(whole)
                self.assertLess(len(biggest), len(whole),
                                "the data area is one connected piece, so this test is measuring "
                                "nothing")
                stranded = whole - biggest
                left = {cell for cell in stranded if cell[1] < 6}
                above = {cell for cell in stranded if cell[0] < 6}
                self.assertEqual(stranded, left | above,
                                 "something is stranded that is neither left of the timing column "
                                 "nor above the timing row")
                self.assertTrue(left and above, "only one of the two strips is stranded")
                self.assertEqual(len(left), len(above),
                                 "the two strips should be the same size by symmetry")

    def test_the_endpoints_are_chosen_inside_one_region(self):
        for version in (6, 8, 10):
            symbol = encode.build(URL, version, "H")
            carving = maze.carve(symbol, seed=1)
            region = maze.largest_region(maze.carvable(version))
            with self.subTest(version=version):
                self.assertIn(carving.entrance, region)
                self.assertIn(carving.exit, region)


class TheCarvingStaysInsideItsBudget(unittest.TestCase):
    def test_no_block_is_damaged_past_its_capacity(self):
        for version in blocks.VERSIONS[3:]:
            symbol = encode.build(URL, version, "H")
            carving = maze.carve(symbol, seed=2)
            with self.subTest(version=version):
                for block, count in carving.corrupted_per_block.items():
                    self.assertLessEqual(count, carving.budget_per_block,
                                         f"block {block} of version {version}")

    def test_the_budget_is_counted_in_codewords_and_not_in_flips(self):
        # Eight flips inside one codeword cost one codeword. If the accounting counted flips, the
        # carver would give up long before the symbol did.
        symbol = encode.build(URL, 8, "H")
        carving = maze.carve(symbol, seed=2)
        total = sum(carving.corrupted_per_block.values())
        self.assertGreater(len(carving.flipped), total,
                           "every flip landed in its own codeword, so this fixture does not "
                           "demonstrate the distinction it is here for")

    def test_a_carved_symbol_still_decodes_to_what_it_encoded(self):
        for version in blocks.VERSIONS[3:]:
            for seed in (0, 5, 9):
                symbol = encode.build(URL, version, "H")
                carving = maze.carve(symbol, seed=seed)
                reading = decode.read(carving.modules)
                with self.subTest(version=version, seed=seed):
                    self.assertTrue(reading.ok, reading.problem)
                    self.assertEqual(reading.payload, URL)

    def test_no_function_module_is_ever_touched(self):
        # A scanner finds the symbol by these. Carving through them produces something that is not
        # a QR code at all, and no error correction covers them.
        for version in (6, 8, 10):
            symbol = encode.build(URL, version, "H")
            carving = maze.carve(symbol, seed=3)
            reserved = geometry.function_modules(version)
            with self.subTest(version=version):
                self.assertEqual([cell for cell in carving.flipped if cell in reserved], [])
                for row, column in reserved:
                    self.assertEqual(carving.modules[row][column],
                                     symbol.modules[row][column],
                                     f"a function module at {(row, column)} changed")

    def test_spending_more_of_the_budget_carves_more_maze(self):
        symbol = encode.build(URL, 8, "H")
        small = maze.carve(symbol, seed=4, branch_attempts=0)
        large = maze.carve(symbol, seed=4, branch_attempts=400)
        self.assertLess(len(small.flipped), len(large.flipped))
        self.assertLess(small.walkable, large.walkable)
        self.assertLessEqual(large.worst_block, large.budget_per_block)

    def test_the_symbol_is_almost_a_maze_before_anything_is_carved(self):
        # The finding the whole project rests on. A QR symbol's data area is about half light
        # modules, so most of a maze is already there and only a handful of flips are needed to
        # connect the two ends.
        symbol = encode.build(URL, 8, "H")
        carving = maze.carve(symbol, seed=4, branch_attempts=0)
        self.assertLess(len(carving.flipped), 30,
                        "connecting the two ends took more flips than the claim allows")
        self.assertGreater(carving.walkable, 200)


class TheMazeIsAMaze(unittest.TestCase):
    def test_there_is_a_route_from_the_entrance_to_the_exit(self):
        for version in (6, 8, 10):
            symbol = encode.build(URL, version, "H")
            carving = maze.carve(symbol, seed=6)
            with self.subTest(version=version):
                self.assertTrue(carving.path)
                self.assertEqual(carving.path[0], carving.entrance)
                self.assertEqual(carving.path[-1], carving.exit)

    def test_every_step_of_the_solution_is_a_light_module_next_to_the_last(self):
        symbol = encode.build(URL, 8, "H")
        carving = maze.carve(symbol, seed=6)
        for cell in carving.path:
            self.assertFalse(carving.modules[cell[0]][cell[1]],
                             f"the solution walks through a wall at {cell}")
        for before, after in zip(carving.path, carving.path[1:]):
            self.assertEqual(abs(before[0] - after[0]) + abs(before[1] - after[1]), 1,
                             f"the solution jumps from {before} to {after}")

    def test_the_solution_is_longer_than_the_straight_line_between_its_ends(self):
        # "Non-trivial" as a number rather than an opinion.
        symbol = encode.build(URL, 8, "H")
        carving = maze.carve(symbol, seed=6)
        straight = (abs(carving.entrance[0] - carving.exit[0])
                    + abs(carving.entrance[1] - carving.exit[1]))
        self.assertGreater(len(carving.path), straight)

    def test_it_has_junctions_and_dead_ends_rather_than_being_a_corridor(self):
        symbol = encode.build(URL, 8, "H")
        carving = maze.carve(symbol, seed=6)
        self.assertGreater(carving.branches, 10)
        self.assertGreater(carving.dead_ends, 10)

    def test_it_is_a_braid_maze_and_the_loop_count_says_so(self):
        # A perfect maze has no loops. This is not one, and the number is reported rather than
        # left for somebody to discover.
        symbol = encode.build(URL, 8, "H")
        carving = maze.carve(symbol, seed=6)
        self.assertGreater(carving.loops, 0)

    def test_the_solver_walks_only_light_modules_and_never_flips_anything(self):
        symbol = encode.build(URL, 6, "H")
        region = maze.largest_region(maze.carvable(6))
        before = [row[:] for row in symbol.modules]
        maze.solve(symbol.modules, region, min(region), max(region))
        self.assertEqual(symbol.modules, before)

    def test_a_symbol_with_no_route_is_reported_rather_than_claimed_solved(self):
        symbol = encode.build(URL, 6, "H")
        region = maze.largest_region(maze.carvable(6))
        walled = [[True] * symbol.size for _ in range(symbol.size)]
        self.assertIsNone(maze.solve(walled, region, min(region), max(region)))


class TheSvgIsSelfContained(unittest.TestCase):
    def test_it_asks_for_nothing_from_the_network(self):
        symbol = encode.build(URL, 6, "H")
        carving = maze.carve(symbol, seed=8)
        text = svg.render(carving.modules, path=carving.path, flipped=carving.flipped,
                          entrance=carving.entrance, exit_at=carving.exit, annotate=True)
        # The `xmlns` declaration is removed first. It is a namespace NAME that happens to look
        # like a URL and nothing fetches it, and leaving it in makes this test fail on the one
        # attribute every SVG is required to have.
        body = text.replace('xmlns="http://www.w3.org/2000/svg"', "")
        for forbidden in ("http://", "https://", "<script", "@import", "xlink:href", "<image",
                          "url(", "@font-face"):
            self.assertNotIn(forbidden, body, f"the SVG reaches for {forbidden}")

    def test_the_quiet_zone_is_there(self):
        symbol = encode.build(URL, 6, "H")
        text = svg.render(symbol.modules, scale=10, quiet=4)
        self.assertIn(f'width="{(symbol.size + 8) * 10}"', text)

    def test_the_dark_modules_in_the_file_are_the_dark_modules_in_the_symbol(self):
        # Parsed back out of the file rather than counted before writing it, so a renderer that
        # dropped some would be caught.
        symbol = encode.build(URL, 6, "H")
        text = svg.render(symbol.modules, scale=4, quiet=4)
        drawn = text.count("M", text.index('fill="#000000"'))
        expected = sum(1 for row in symbol.modules for value in row if value)
        self.assertEqual(drawn, expected)


class TheCommandLine(unittest.TestCase):
    def invoke(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        code = cli.main(list(argv), stdout=out, stderr=err)
        return code, out.getvalue(), err.getvalue()

    def test_a_successful_run_reports_that_it_decoded(self):
        code, out, err = self.invoke("https://example.invalid/m/1", "--version", "6", "--json")
        self.assertEqual(code, 0)
        body = json.loads(out)
        self.assertTrue(body["decodes_to_the_url"])
        self.assertTrue(body["maze_is_solvable"])
        self.assertEqual(body["decoded"]["payload"], "https://example.invalid/m/1")

    def test_the_report_says_what_the_carving_cost(self):
        _, out, _ = self.invoke("https://example.invalid/m/2", "--version", "8", "--json")
        body = json.loads(out)
        for key in ("modules_flipped", "corrupted_codewords", "worst_block_corrupted",
                    "budget_per_block", "independent_loops", "solution_length"):
            self.assertIn(key, body)
        self.assertLessEqual(body["worst_block_corrupted"], body["budget_per_block"])

    def test_a_payload_that_does_not_fit_is_refused_before_anything_is_written(self):
        code, out, err = self.invoke("x" * 400, "--version", "1")
        self.assertEqual(code, 3)
        self.assertEqual(out, "")

    def test_a_payload_too_large_for_any_known_version_is_refused(self):
        code, _, _ = self.invoke("x" * 5000)
        self.assertEqual(code, 3)

    def test_negative_arguments_are_refused(self):
        for argv in (("--branches", "-1"), ("--scale", "0"), ("--seed", "-4")):
            with self.subTest(argv=argv):
                code, _, _ = self.invoke("https://example.invalid/m/3", "--version", "6", *argv)
                self.assertEqual(code, 3)

    def test_the_same_seed_gives_the_same_maze(self):
        _, first, _ = self.invoke("https://example.invalid/m/4", "--version", "8",
                                  "--seed", "3", "--json")
        _, second, _ = self.invoke("https://example.invalid/m/4", "--version", "8",
                                   "--seed", "3", "--json")
        self.assertEqual(first, second)

    def test_different_seeds_give_different_mazes(self):
        _, first, _ = self.invoke("https://example.invalid/m/5", "--version", "8",
                                  "--seed", "1", "--json")
        _, second, _ = self.invoke("https://example.invalid/m/5", "--version", "8",
                                   "--seed", "2", "--json")
        self.assertNotEqual(first, second)


if __name__ == "__main__":
    unittest.main()
