"""Build docs/index.html: the mazes this program produces, drawn, and scannable from the page.

WHY A PAGE AT ALL. Everything else in this repository argues that the carving stays inside the
error correction budget, and it argues in numbers. A reader with a phone can settle it in three
seconds by pointing the camera at the first picture. That is a better demonstration than any table,
and it is the one thing a README cannot do.

WHAT IS ON IT IS REAL OUTPUT. Every symbol here is produced by the same `encode.build` and
`maze.carve` the command line uses, and every one is decoded again by `decode.read` before it
reaches the page. The verdict printed under each maze is that decoder's, not a claim written here.
A symbol that failed to decode would appear saying so rather than being quietly dropped.

SELF CONTAINED, AND NOT BY ACCIDENT. The SVGs are inlined rather than linked, there is no script
from anywhere else, no font is fetched and no image is loaded over the network. The privacy scan in
`scripts/verify.sh` reads the built file and fails on an absolute path or a remote reference, so
this stays true rather than merely starting out true.
"""

from __future__ import annotations

import html
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from mazeglyph import decode, encode, maze, svg  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "index.html"

# The page encodes its own address, so scanning the picture lands on the page that explains it.
URL = "https://jesserweigel.github.io/mazeglyph/"

# How many dead ends to attempt, as a series. The point of the series is that the budget is finite:
# the early frames spend a little of it and the late ones spend all of it, and every frame still
# decodes. The last one refuses branches it cannot afford, which is the behaviour worth seeing.
BUDGET_SERIES = [0, 20, 60, 120, 240, 400]

# The four error correction levels at one fixed version, which is the other axis: a bigger budget
# is a longer maze, bought with fewer bytes of payload.
LEVELS = ["L", "M", "Q", "H"]
LEVEL_VERSION = 6


def build(url: str, level: str, branches: int, seed: int, version: int | None = None) -> dict:
    """One symbol, carved, decoded, and rendered twice. The decoder's verdict travels with it."""
    payload = url.encode("utf-8")
    version = version or encode.smallest_version(payload, level)
    symbol = encode.build(payload, version, level)
    carving = maze.carve(symbol, branch_attempts=branches, seed=seed)
    reading = decode.read(carving.modules)
    out = carving.as_dict()
    out.update({
        "url": url, "version": version, "level": level, "branches_asked": branches, "seed": seed,
        "size": symbol.size,
        "decoded_ok": reading.ok,
        "decodes_to_the_url": bool(reading.ok and reading.payload == payload),
        "corrected_codewords": reading.corrected_codewords,
        "blocks_beyond_repair": reading.blocks_beyond_repair,
        "problem": reading.problem,
        "plain": svg.render(carving.modules, scale=8,
                            title=f"a maze that is also a QR code for {url}"),
        "annotated": svg.render(carving.modules, scale=8, path=carving.path,
                                flipped=carving.flipped, entrance=carving.entrance,
                                exit_at=carving.exit, annotate=True,
                                title="the solution and the carving, drawn over the symbol"),
    })
    return out


def inline(svg_text: str, cls: str) -> str:
    """An SVG dropped straight into the document, sized by CSS rather than by its own attributes.

    The width and height are removed so the picture scales with its container; the viewBox carries
    the aspect ratio. The xmlns stays, because an inline SVG in HTML is still an SVG element and
    dropping it breaks the picture in exactly the browsers nobody tests in.
    """
    body = svg_text.strip()
    body = re.sub(r'\swidth="\d+"\sheight="\d+"', "", body, count=1)
    body = body.replace("<svg ", f'<svg class="{cls}" role="img" ', 1)
    return body


def verdict(entry: dict) -> str:
    """What the decoder said, in a sentence, with the failure case written out."""
    if entry["decodes_to_the_url"]:
        return (f"decodes to the url after correcting "
                f"{entry['corrected_codewords']} codewords")
    if entry["decoded_ok"]:
        return "decodes, but to something else, which is a defect"
    return f"DOES NOT DECODE: {entry['problem'] or 'no reason given'}"


