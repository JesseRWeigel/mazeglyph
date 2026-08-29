# mazeglyph

A maze whose walls are a scannable QR code, carved inside the error correction budget.

Catalog task: `WEIRD-031`. One of a public catalog of build ideas:
https://github.com/JesseRWeigel/722-things-to-build

```
$ mazeglyph 'https://example.invalid/m/7f3a' --version 8 --out maze.svg
version 8H, 49 modules across, mask 4
165 modules flipped, costing 78 corrupt codewords; the worst of 6 blocks used 13 of its 13
the maze has 764 cells you can walk to, 411 junctions, 112 dead ends and 209 loops
the solution is 85 cells long
16 further dead ends were refused because the budget was spent
it decodes to https://example.invalid/m/7f3a after correcting 78 codewords
```

Every run decodes what it just carved before it claims anything. That check is the program.

## The finding

**A QR code is already most of a maze.** Its data area is about half light modules scattered at
random, and a passage is a run of light modules, so the maze is mostly there before you start.

On a version 8 symbol, **nine flipped modules out of 1,936** are enough to connect one corner to
the other. That bare maze already has 315 cells you can walk to, 45 loops and 56 dead ends. Almost
none of the error correction budget has been touched.

| branch attempts | flips | corrupt codewords | worst block | walkable cells | loops | still decodes |
|---|---|---|---|---|---|---|
| 0 | 9 | 7 | 2 / 13 | 315 | 45 | yes |
| 10 | 18 | 14 | 4 / 13 | 382 | 59 | yes |
| 40 | 36 | 27 | 8 / 13 | 459 | 67 | yes |
| 120 | 85 | 58 | 12 / 13 | 647 | 106 | yes |
| 400 | 165 | 78 | 13 / 13 | 764 | 209 | yes |

## How the budget works

Carving means flipping modules, and every flipped module corrupts the codeword it belongs to.
Reed-Solomon says exactly how many corrupt codewords a block survives: **half its correction
codewords**, because the decoder is not told where the errors are and spends one codeword locating
each and one correcting it.

Two things follow, and both shape the program.

**The budget is counted in codewords, not in flips.** A codeword is eight modules, so eight flips
inside one codeword cost the same as one. On the table above, 165 flips cost 78 codewords.

**The budget is per block, not per symbol.** A version 8 level H symbol has six blocks of 26
correction codewords, so 78 corrupt codewords in total, but only if the damage is spread evenly.
Concentrate it in one block and the symbol fails long before that. Interleaving is what makes the
even spread happen: codewords are written one from each block in turn, so a carved region damages
every block a little.

## Where the budget actually goes

The carving is a shortest path problem with an unusual cost. Moving onto a module that is already
light is **free**. Moving onto a dark one costs one flip. So the cheapest route from the entrance
to the exit threads through the light modules the symbol happens to have, and the budget is spent
only where the existing pattern refuses to cooperate. That is what "exploit the error correction
budget" means here.

Whatever is left goes on dead ends, each a short cheapest path from somewhere on the route. A
branch that does not fit is counted and skipped rather than trimmed, so the report can say how much
maze the budget actually bought.

## What it never touches

The finder patterns, the separators, the timing patterns, the alignment patterns and the format
information. A scanner uses those to find the symbol at all, **no error correction covers them**,
and a maze carved through them produces something no scanner would recognise as a QR code.

That leaves less room than it sounds. The two timing patterns each run the full width of the
symbol, so the vertical one walls off the six columns to its left and the horizontal one walls off
the six rows above it. For version 6 that is 144 modules stranded in each strip, exactly symmetric,
and no maze crossing the symbol can ever use them.

## It is a braid maze, not a perfect one

A perfect maze is a tree: one route between any two points, no loops. This is not that, and saying
so is better than implying otherwise. The light region is already a large connected blob before
anything is carved, and carving only widens it. Turning it into a tree would mean **adding** walls,
light modules flipped to dark, and every one of those costs the same as a passage. The budget will
not buy both.

So the loop count is reported. A version 8 maze at full budget has 209 independent loops, 411
junctions and 112 dead ends, and it is harder to solve by eye than a perfect maze of the same size
for exactly that reason.

## What was verified, and what was not

