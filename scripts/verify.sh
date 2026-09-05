#!/usr/bin/env bash
set -u
cd "$(dirname "$0")/.."
PY=${PY:-python3}
STEP=0
FAILED=0
step() { STEP=$((STEP + 1)); printf '\n== %d. %s\n' "$STEP" "$1"; }
check() {
  if [ "$1" -eq 0 ]; then printf '   PASS\n'
  else printf '   FAIL (exit %d)\n' "$1"; FAILED=$((FAILED + 1)); fi
}

TREE_HASH='
import hashlib, pathlib
h = hashlib.sha256()
for p in sorted(pathlib.Path(".").rglob("*")):
    if p.is_file() and ".git" not in p.parts and "__pycache__" not in p.parts:
        h.update(str(p).encode()); h.update(p.read_bytes())
print(h.hexdigest())
'
BEFORE=$("$PY" -c "$TREE_HASH")

step "python, standard library only, no QR library anywhere"
"$PY" - <<'EOF'
import sys
sys.path.insert(0, ".")
import mazeglyph.blocks, mazeglyph.cli, mazeglyph.decode, mazeglyph.encode
import mazeglyph.galois, mazeglyph.geometry, mazeglyph.maze, mazeglyph.reedsolomon
import mazeglyph.svg
for name in ("qrcode", "segno", "PIL", "numpy", "reedsolo", "pyzbar", "cv2"):
    if name in sys.modules:
        print(f"   FAIL {name} is loaded, so the encoder is not this program's")
        raise SystemExit(1)
print(f"   python {sys.version.split()[0]}, standard library only")
print("   the encoder, the decoder and the Reed-Solomon code are all in this repository")
EOF
check $?

step "unit tests"
# Counts and verdict only, never elapsed time: this transcript is pasted into the README and
# compared against a fresh run, so a millisecond figure could never converge.
OUT=$("$PY" -m unittest discover -s tests -t . 2>&1)
RC=$?
echo "$OUT" | grep -E "^Ran [0-9]+ tests" | sed -E 's/ in [0-9.]+s//' | sed 's/^/   /'
echo "$OUT" | grep -E "^(OK|FAILED)" | sed 's/^/   /'
check $RC

step "the test count claimed in the README is the count that exists"
"$PY" - <<'EOF'
import re, subprocess, sys
out = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."],
                     capture_output=True, text=True)
ran = int(re.search(r"^Ran (\d+) tests", out.stderr, re.M).group(1))
text = open("README.md", encoding="utf-8").read()
claimed = [int(n) for n in re.findall(r"Ran (\d+) tests", text)]
claimed += [int(n) for n in re.findall(r"(\d+) unit tests", text)]
if not claimed:
    print("   FAIL the README pastes no test count, so it cannot be checked"); raise SystemExit(1)
if any(number != ran for number in claimed):
    print(f"   FAIL the README claims {sorted(set(claimed))} and the runner ran {ran}")
    raise SystemExit(1)
print(f"   the README says {ran} unit tests in {len(claimed)} places and the runner ran {ran}")
EOF
check $?

step "the error correction recovers at its capacity and refuses one past it"
# The number the carving budget is spent against. A decoder that repaired one error too many would
# let the carver overspend and produce something no scanner could read.
"$PY" - <<'EOF'
import random, sys
sys.path.insert(0, ".")
from mazeglyph import reedsolomon
rng = random.Random(20260829)
at_capacity = past = wrong = 0
for ec_count in (10, 16, 22, 26, 28, 30):
    data = [rng.randrange(256) for _ in range(35)]
    block = data + reedsolomon.encode(data, ec_count)
    capacity = reedsolomon.capacity(ec_count)
    for count in range(capacity + 1):
        damaged = list(block)
        for position in rng.sample(range(len(block)), count):
            damaged[position] ^= rng.randrange(1, 256)
        fixed, found = reedsolomon.correct(damaged, ec_count)
        if fixed == block and found == count:
            at_capacity += 1
        else:
            print(f"   FAIL {ec_count} correction codewords, {count} errors: not recovered")
            wrong += 1
    for trial in range(20):
        damaged = list(block)
        for position in rng.sample(range(len(block)), capacity + 1):
            damaged[position] ^= rng.randrange(1, 256)
        fixed, _ = reedsolomon.correct(damaged, ec_count)
        if fixed is None or fixed == block:
            past += 1
        else:
            print("   FAIL a block past capacity was repaired into something else")
            wrong += 1
