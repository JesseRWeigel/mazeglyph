"""The command line. Build the symbol, carve the maze, and refuse to claim more than was checked.

FOUR EXIT CODES:

  0  a maze was carved and the symbol still decodes to the payload it was given
  1  the maze was carved and the symbol NO LONGER DECODES, which is a failure of this program
  2  no maze could be carved within the budget, so nothing was written
  3  the arguments do not describe something that can be built

The difference between 0 and 1 is the whole point of the program, so they are separate codes and
the check that separates them runs on every invocation rather than on request. A tool that wrote
the file and left the verifying to the user would be a tool that ships unscannable QR codes.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

from . import blocks, decode, encode, maze, svg


def is_good(reading, payload: bytes, solved: bool) -> bool:
    """Whether a run may report success.

    A FUNCTION RATHER THAN AN EXPRESSION BURIED IN `main`, so that it can be asked directly about a
    symbol that is deliberately broken. The tool never produces one, which is the point of the
    tool, so the only way to exercise this is to hand it one, and the only way to hand it one is
    for it to be callable.
    """
    return bool(reading.ok and reading.payload == payload and solved)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mazeglyph",
        description="A maze whose walls are a scannable QR code, carved inside the error "
                    "correction budget.")
    parser.add_argument("url", help="what the code should resolve to")
    parser.add_argument("--version", type=int, default=None,
                        help="QR version; the smallest that fits by default")
    parser.add_argument("--level", default="H", choices=list(blocks.LEVELS),
                        help="error correction level, which is the size of the carving budget "
                             "(default: H, the largest)")
    parser.add_argument("--branches", type=int, default=400,
                        help="how many dead ends to attempt; more spends more of the budget")
    parser.add_argument("--seed", type=int, default=0, help="which maze, for a repeatable one")
    parser.add_argument("--scale", type=int, default=8, help="pixels per module in the SVG")
    parser.add_argument("--out", default="", help="write the plain SVG here")
    parser.add_argument("--annotated", default="",
                        help="write an annotated SVG here, showing the solution and the carving")
    parser.add_argument("--text", action="store_true", help="draw the symbol in the terminal")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    return parser


def main(argv=None, stdout=None, stderr=None) -> int:
    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr
    args = build_parser().parse_args(argv)

    payload = args.url.encode("utf-8")
    try:
        version = args.version or encode.smallest_version(payload, args.level)
        symbol = encode.build(payload, version, args.level)
    except ValueError as error:
        print(str(error), file=stderr)
        return 3
    if args.branches < 0 or args.scale < 1 or args.seed < 0:
        print("the branch count, the scale and the seed must not be negative", file=stderr)
        return 3

    try:
        carving = maze.carve(symbol, branch_attempts=args.branches, seed=args.seed)
    except ValueError as error:
        print(str(error), file=stderr)
        return 2

    # THE CHECK THAT MAKES THE CLAIM. Every run decodes what it just carved and compares it with
    # what was asked for. Without this the program writes a picture and hopes.
    reading = decode.read(carving.modules)
    solved = bool(carving.path)
    good = is_good(reading, payload, solved)

    report = carving.as_dict()
    report["url"] = args.url
    report["version"] = version
    report["level"] = args.level
    report["mask"] = symbol.mask
    report["size"] = symbol.size
    report["decoded"] = reading.as_dict()
    report["decodes_to_the_url"] = reading.ok and reading.payload == payload
    report["maze_is_solvable"] = solved

    if args.out:
        pathlib.Path(args.out).write_text(
            svg.render(carving.modules, scale=args.scale,
                       title=f"a maze that is also a QR code for {args.url}"), encoding="utf-8")
    if args.annotated:
        pathlib.Path(args.annotated).write_text(
            svg.render(carving.modules, scale=args.scale, path=carving.path,
                       flipped=carving.flipped, entrance=carving.entrance,
                       exit_at=carving.exit, annotate=True,
                       title="NOT SCANNABLE: the solution and the carving drawn over the symbol"),
            encoding="utf-8")

    if args.json:
        json.dump(report, stdout, indent=2, sort_keys=True)
        stdout.write("\n")
    elif args.text:
        stdout.write(svg.as_text(carving.modules, carving.path))
    else:
        print(f"version {version}{args.level}, {symbol.size} modules across, mask {symbol.mask}",
              file=stdout)
        print(f"{report['modules_flipped']} modules flipped, costing "
              f"{report['corrupted_codewords']} corrupt codewords; the worst of "
              f"{report['blocks']} blocks used {report['worst_block_corrupted']} of its "
              f"{report['budget_per_block']}", file=stdout)
        print(f"the maze has {report['walkable_cells']} cells you can walk to, "
              f"{report['branches']} junctions, {report['dead_ends']} dead ends and "
              f"{report['independent_loops']} loops", file=stdout)
        print(f"the solution is {report['solution_length']} cells long", file=stdout)
        if report["branches_refused_for_want_of_budget"]:
            print(f"{report['branches_refused_for_want_of_budget']} further dead ends were "
                  f"refused because the budget was spent", file=stdout)

    if not good:
        why = []
        if not solved:
            why.append("the maze has no solution")
        if not reading.ok:
            why.append(f"the symbol no longer decodes: {reading.problem}")
        elif reading.payload != payload:
            why.append("the symbol decodes to something else")
        print("; ".join(why), file=stderr)
        return 1
    print(f"it decodes to {args.url} after correcting {reading.corrected_codewords} codewords",
          file=stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