**There is no QR scanner on the machine this was built on, and no third party decoder available to
it.** So "the maze still scans" was not checked by scanning, and this README will not claim it was.

What was checked:

- A decoder written from the standard, doing the inverse operations, recovers the payload from
  every symbol the encoder produces and from every symbol the carver carves. Its Reed-Solomon
  half is syndromes, Berlekamp-Massey, a root search and a solved linear system, which shares no
  code with the encoder's single polynomial division.
- `scripts/check_independent.py`, which imports nothing from the package, **builds symbols with its
  own field arithmetic, its own generator polynomial, its own placement and its own format word**,
  and the package reads them correctly. Two implementations that never shared a line agreeing on a
  symbol is the closest thing to a scanner available here.
- That same file parses the SVG **back off disk** into a module grid and checks it against what the
  program reported, so a renderer that dropped a module would be caught.
- The structural facts a scanner actually checks: the timing patterns alternate and start dark on
  an even coordinate, the finder patterns are three rings, the module that is always dark is dark.

What was not: that a phone camera, at an angle, in poor light, reads it.

## How the claims are checked

`bash scripts/verify.sh` runs all of it. Sixteen steps. No QR library, no image library, no
Reed-Solomon library: the field arithmetic, the error correction, the encoder and the decoder are
all in this repository, because a bundled encoder would make "it still scans" a claim about
somebody else's code.

**88 unit tests.** The field axioms exhaustively, error correction at every count from zero to
capacity and one past it, the geometry against the published module counts, both BCH codes against
their published minimum distances, every version and level round tripping, and the carving.

**A sabotage suite** that breaks the code 44 ways and requires each one to apply, to move the
fingerprint, and only then to be caught. A null control copies the tree into a differently named
directory first and requires the fingerprint not to move.

**One table that cannot be derived, checked against one that can.** How a version's codewords split
into blocks exists only in a table. How many codewords a version holds is a consequence of its
geometry. The two are computed separately and compared, which caught two transcription errors on
the day it was written.

## What the verification found

**The format information was one bit too long, and it clobbered the module that is always dark.**
The second copy of the format is seven bits up the left edge and eight along the top; this wrote
eight and seven. The extra bit landed on the module the standard requires to be dark forever. Every
payload round tripped perfectly, because the decoder read the same displaced positions back and
agreed with itself, and no real scanner would have read the symbol. It was found by a sabotage that
made that module light and changed nothing measurable, which is the sabotage suite reporting that
the module was already wrong.

**Berlekamp-Massey was one degree off, and only exactly at capacity.** The register length was
being read off the polynomial's length, and adding two polynomials can lengthen the list without
changing the register. Below capacity there is enough slack that the wrong locator still worked:
383 of 400 random trials passed and the 17 that failed were all on the boundary. A test that
sampled error counts uniformly would probably have shipped it.

**Blaming narrow ranges, in the other project of this pair, is the same class of bug.** Here the
equivalent was Forney's algorithm: the error locations were right and every magnitude was wrong.
Rather than debug a formula with several conventions in circulation, the magnitudes are now solved
as a small linear system, which is arithmetic a reader can check against the sentence describing
it.

**The alignment pattern rule does not hold for every version.** It reproduces the published table
exactly to version 20 and disagrees at 32 and 39, where the standard's table is not what any single
rounding rule produces. `alignment_centres` now refuses above the highest version it has been
checked to, rather than returning a plausible wrong answer.

**Every complement of a valid format word is also a valid format word.** All thirty two. So a
format copy whose every module has been inverted sits at distance zero from a perfectly good word
naming the wrong level and the wrong mask, and a decoder that pooled both copies would take it. The
two copies are now read separately and an equal-distance disagreement is refused.

**The "not scannable" warning on the annotated rendering was the caller's to remember.** It is now
emitted whenever the overlay is.

**Three sabotages were removed with the measurements that proved them inert**, rather than excused.
The check that the field generator reaches every element cannot fire, because the polynomial a
sabotage substitutes is primitive too. The terminator's length guard cannot bind, because in byte
mode a symbol filled to the last whole byte leaves exactly four spare bits in all forty version and
level combinations. And three checks on a block beyond repair are redundant with each other, so no
single edit to any of them moves anything; what stands in for them is a measured count of blocks
repaired into something other than the original, across 396 over-capacity trials, which is zero.

