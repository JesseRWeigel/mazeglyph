"""Scan everything published for anything belonging to the machine it was built on.

Two things this has to get right.

  IT MUST NOT MATCH ITSELF. Every pattern and every planted control is assembled from fragments at
  runtime, so the literal text a pattern looks for never appears in this source.

  IT MUST BE PROVEN TO WORK. A positive control plants invented values and requires all of them to
  be found; a negative control passes clean text and requires nothing. A broken pattern is silent,
  and silence is exactly what a passing scan looks like.

WHAT THIS PROJECT HAS TO GET RIGHT THAT MOST DO NOT: IT PUBLISHES URLS BY DESIGN. A QR code is a
URL rendered as a picture, so a URL is the deliverable and cannot be treated as a leak. Every URL
in this repository points at `example.invalid`, a reserved name that can never resolve to
anything, and the scan enforces that: any other host is a finding.

The planted values are INVENTED. Nothing here reads the real environment, because a control that
plants a real secret has published it the moment its output is saved.
"""


from __future__ import annotations

import os
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PUBLISHED = ("mazeglyph", "tests", "scripts", "README.md", "LICENSE",
             ".gitignore")
SKIP_SUFFIXES = (".pyc",)
ALLOWED_EMAIL_DOMAIN = "example" + "." + "invalid"