def stat_rows(entry: dict) -> str:
    pairs = [
        ("symbol", f"version {entry['version']}, level {entry['level']}, "
                   f"{entry['size']}&times;{entry['size']} modules"),
        ("maze", f"{entry['walkable_cells']} walkable cells, {entry['dead_ends']} dead ends, "
                 f"solution {entry['solution_length']} steps"),
        ("carved", f"{entry['modules_flipped']} modules flipped, "
                   f"{entry['corrupted_codewords']} codewords touched"),
        ("budget", f"{entry['budget_per_block']} correctable codewords per block, "
                   f"worst block used {entry['worst_block_corrupted']}"),
        ("refused", f"{entry['branches_refused_for_want_of_budget']} branches the budget "
                    f"would not pay for"),
        ("decoder", verdict(entry)),
    ]
    return "".join(f"<div class=stat><dt>{k}</dt><dd>{v}</dd></div>" for k, v in pairs)


def page(hero: dict, series: list[dict], levels: list[dict], measured: dict) -> str:
    # THE ANNOTATED DRAWING, NOT THE PLAIN ONE. Six plain symbols in a row look like six QR codes,
    # because the difference between them is which modules were flipped and that is invisible at a
    # glance. The annotated drawing colours the carved cells and traces the solution, so dragging
    # the slider shows passages opening up, which is the thing the budget is being spent on.
    budget_frames = "".join(
        f'<div class="frame" data-frame="{i}" {"" if i == 0 else "hidden"}>'
        f'{inline(e["annotated"], "maze")}</div>'
        for i, e in enumerate(series))
    budget_captions = "".join(
        f'<div class="caption" data-frame="{i}" {"" if i == 0 else "hidden"}>'
        f'<strong>{e["branches_asked"]} branch attempts.</strong> '
        f'{e["modules_flipped"]} modules flipped, '
        f'worst block spent {e["worst_block_corrupted"]} of its {e["budget_per_block"]}. '
        f'{e["walkable_cells"]} walkable cells, {e["dead_ends"]} dead ends. '
        f'{"<em>Refused " + str(e["branches_refused_for_want_of_budget"]) + " branches it could not afford.</em> " if e["branches_refused_for_want_of_budget"] else ""}'
        f'{verdict(e).capitalize()}.'
        f'</div>'
        for i, e in enumerate(series))

    level_cards = "".join(
        f'<figure class="card">'
        f'{inline(e["annotated"], "maze")}'
        f'<figcaption><strong>level {e["level"]}</strong><br>'
        f'{e["budget_per_block"]} correctable codewords per block<br>'
        f'{e["walkable_cells"]} walkable cells, {e["dead_ends"]} dead ends<br>'
        f'<span class="ok">{verdict(e)}</span></figcaption></figure>'
        for e in levels)

    never = measured["what_the_carving_never_touches"]
    never_rows = "".join(
        f"<tr><td>{html.escape(k)}</td><td>{v['function_modules']}</td>"
        f"<td>{v['function_modules_changed']}</td></tr>"
        for k, v in sorted(never.items()))

    by_version = measured["carving_by_version"]
    version_rows = "".join(
        f"<tr><td>{html.escape(k)}</td><td>{v['budget_per_block']}</td>"
        f"<td>{v['worst_block_corrupted']}</td><td>{v['modules_flipped']}</td>"
        f"<td>{v['dead_ends']}</td><td>{v['branches_refused_for_want_of_budget']}</td>"
        f"<td>{'yes' if v['decodes_to_the_url'] else 'NO'}</td></tr>"
        for k, v in sorted(by_version.items(), key=lambda kv: int(kv[0].split()[1])))

    return f"""<!doctype html>
<html lang=en>
<meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Mazeglyph</title>
<meta name=description content="A maze whose walls are a scannable QR code, carved inside the error correction budget.">
<link rel=icon href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 8 8'%3E%3Crect width='8' height='8' fill='%23fff'/%3E%3Cpath fill='%23111' d='M0 0h3v3H0zM5 0h3v3H5zM0 5h3v3H0zM4 4h1v1H4zM6 4h1v1H6zM5 5h1v1H5zM7 5h1v1H7zM4 6h1v1H4zM6 6h1v1H6zM5 7h1v1H5zM7 7h1v1H7z'/%3E%3C/svg%3E">
<style>
:root{{--bg:#fbfbfa;--fg:#1b1d20;--card:#ffffff;--accent:#2d6f88;--muted:#5f646b;--line:#e2e4e7;
--maze-ink:#111318;--maze-paper:#ffffff}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0f1113;--fg:#e8e6e1;--card:#16191d;
--accent:#7fb2c4;--muted:#8f9298;--line:#24282d;--maze-ink:#0d0f12;--maze-paper:#e9eaec}}}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--fg);
font:16px/1.65 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}}
main{{max-width:64rem;margin:0 auto;padding:2.5rem 1.25rem 5rem}}
h1{{font-size:clamp(1.9rem,5vw,2.8rem);line-height:1.1;margin:0 0 .4rem;letter-spacing:-.02em}}
h2{{font-size:1.3rem;margin:3rem 0 .6rem;letter-spacing:-.01em}}
.lede{{font-size:1.12rem;color:var(--muted);margin:0 0 2rem;max-width:46rem}}
a{{color:var(--accent)}}
.hero{{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:1.5rem;align-items:start}}
@media (max-width:44rem){{.hero{{grid-template-columns:1fr}}}}
figure.panel{{margin:0}}
figure.panel figcaption{{font-size:.95rem;color:var(--muted);margin-top:.7rem}}
figure.panel strong{{color:var(--fg)}}
.mazebox{{background:var(--maze-paper);border:1px solid var(--line);border-radius:10px;padding:1rem}}
.maze{{display:block;width:100%;height:auto}}
.note{{font-size:.92rem;color:var(--muted);margin-top:1rem}}
dl.stats{{margin:1.75rem 0 0;display:grid;gap:.5rem;
grid-template-columns:repeat(auto-fit,minmax(19rem,1fr));column-gap:2rem}}
.stat{{display:grid;grid-template-columns:6.5rem minmax(0,1fr);gap:.75rem;
border-bottom:1px solid var(--line);padding-bottom:.5rem}}
.stat dt{{color:var(--muted);font-size:.88rem;text-transform:lowercase}}
.stat dd{{margin:0;font-size:.94rem}}
button{{font:inherit;color:var(--fg);background:var(--card);border:1px solid var(--line);
border-radius:7px;padding:.4rem .85rem;cursor:pointer}}
button[aria-pressed=true]{{background:var(--accent);color:var(--maze-paper);border-color:var(--accent)}}
.controls{{display:flex;gap:.5rem;flex-wrap:wrap;margin:.9rem 0 0}}
input[type=range]{{width:100%;accent-color:var(--accent)}}
.frames{{position:relative;max-width:32rem}}
.caption{{font-size:.95rem;color:var(--muted);min-height:4.5rem;margin-top:.7rem}}
.caption strong{{color:var(--fg)}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(13rem,1fr));gap:1.25rem}}
figure.card{{margin:0;background:var(--maze-paper);border:1px solid var(--line);border-radius:10px;
padding:.9rem}}
figure.card figcaption{{font-size:.85rem;color:#5f646b;margin-top:.6rem;line-height:1.5}}
figure.card strong{{color:#1b1d20}}
.ok{{color:#2d6f88}}
table{{width:100%;border-collapse:collapse;font-size:.92rem;margin-top:.5rem;display:block;
overflow-x:auto;white-space:nowrap}}
th,td{{text-align:left;padding:.4rem .7rem .4rem 0;border-bottom:1px solid var(--line)}}
th{{color:var(--muted);font-weight:600}}
p{{max-width:46rem}}
code{{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.92em;
background:var(--card);border:1px solid var(--line);border-radius:4px;padding:.05rem .3rem}}
footer{{margin-top:4rem;padding-top:1.5rem;border-top:1px solid var(--line);color:var(--muted);
font-size:.9rem}}
</style>
<main>
<h1>Mazeglyph</h1>
<p class=lede>A maze whose walls are a QR code. The passages are carved out of the symbol itself,
inside the error correction budget, so the code still scans while the maze is real enough to solve.</p>

<div class=hero>
  <figure class=panel>
    <div class=mazebox>{inline(hero["plain"], "maze")}</div>
    <figcaption><strong>Scan it.</strong> A phone camera reads this as an ordinary QR code and
    opens this page. Nothing about it announces that it is also a maze.</figcaption>
  </figure>
  <figure class=panel>
    <div class=mazebox>{inline(hero["annotated"], "maze")}</div>
    <figcaption><strong>Solve it.</strong> The same symbol with the carved cells shaded and the
    solution traced, from the entrance to the exit. This drawing is not scannable; the one beside
    it is.</figcaption>
  </figure>
</div>
<dl class=stats>{stat_rows(hero)}</dl>
<p class=note>Every number here came from encoding this url and then decoding the carved symbol
again. The last row is that decoder's verdict on the picture above, not a claim written under it.</p>

<h2>Spending the budget</h2>
<p>Error correction is what pays for the maze. Every module the carving flips is damage the decoder
has to repair, and each block of the symbol can absorb a fixed number of broken codewords before it
is lost. Ask for more dead ends and more of that budget goes; ask for too many and the carver
refuses the ones it cannot afford rather than breaking the code.</p>
<p>Drag the slider. The worst block reaches its limit by {series[2]["branches_asked"]} attempts and
everything after that is spent on blocks with room left, which is why refusals start appearing.
Notice the dead ends peak at {max(e["dead_ends"] for e in series)} and then fall to
{series[-1]["dead_ends"]}: opening more passages joins blind alleys into loops, so a bigger carving
is not a harder maze.</p>
<div class=frames>
  <div class=mazebox>{budget_frames}</div>
  <input type=range id=budget min=0 max="{len(series) - 1}" value=0 step=1
         aria-label="how many dead ends to attempt">
  <div class=captions>{budget_captions}</div>
</div>

<h2>The four levels</h2>
<p>The same url at version {LEVEL_VERSION}, at each error correction level. A higher level corrects
more and therefore carves more, and costs payload capacity to do it.</p>
<div class=grid>{level_cards}</div>

<h2>What the carving never touches</h2>
<p>The finder patterns, the timing patterns, the alignment patterns and the format information are
not data and are not covered by error correction. A single flipped module in any of them is not a
damaged symbol, it is a symbol a scanner cannot find or cannot read the settings of. The carver
treats them as walls that cannot be knocked through, and the measurement counts it.</p>
<table>
<thead><tr><th>version</th><th>function modules</th><th>changed by carving</th></tr></thead>
<tbody>{never_rows}</tbody>
</table>

<h2>Every version, measured</h2>
<table>
<thead><tr><th>symbol</th><th>budget per block</th><th>worst block used</th><th>modules flipped</th>
<th>dead ends</th><th>refused</th><th>decodes to the url</th></tr></thead>
<tbody>{version_rows}</tbody>
</table>

<footer>
<p>Built by <code>scripts/build_page.py</code> from the same encoder, carver and decoder the command
line uses. Nothing on this page is fetched from anywhere.
<a href="https://github.com/JesseRWeigel/mazeglyph">Source and the full verification suite</a>.</p>
</footer>
</main>
<script>
(function () {{
  var slider = document.getElementById('budget');
  function show(n) {{
    document.querySelectorAll('[data-frame]').forEach(function (el) {{
      el.hidden = Number(el.dataset.frame) !== n;
    }});
  }}
  slider.addEventListener('input', function () {{ show(Number(slider.value)); }});
  show(0);
}})();
</script>
</html>
"""


def main() -> int:
    measured_path = ROOT / "docs" / "measured.json"
    measured = json.loads(measured_path.read_text(encoding="utf-8"))

    hero = build(URL, "H", branches=240, seed=7)
    series = [build(URL, "H", branches=b, seed=7) for b in BUDGET_SERIES]
    levels = [build(URL, level, branches=400, seed=3, version=LEVEL_VERSION) for level in LEVELS]

    # A symbol that does not decode is a defect, and it must not reach the page quietly.
    bad = [e for e in [hero, *series, *levels] if not e["decodes_to_the_url"]]
    if bad:
        for e in bad:
            print(f"version {e['version']} level {e['level']} branches {e['branches_asked']}: "
                  f"{verdict(e)}", file=sys.stderr)
        print(f"{len(bad)} of the symbols on the page do not decode to the url", file=sys.stderr)
        return 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    (OUT.parent / ".nojekyll").write_text("", encoding="utf-8")
    OUT.write_text(page(hero, series, levels, measured), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size / 1024:.1f} KB), "
          f"{1 + len(series) + len(levels)} symbols, every one decoded back to the url")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