## Status

```

== 1. python, standard library only, no QR library anywhere
   python 3.12.3, standard library only
   the encoder, the decoder and the Reed-Solomon code are all in this repository
   PASS

== 2. unit tests
   Ran 88 tests
   OK
   PASS

== 3. the test count claimed in the README is the count that exists
   the README says 88 unit tests in 3 places and the runner ran 88
   PASS

== 4. the error correction recovers at its capacity and refuses one past it
   72 blocks recovered exactly, at every error count from none to capacity
   120 blocks one past capacity, none repaired into a different block
   PASS

== 5. every version and level round trips through a separately written decoder
   120 combinations of version, level and payload size, 0 wrong
   PASS

== 6. the carved symbol still decodes, at every size, and never touches a function pattern
   21 carvings across 7 versions and three seeds, 0 that failed
   PASS

== 7. the symbol is already most of a maze before anything is carved
   13 flips out of 1936 data modules connect one corner to the other
   that bare maze already has 326 walkable cells, 124 junctions and 45 loops
   spending the whole budget instead: 166 flips, 728 walkable cells, 230 loops, 26 further branches refused
   PASS

== 8. the documented invocations exit as documented
   exit 0: an ordinary run
   exit 0: the smallest version that fits
   exit 0: the report as json
   exit 0: a lower correction level
   exit 0: no branches at all
   exit 0: drawn in the terminal
   exit 3: too much text for the version
   exit 3: too much text for any version
   exit 3: a negative branch count
   exit 3: a scale of zero
   PASS

== 9. the measurement is deterministic and does not track the working directory
   FINGERPRINT fa92e53b84d545ed6491dcd4ecbcc4dee7e29a596f8322870f7a895694d61384
   identical across two runs and from a copy under a different name
   PASS

== 10. the measurement carries nothing belonging to this machine
   67137 characters of measurement, none of them this machine's
   PASS

== 11. sabotage suite, three gates and a null control
   null control: an untouched copy in another directory fingerprints fa92e53b84d545ed
   44 of 44 sabotages caught, null control held
   PASS

== 12. independent recomputation, importing nothing from the package
   independent recomputation, importing nothing from mazeglyph
     255 powers of the field generator agree with a table built here from the standard's polynomial
     80 blocks encoded here have zero syndromes under a parity check matrix, which is a different 
   mechanism from evaluating a polynomial
     4 SVG files parsed back from disk carry the format the program reported and a maze this file 
   can solve by union find
     3 symbols built by this file, with its own field, generator, placement and format word, are 
   read correctly by the package
     4 agreed, 0 disagreed
   PASS

== 13. the independent checker refuses every dependent probe
   6 dependent probes refused, 1 clean probe accepted
   PASS

== 14. privacy scan with planted controls
   clean: 32 published files and the whole measurement carry none of 11 patterns; 11 planted 
   values were all found and 8 clean samples matched nothing
   PASS

== 15. the README is finished and carries this script's own success line
   10 sections, 0 problem(s)
   PASS

== 16. verify did not modify the tree it was verifying
   the tree is byte identical to before this ran
   PASS

VERIFY PASSED: mazeglyph, 16 of 16 steps
```

## Unfinished

**Versions 1 to 10 only.** The block table is written out for those forty version and level
combinations and checked against the geometry. Higher versions need more rows, and above version 20
the alignment rule stops being trustworthy.

**Byte mode only.** Numeric and alphanumeric modes pack more into the same space and a URL is
neither, so they would be code nothing here exercises. Kanji mode likewise.

**No scanner was used.** Stated above and worth repeating: two independently written decoders agree
and a camera was never involved.

**The maze has loops and a perfect maze would need walls.** Adding walls costs the same budget as
carving passages, and there is not enough for both. A version with far more correction codewords
than the payload needs would have room; nothing here tries it.

**The entrance and the exit are the two extreme corners of the largest region**, which is a
reasonable default and is not a choice the caller can make. Nor can the caller ask for a particular
solution length.

**The output is an SVG and nothing else.** No PNG, no PDF, no laser cutter dialect. The task
mentions laser cutting and an SVG is the right interchange format for it, but nothing here has been
cut.