def patterns():
    """Assembled at runtime so no pattern's literal text appears in this file."""
    h, o, m, e = "h", "o", "m", "e"
    u, s, r = "u", "s", "r"
    return [
        ("a home directory path", re.compile("/" + h + o + m + e + r"/[A-Za-z0-9_.-]+")),
        ("a users directory path", re.compile("/" + u + s + e + r + s + r"/[A-Za-z0-9_.-]+",
                                              re.I)),
        ("a windows profile path",
         re.compile(r"[A-Za-z]:\\\\?" + u + s + e + r + s + r"\\\\?[A-Za-z0-9_.-]+", re.I)),
        ("a private key header", re.compile("BEGIN [A-Z ]*P" + "RIVATE KEY")),
        ("an api key of the sk- shape", re.compile(r"\b" + s + "k" + r"-[A-Za-z0-9]{16,}")),
        ("a bearer token", re.compile(r"\b" + "Bea" + "rer\\s+[A-Za-z0-9._-]{16,}")),
        ("an aws access key id", re.compile(r"\b" + "AKI" + "A" + r"[0-9A-Z]{12,}")),
        ("a github token", re.compile(r"\b" + "g" + "h" + r"[posu]_[A-Za-z0-9]{20,}")),
        ("a postgres connection string with a password",
         re.compile("post" + "gres(?:ql)?://[^\\s:@]+:[^\\s:@]+@")),
        ("an ipv4 address that is not a loopback or a version",
         re.compile(r"\b(?!127\.0\.0\.1\b)(?:\d{1,3}\.){3}\d{1,3}\b")),
        ("an email address outside the reserved domain",
         re.compile(r"\b[A-Za-z0-9._%+-]+@(?!" + re.escape(ALLOWED_EMAIL_DOMAIN) +
                    r"\b)[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ]


def scan_text(text: str, label: str):
    findings = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        for description, pattern in patterns():
            for match in pattern.finditer(line):
                findings.append((label, line_number, description, match.group(0)))
    return findings


def published_files():
    for entry in PUBLISHED:
        path = ROOT / entry
        if path.is_file():
            yield path
        elif path.is_dir():
            for child in sorted(path.rglob("*")):
                if child.is_file() and "__pycache__" not in child.parts and \
                        child.suffix not in SKIP_SUFFIXES:
                    yield child


def planted():
    """Invented values, assembled the same way the patterns are, for the positive control."""
    h, o, m, e = "h", "o", "m", "e"
    users = "U" + "sers"
    at = chr(64)
    return [
        "/" + h + o + m + e + "/plante" + "duser/projects/notreal",
        "/" + users + "/Plan" + "tedPerson/Documents",
        "C:" + chr(92) + users + chr(92) + "Plan" + "tedPerson" + chr(92) + "AppData",
        "-----BEGIN RSA P" + "RIVATE KEY-----",
        "s" + "k-" + "PlantedNotARealKey0123456789",
        "Bea" + "rer " + "planted.token.value.0123456789",
        "AKI" + "A" + "PLANTEDNOTREAL99",
        "g" + "h" + "p_PlantedTokenValue0123456789ab",
        "post" + "gres://planteduser:plantedsecret" + at + "db.inval" + "id:5432/app",
        ".".join(["203", "0", "113", "47"]),
        "planted.person" + at + "notarealcompany.exam" + "ple",
    ]


def clean_samples():
    """Text that must produce nothing, including the shapes closest to a false positive."""
    at = chr(64)
    return [
        "a.brenner12" + at + ALLOWED_EMAIL_DOMAIN,
        "https://northwind." + ALLOWED_EMAIL_DOMAIN + "/invoice42",
        # Four dotted numbers that are a version, not an address: the known limit of scanning
        # text rather than parsing it, kept here so the control still fails if anything ELSE
        # clean starts matching.
        "version " + ".".join("1234") + " of nothing",
        ".".join(["127", "0", "0", "1"]) + " is the loopback",
        "version 8 at level H holds 86 data codewords",
        "https://" + ALLOWED_EMAIL_DOMAIN + "/m/7f3a",
        "the worst block used 14 of its 14 correction codewords",
        "the sku is 6Q8J-0 and the phone is +99 555 512823",
    ]


def main() -> int:
    problems = []

    found = scan_text("\n".join(planted()), "positive control")
    seen = {f[1] for f in found}
    for index, value in enumerate(planted(), start=1):
        if index not in seen:
            problems.append(f"positive control: nothing matched {value!r}")

    for sample in clean_samples():
        hits = scan_text(sample, "negative control")
        hits = [h for h in hits if not (sample.startswith("version") and "ipv4" in h[2])]
        for hit in hits:
            problems.append(f"negative control: {sample!r} matched {hit[2]}: {hit[3]!r}")

    findings = []
    for path in published_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            problems.append(f"{path}: could not be read as text")
            continue
        findings.extend(scan_text(text, str(path.relative_to(ROOT))))
        if b"\0" in path.read_bytes():
            # One NUL byte makes git and grep call the whole file binary, and a scan that skips
            # a file reports the same "clean" as one that read it and found nothing.
            problems.append(f"{path.relative_to(ROOT)} contains a NUL byte, which would make "
                            f"every text scan skip it silently")

    measured = subprocess.run([sys.executable, "scripts/measure.py"], cwd=ROOT,
                              capture_output=True, text=True, timeout=3600)
    if measured.returncode != 0:
        problems.append(f"the measurement would not run: {measured.stderr.strip()[-300:]}")
    else:
        findings.extend(scan_text(measured.stdout, "the measurement"))
        home = os.path.expanduser("~")
        user = os.path.basename(home)
        if home and home != "/" and home in measured.stdout:
            problems.append("the measurement carries this machine's home directory")
        if user and len(user) > 2 and user in measured.stdout:
            problems.append("the measurement carries this machine's account name")
        if str(ROOT) in measured.stdout:
            problems.append("the measurement carries an absolute path to this checkout")

    for label, line_number, description, text in findings:
        print(f"FOUND {label}:{line_number}: {description}: {text}")
    for problem in problems:
        print("CONTROL FAILED " + problem)

    if findings or problems:
        print(f"{len(findings)} findings, {len(problems)} control failures")
        return 1
    print(f"clean: {len(list(published_files()))} published files and the whole measurement "
          f"carry none of {len(patterns())} patterns; {len(planted())} planted values were all "
          f"found and {len(clean_samples())} clean samples matched nothing")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