print(f"   {at_capacity} blocks recovered exactly, at every error count from none to capacity")
print(f"   {past} blocks one past capacity, none repaired into a different block")
raise SystemExit(1 if wrong else 0)
EOF
check $?

step "every version and level round trips through a separately written decoder"
"$PY" - <<'EOF'
import sys
sys.path.insert(0, ".")
from mazeglyph import blocks, decode, encode
checked = wrong = 0
for version in blocks.VERSIONS:
    for level in blocks.LEVELS:
        layout = blocks.layout(version, level)
        room = (layout.data_codewords * 8 - 4 - encode.character_count_bits(version)) // 8
        for size in sorted({1, max(1, room // 2), room}):
            payload = bytes((index * 7 + size) % 90 + 33 for index in range(size))
            symbol = encode.build(payload, version, level)
            reading = decode.read(symbol.modules)
            checked += 1
            if not (reading.ok and reading.payload == payload
                    and reading.level == level and reading.mask == symbol.mask):
                wrong += 1
                print(f"   FAIL version {version} level {level}, {size} bytes: "
                      f"{reading.problem or 'read back wrongly'}")
print(f"   {checked} combinations of version, level and payload size, {wrong} wrong")
if checked < 100:
    print(f"   FAIL only {checked} combinations were exercised"); raise SystemExit(1)
raise SystemExit(1 if wrong else 0)
EOF
check $?

step "the carved symbol still decodes, at every size, and never touches a function pattern"
"$PY" - <<'EOF'
import sys
sys.path.insert(0, ".")
from mazeglyph import blocks, decode, encode, geometry, maze
url = b"https://example.invalid/m/verify"
checked = wrong = 0
for version in blocks.VERSIONS[3:]:
    for seed in (0, 3, 8):
        symbol = encode.build(url, version, "H")
        carving = maze.carve(symbol, seed=seed)
        reading = decode.read(carving.modules)
        reserved = geometry.function_modules(version)
        checked += 1
        problems = []
        if not (reading.ok and reading.payload == url):
            problems.append(reading.problem or "decoded to something else")
        if not carving.path:
            problems.append("the maze has no solution")
        touched = [cell for cell in carving.flipped if cell in reserved]
        if touched:
            problems.append(f"{len(touched)} function modules were carved")
        for block, count in carving.corrupted_per_block.items():
            if count > carving.budget_per_block:
                problems.append(f"block {block} was damaged past its budget")
        if problems:
            wrong += 1
            print(f"   FAIL version {version} seed {seed}: {'; '.join(problems)}")
print(f"   {checked} carvings across {len(blocks.VERSIONS[3:])} versions and three seeds, "
      f"{wrong} that failed")
raise SystemExit(1 if wrong else 0)
EOF
check $?

step "the symbol is already most of a maze before anything is carved"
# The finding the project rests on, printed rather than described.
"$PY" - <<'EOF'
import sys
sys.path.insert(0, ".")
from mazeglyph import decode, encode, maze
url = b"https://example.invalid/m/verify"
symbol = encode.build(url, 8, "H")
bare = maze.carve(symbol, seed=7, branch_attempts=0)
full = maze.carve(symbol, seed=7, branch_attempts=400)
data_modules = len(maze.carvable(8))
print(f"   {len(bare.flipped)} flips out of {data_modules} data modules connect one corner to "
      f"the other")
print(f"   that bare maze already has {bare.walkable} walkable cells, {bare.branches} junctions "
      f"and {bare.loops} loops")
print(f"   spending the whole budget instead: {len(full.flipped)} flips, "
      f"{full.walkable} walkable cells, {full.loops} loops, "
      f"{full.refused_branches} further branches refused")
bad = 0
if len(bare.flipped) > 40:
    print("   FAIL connecting the two ends took more flips than the claim allows"); bad = 1
if full.worst_block != full.budget_per_block:
    print("   FAIL the full carving did not spend the whole budget"); bad = 1
for carving in (bare, full):
    reading = decode.read(carving.modules)
    if not (reading.ok and reading.payload == url):
        print("   FAIL a carving does not decode"); bad = 1
raise SystemExit(bad)
EOF
check $?

step "the documented invocations exit as documented"
"$PY" - <<'EOF'
import io, sys
sys.path.insert(0, ".")
from mazeglyph import cli
URL = "https://example.invalid/m/verify"
cases = [
    ([URL, "--version", "6"], 0, "an ordinary run"),
    ([URL], 0, "the smallest version that fits"),
    ([URL, "--version", "10", "--json"], 0, "the report as json"),
    ([URL, "--version", "8", "--level", "L"], 0, "a lower correction level"),
    ([URL, "--version", "8", "--branches", "0"], 0, "no branches at all"),
    ([URL, "--version", "6", "--text"], 0, "drawn in the terminal"),
    (["x" * 400, "--version", "1"], 3, "too much text for the version"),
    (["x" * 5000], 3, "too much text for any version"),
    ([URL, "--version", "6", "--branches", "-1"], 3, "a negative branch count"),
    ([URL, "--version", "6", "--scale", "0"], 3, "a scale of zero"),
]
bad = 0
for argv, expected, what in cases:
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(argv, stdout=out, stderr=err)
    if code != expected:
        bad += 1
        print(f"   FAIL {what}: exited {code}, documented as {expected}")
    else:
        print(f"   exit {expected}: {what}")
raise SystemExit(1 if bad else 0)
EOF
check $?

step "the measurement is deterministic and does not track the working directory"
"$PY" - <<'EOF'
import pathlib, shutil, subprocess, sys, tempfile
def fp(tree):
    d = subprocess.run([sys.executable, "scripts/measure.py"], cwd=tree, capture_output=True,
                       text=True, timeout=3600)
    if d.returncode != 0:
        print("   FAIL the fingerprint could not be taken:", d.stderr.strip()[-300:])
        raise SystemExit(1)
    return [l.split()[1] for l in d.stderr.splitlines() if l.startswith("FINGERPRINT ")][0]
one, two = fp("."), fp(".")
with tempfile.TemporaryDirectory() as area:
    other = pathlib.Path(area) / "a-completely-different-name"
    shutil.copytree(".", other, ignore=shutil.ignore_patterns(".git", "__pycache__"))
    three = fp(other)
if not (one == two == three):
    print(f"   FAIL {one} then {two} then {three}"); raise SystemExit(1)
print(f"   FINGERPRINT {one}")
print("   identical across two runs and from a copy under a different name")
EOF
check $?

step "the measurement carries nothing belonging to this machine"
"$PY" - <<'EOF'
import os, subprocess, sys
done = subprocess.run([sys.executable, "scripts/measure.py"], capture_output=True, text=True)
if done.returncode != 0:
    print("   FAIL the measurement refused to print"); raise SystemExit(1)
home = os.path.expanduser("~")
user = os.path.basename(home)
problems = []
if home and home != "/" and home in done.stdout:
    problems.append("the home directory appears in the measurement")
if user and len(user) > 2 and user in done.stdout:
    problems.append("the account name appears in the measurement")
if os.getcwd() in done.stdout:
    problems.append("the path to this checkout appears in the measurement")
for problem in problems:
    print(f"   FAIL {problem}")
print(f"   {len(done.stdout)} characters of measurement, none of them this machine's")
raise SystemExit(1 if problems else 0)
EOF
check $?

step "sabotage suite, three gates and a null control"
OUT=$("$PY" scripts/sabotage.py 2>&1)
RC=$?
echo "$OUT" | grep -E "^FAIL|sabotages caught|null control" | tail -6 | sed 's/^/   /'
check $RC

step "independent recomputation, importing nothing from the package"
OUT=$("$PY" scripts/check_independent.py 2>&1)
RC=$?
echo "$OUT" | fold -s -w 96 | sed 's/^/   /'
check $RC

step "the independent checker refuses every dependent probe"
"$PY" - <<'EOF'
import importlib.util, pathlib
spec = importlib.util.spec_from_file_location("chk", "scripts/check_independent.py")
chk = importlib.util.module_from_spec(spec); spec.loader.exec_module(chk)
# Which probes must be refused is declared in each probe's own first line, not inferred from its
# filename, so adding a probe cannot silently land in the wrong bucket.
probes = []
for path in sorted(pathlib.Path("scripts/probes").glob("probe_*.py")):
    first = path.read_text(encoding="utf-8").splitlines()[0]
    if "MUST BE REFUSED" in first:
        probes.append((path, True))
    elif "MUST BE ACCEPTED" in first:
        probes.append((path, False))
refused = sum(1 for _, want in probes if want)
if refused < 4 or refused == len(probes):
    print(f"   FAIL {refused} refuse and {len(probes) - refused} accept, which proves little")
    raise SystemExit(1)
bad = 0
for path, want in probes:
    if bool(chk.audit(path)) != want:
        print(f"   FAIL {path.name} {'was accepted' if want else 'was refused'}"); bad += 1
print(f"   {refused} dependent probes refused, {len(probes) - refused} clean probe accepted")
raise SystemExit(1 if bad else 0)
EOF
check $?

step "privacy scan with planted controls"
"$PY" scripts/privacy_scan.py | fold -s -w 96 | sed 's/^/   /'
check "${PIPESTATUS[0]}"

step "the published page is what the builder produces, and reaches for nothing"
"$PY" - <<'EOF'
import hashlib, pathlib, re, subprocess, sys

ROOT = pathlib.Path(".").resolve()
PAGE = ROOT / "docs" / "index.html"

# REBUILT AND COMPARED, NOT JUST READ. A page committed once and never regenerated drifts away
# from the code that made it, and the drift is invisible because the page still looks fine. The
# builder decodes every symbol it draws, so rebuilding here also re-runs that check.
before = PAGE.read_bytes() if PAGE.is_file() else b""
done = subprocess.run([sys.executable, "scripts/build_page.py"], capture_output=True, text=True)
if done.returncode != 0:
    print("   the page builder failed:")
    print("   " + (done.stderr or done.stdout).strip().replace("\n", "\n   "))
    raise SystemExit(1)
after = PAGE.read_bytes()
print("   " + done.stdout.strip())
if before and before != after:
    print(f"   FAIL the committed page is not what the builder produces "
          f"({len(before)} bytes committed, {len(after)} bytes rebuilt)")
    raise SystemExit(1)

text = after.decode("utf-8")
problems = []

# Nothing may be fetched. A page that loads a font, a script or an image from somewhere else stops
# working when that somewhere else does, and tells whoever runs it that a reader visited.
for pattern, what in ((r"https?://(?!jesserweigel\.github\.io|github\.com|www\.w3\.org)",
                       "an outbound url"),
                      (r"<script[^>]+src=", "a script from another file"),
                      (r"<link[^>]+href=\"http", "a stylesheet from another file"),
                      (r"@import", "an imported stylesheet")):
    hits = re.findall(pattern, text)
    if hits:
        problems.append(f"{what}: {len(hits)} occurrence(s), first {hits[0]!r}")

if "/home/" in text or "/Users/" in text:
    problems.append("an absolute home path")

# The symbols have to be there. An empty page passes every check above.
symbols = text.count("<svg")
if symbols < 11:
    problems.append(f"only {symbols} drawings on the page, expected at least 11")

print(f"   {len(text) / 1024:.1f} KB, {symbols} drawings, "
      f"sha256 {hashlib.sha256(after).hexdigest()[:16]}")
for message in problems:
    print(f"   FAIL {message}")
raise SystemExit(1 if problems else 0)
EOF
check $?

step "the README is finished and carries this script's own success line"
"$PY" - <<'EOF'
import re, sys
text = open("README.md", encoding="utf-8").read()
prose = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
problems = []
for marker in ("TODO", "PLACEHOLDER", "FIXME", "NOT YET VERIFIED"):
    if marker in prose:
        problems.append(f"the README still contains {marker!r}")
for heading in ("## Status", "## Unfinished"):
    if heading not in text:
        problems.append(f"no {heading} section")
if "VERIFY PASSED: mazeglyph" not in text:
    problems.append("the Status section does not carry this script's success line")
if "—" in prose:
    problems.append("the README prose contains an em dash")

sys.path.insert(0, "scripts")
import sabotage
if f"breaks the code {len(sabotage.SABOTAGES)} ways" not in text:
    problems.append(f"the README does not say 'breaks the code {len(sabotage.SABOTAGES)} ways', "
                    f"and there are {len(sabotage.SABOTAGES)} sabotages")
# The BYTE COUNT of the README is deliberately not printed. This transcript is pasted into the
# README, so any number depending on the README's own length changes the moment it is pasted and
# the loop that converges the two would never terminate.
print(f"   {len(re.findall(r'^## ', text, re.M))} sections, {len(problems)} problem(s)")
for message in problems:
    print(f"   {message}")
sys.exit(1 if problems else 0)
EOF
check $?

step "verify did not modify the tree it was verifying"
AFTER=$("$PY" -c "$TREE_HASH")
if [ "$BEFORE" = "$AFTER" ]; then printf '   the tree is byte identical to before this ran\n'; check 0
else printf '   FAIL the tree changed while being verified\n'; check 1; fi

printf '\n'
if [ "$FAILED" -eq 0 ]; then
  printf 'VERIFY PASSED: mazeglyph, %d of %d steps\n' "$STEP" "$STEP"; exit 0
fi
printf 'VERIFY FAILED: mazeglyph, %d of %d steps failed\n' "$FAILED" "$STEP"
exit 1
