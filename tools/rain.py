#!/usr/bin/env python3
"""Builds the code rain look into hooks/rain-scene.js.

Run from anywhere:  python3 -I tools/rain.py
Change a number below and run again; the mod reloads on its own.
  --out <file>   write the module somewhere else (to try a change without touching the mod)
  --svg <file>   also write the bare scene, to look at or to hand to a test harness

The picture: code falling through a deep, dark space, seen through a lens.
Far columns are small, slow and out of focus. Nearer ones are a little larger,
quicker, sharp and bright, each led by a white-hot glyph with a glow. Now and
then a column too close to focus on sweeps past as a soft blur. Lengths,
places, speeds, sizes and brightness are all drawn at random from SEED.

How it is built, and why. The desktop app's rules are in build_scenes.py: it
draws the whole scene again every frame, and puts a still frame back for good
if a frame costs it too much.

- A column is ONE upright vertical run of text (writing-mode), not a glyph per
  x/y. A run of twenty glyphs costs the app about a fifth of what they cost
  placed one by one. Its fade is a few tspans of solid color: a gradient fill
  on vertical text comes out wrong in Chrome, and costs more. A run is
  anchored at its end, where its head is, so the glow and the flicker land on
  the head however the browser spaces the glyphs.
- Each out-of-focus plane is drawn once into a <pattern> tile, blur and all,
  and the tile is slid down inside a tall rect. Chrome keeps the drawn tile, so
  a plane of a hundred and more columns costs the app one rect a frame, and the
  blur, far too dear on moving text, is paid once. Nothing inside a tile may
  animate, or the tile is drawn again every frame.
- The sharp columns are real text, in lanes. Each lane has its own speed and
  holds one to three streaks, and the head glyph of the near ones flickers
  between two characters.
- Nothing hangs from the top when the motion is taken away: each lane's
  transform attribute puts it where its animation has it at the first frame,
  and a tile is full of columns wherever it sits.
- The app's flash check sees the picture as 64 by 40 cells and counts a cell
  that swings bright and dark twice inside a second. Only a streak with a glow
  is bright enough to count, so no two of those share a cell, and the streaks
  in one lane follow each other more than a second apart.
- A phone gets no tiles (they are large for a phone's memory): RAIN_PORTRAIT
  hides the planes and shows a few plain far lanes kept for it instead.
"""
import html
import json
import math
import pathlib
import random
import sys

TOOLS = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))  # python3 -I leaves the script's own folder off the import path
sys.dont_write_bytecode = True  # and leave no __pycache__ behind in the mod
from build_scenes import H, LIMIT, W, f, root, scene_problems, with_portrait  # noqa: E402

HOOKS = TOOLS.parent / "hooks"
SEED = 2026

# How far apart the glyphs of an upright vertical run of ui-monospace sit.
# The font's line height (1.17 em) less the letter-spacing below would make it
# 1.02 em, but the browser rounds the font's ascent and descent to whole pixels
# at the size it draws at, so the real step is anywhere from 0.93 to 1.11 em
# and changes with the window (measured in Chrome). So nothing here trusts it:
# every streak is anchored at its END (text-anchor), where its head is.
TRACK = -0.15  # letter-spacing, em
LONGEST = 1.11  # the longest the step comes out, em
HEAD = 0.44  # a streak's last glyph has its middle this far above the streak's end, em

# What falls: hex digits, code symbols and a few plain letter and math shapes.
DIGITS = "0123456789"
HEX = "ABCDEFabcdef"
CODE = "{}[]()<>=+-*/;:#$%&|~^!?@_"
SHAPES = "λΣΩπΔΦΨθμξЖЯФДЦЩЭЮБИЛ∞≠≈±×÷¬∂√∫◊∑∏≤≥"

# The chat column's middle in the 1600-wide picture (about 52% across). The
# brightest streaks are thinned out behind it; the app's glass does the rest.
CHAT_X = 825

# Ink, by plane, as CSS classes.
INK = {
    # deep plane, blurred hard: body, bright, hot
    "a": "#1e9449", "b": "#43e480", "c": "#d2ffe2",
    # far plane, blurred a little: tail, body, head
    "e": "#11622f", "g": "#209e4d", "i": "#5ff394",
    # soft middle plane, and the phone's far lanes: tail, body, bright, head
    "j": "#0c4a23", "k": "#167c3b", "o": "#29ba5e", "p": "#86ffb1",
    # sharp middle lanes: tail, body, bright, head
    "q": "#0d5628", "r": "#198d43", "t": "#30cb68", "u": "#8dffb6",
    # near lanes: tail, body, bright, hot, and the white head
    "w": "#0f6130", "x": "#1d9f4d", "y": "#35db71", "A": "#62ff9a", "h": "#effff4",
    # the odd pale streak: tail, body
    "B": "#458f68", "C": "#a2e6c0",
    # the plane in front of the lens
    "D": "#38c26e",
}

# A recipe lists a streak from its head back to its tail as (ink, amount):
# a whole number is that many glyphs, a fraction that share of the streak, and
# the last entry takes what is left.
PLANES = {
    # key: tile height, seconds to fall one tile, blur, columns, font sizes, usual length,
    #      least gap between columns, recipes, and (ink, chance) of one lit glyph in the tail
    "pa": dict(tile=1240, seconds=44, blur=2.2, count=150, size=(8, 9.5), usual=16, gap=4,
               recipes=[[("a", 1.0)], [("a", 1.0)], [("b", 2), ("a", 1.0)], [("c", 1), ("b", 2), ("a", 1.0)]]),
    "pb": dict(tile=1150, seconds=29, blur=0.9, count=120, size=(8.5, 10), usual=14, gap=6,
               recipes=[[("i", 1), ("g", 0.45), ("e", 1.0)], [("g", 0.4), ("e", 1.0)]]),
    "pc": dict(tile=1320, seconds=24, blur=0, count=110, size=(9, 10.5), usual=13, gap=8,
               recipes=[[("p", 1), ("k", 0.5), ("j", 1.0)], [("o", 2), ("k", 0.4), ("j", 1.0)],
                        [("k", 0.5), ("j", 1.0)]], spark=("o", 0.18)),
}
# The plane in front of the lens: few, large, fast, and blurred past reading. It keeps to the sides.
FRONT = dict(tile=2600, seconds=12.6, blur=4.5, count=20, size=(21, 26), usual=7, gap=48,
             recipes=[[("D", 1.0)]])

LANES = [
    # Painted in this order. count, font sizes, seconds to fall the height of the picture,
    # usual length, how many streaks a lane may hold, recipes, the share kept behind the chat
    # column (there the lanes keep that much further apart), least gap to any other lane, the
    # head's glow (width, height in em), the chance a head flickers, and (ink, chance) of one
    # lit glyph in the tail.
    # The lanes with a glow keep 26 or more apart. The app's flash check looks at the picture
    # in cells 25 wide, and counts a cell that goes bright and dark twice inside a second: no
    # two glowing lanes may share a cell.
    dict(count=68, size=(10, 11.5), crossing=(10.5, 17), usual=12, streaks=[1, 1, 2, 2, 3], floor=0.75, gap=10,
         recipes=[[("u", 1), ("r", 0.45), ("q", 1.0)], [("t", 1), ("r", 0.4), ("q", 1.0)], [("r", 0.5), ("q", 1.0)]],
         spark=("t", 0.12)),
    dict(count=38, size=(12, 13.5), crossing=(6.8, 10), usual=12, streaks=[1, 2, 2], floor=0.5, gap=26,
         recipes=[[("h", 1), ("A", 1), ("y", 0.3), ("x", 0.3), ("w", 1.0)]] * 4
         + [[("A", 1), ("y", 0.3), ("x", 0.3), ("w", 1.0)], [("h", 1), ("C", 0.5), ("B", 1.0)]],
         glow=(1.25, 2.7), flicker=0.75),
    dict(count=10, size=(14.5, 15.5), crossing=(4.8, 6.4), usual=13, streaks=[1, 1, 2], floor=0.3, gap=30,
         recipes=[[("h", 1), ("A", 2), ("y", 0.3), ("x", 0.3), ("w", 1.0)]], glow=(1.5, 3.4), flicker=1.0),
]
# Far lanes for a phone, which gets no planes: shown by RAIN_PORTRAIT alone.
# They sit between the sharp lanes, a little closer to them than those sit to each other.
PHONE_LANES = dict(count=30, size=(9, 10.5), crossing=(17, 26), usual=13, streaks=[1, 2, 2], floor=1.0, gap=12,
                   recipes=[[("p", 1), ("k", 0.5), ("j", 1.0)], [("o", 2), ("k", 0.4), ("j", 1.0)],
                            [("k", 0.5), ("j", 1.0)]], span=(400, 1200), also="ph", clear=7)

FLICKER = [0.34, 0.46, 0.62, 0.86]  # seconds for a head to show both of its glyphs


def glyphs(rnd, n):
    out, last = [], ""
    for _ in range(n):
        r = rnd.random()
        pool = DIGITS if r < 0.36 else HEX if r < 0.56 else CODE if r < 0.80 else SHAPES
        ch = rnd.choice(pool)
        while ch == last:
            ch = rnd.choice(pool)
        out.append(ch)
        last = ch
    return "".join(out)


def esc(text):
    return html.escape(text, quote=False)


def streak_length(rnd, low, high, usual):
    """How many glyphs long: mostly near `usual`, now and then much longer."""
    n = math.exp(rnd.gauss(math.log(usual), 0.55))
    return int(max(low, min(high, round(n))))


def scatter(rnd, count, low, high, gap, taken=(), share=None, clear=None):
    """Up to `count` x positions, none closer than `gap` to another, nor than `clear` to any in `taken`.

    share(x), between 0 and 1, thins them out: where it is a half, half as many are tried
    and they keep twice as far apart.
    """
    clear = gap if clear is None else clear
    xs = []
    for _ in range(count * 60):
        if len(xs) == count:
            break
        x = rnd.uniform(low, high)
        part = share(x) if share else 1
        if rnd.random() > part:
            continue
        if all(abs(x - other) * part >= gap for other in xs) and all(abs(x - other) * part >= clear for other in taken):
            xs.append(x)
    return xs


def near_chat(x, floor, inner=190, outer=360):
    """The share of streaks kept at x: `floor` behind the chat column, all of them at the sides."""
    d = abs(x - CHAT_X)
    t = max(0.0, min(1.0, (d - inner) / (outer - inner)))
    return floor + (1 - floor) * t * t * (3 - 2 * t)


class Sizes:
    """Font sizes as classes, one per half unit."""

    def __init__(self):
        self.used = {}

    @staticmethod
    def snap(size):
        return round(size * 2) / 2

    def cls(self, size):
        half = round(size * 2)
        return self.used.setdefault(half, f"z{half}")

    def css(self):
        return "".join(f".{name}{{font-size:{f(half / 2)}px}}" for half, name in sorted(self.used.items()))


def streak(rnd, n, recipe, spark=None):
    """A streak of n glyphs as (ink, text) runs, tail first."""
    runs, left = [], n
    for ink, amount in recipe:
        take = amount if isinstance(amount, int) else max(1, round(n * amount))
        take = min(take, left)
        runs.append((ink, take))
        left -= take
        if left == 0:
            break
    if left:
        runs[-1] = (runs[-1][0], runs[-1][1] + left)
    runs.reverse()
    if spark and runs[0][1] >= 4 and rnd.random() < spark[1]:
        ink, take = runs[0]
        at = rnd.randrange(1, take - 1)
        runs[0:1] = [(ink, at), (spark[0], 1), (ink, take - at - 1)]
    return [(ink, glyphs(rnd, take)) for ink, take in runs]


# ----------------------------------------------------------------------------
# The out-of-focus planes: each drawn once into a pattern tile, then slid down.
# ----------------------------------------------------------------------------
def plane(rnd, sizes, key, *, tile, seconds, blur, count, size, usual, recipes, gap, spark=None, share=None):
    """One depth plane. Returns (defs, body)."""
    margin = 3 * blur + 6  # how far a column's blur reaches past it
    columns, copies = [], []
    for i, x in enumerate(scatter(rnd, count, 14, W - 14, gap, (), share)):
        em = sizes.snap(rnd.uniform(*size))
        n = streak_length(rnd, 3, 44, usual)
        end = rnd.uniform(0, tile)
        runs = streak(rnd, n, rnd.choice(recipes), spark)
        inner = esc(runs[0][1]) + "".join(f'<tspan class="{ink}">{esc(t)}</tspan>' for ink, t in runs[1:])
        # a column that crosses the tile's edge is drawn again one tile away, so the tiles join
        wraps_up = end - n * LONGEST * em - margin < 0
        wraps_down = end + margin > tile
        ident = f' id="{key}{i}"' if wraps_down or wraps_up else ""
        columns.append(
            f'<text{ident} class="{sizes.cls(em)} {runs[0][0]}" x="{f(x)}" y="{f(end)}">{inner}</text>'
        )
        if wraps_down:
            copies.append(f'<use href="#{key}{i}" y="-{tile}"/>')
        if wraps_up:
            copies.append(f'<use href="#{key}{i}" y="{tile}"/>')
    content = "".join(columns) + "".join(copies)
    defs = ""
    if blur:
        defs += (
            f'<filter id="{key}b" filterUnits="userSpaceOnUse" x="-30" y="-30" width="{W + 60}" '
            f'height="{tile + 60}"><feGaussianBlur stdDeviation="{f(blur)}"/></filter>'
        )
        content = f'<g filter="url(#{key}b)">{content}</g>'
    defs += f'<pattern id="{key}" width="{W}" height="{tile}" patternUnits="userSpaceOnUse">{content}</pattern>'
    body = (
        f'<rect class="pl" style="--d:{f(seconds)}s;--p:-{f(rnd.uniform(0, seconds))}s;--t:{tile}px" '
        f'y="-{tile}" width="{W}" height="{H + tile}" fill="url(#{key})"/>'
    )
    return defs, body


# ----------------------------------------------------------------------------
# The sharp lanes: real text, each lane with its own speed.
# ----------------------------------------------------------------------------
def fall(rnd, length, crossing):
    """The timing of something `length` tall that falls the height of the picture in `crossing` s.

    It starts wholly above the top and ends wholly below the foot. The transform
    attribute puts it where the first frame has it, which is also where it
    rests when the app takes the motion away.
    """
    seconds = (H + length) * crossing / H
    phase = rnd.random()
    place = -length + phase * (H + length)
    return (
        f'style="--d:{f(seconds)}s;--p:-{f(phase * seconds)}s;--s:-{f(length)}px" '
        f'transform="translate(0 {f(place)})"'
    )


def lanes(rnd, sizes, taken, *, count, size, crossing, usual, streaks, recipes, floor, gap, glow=None,
          flicker=0.0, spark=None, span=(10, W - 10), also="", clear=None):
    """Lanes of sharp falling text. Returns the markup; adds the x it uses to `taken`."""
    out = []
    xs = scatter(rnd, count, span[0], span[1], gap, taken, lambda x: near_chat(x, floor), clear)
    taken.extend(xs)
    also = f" {also}" if also else ""
    for x in xs:
        em = sizes.snap(rnd.uniform(*size))
        seconds = rnd.uniform(*crossing)
        text, glows, end = [], [], 0.0
        for j in range(rnd.choice(streaks)):
            n = streak_length(rnd, 3, 40, usual)
            # Room for the streak at its longest, below the one before it, and a gap that takes
            # more than a second to pass: two bright streaks through one spot inside a second
            # is what the app's flash check counts.
            end += n * LONGEST * em + (rnd.uniform(1.15, 2.6) * H / seconds if j else 0.0)
            at = f' y="{f(end)}"'
            runs = streak(rnd, n, rnd.choice(recipes), spark)
            for k, (ink, t) in enumerate(runs):
                here = at if k == 0 else ""
                if k == len(runs) - 1 and rnd.random() < flicker:
                    # The head's cell shows two glyphs in turn. The second is a run of its own
                    # that ends where the streak ends, so it lands on the head whatever the step.
                    m = rnd.randrange(len(FLICKER))
                    other = glyphs(rnd, 1)
                    if other == t[-1]:
                        other = "4" if other == "7" else "7"
                    if len(t) > 1:
                        text.append(f'<tspan class="{ink}"{here}>{esc(t[:-1])}</tspan>')
                        here = ""
                    text.append(
                        f'<tspan class="{ink} m{m}"{here}>{esc(t[-1])}</tspan>'
                        f'<tspan class="{ink} n{m}"{at}>{esc(other)}</tspan>'
                    )
                else:
                    text.append(f'<tspan class="{ink}"{here}>{esc(t)}</tspan>')
            if glow:
                # the glow's bright point is three quarters of the way down it: put that on the head
                wide, tall = glow
                cy = end - HEAD * em - tall * em * 0.5
                glows.append(f'<ellipse cx="{f(x)}" cy="{f(cy)}" rx="{f(wide * em)}" ry="{f(tall * em)}"/>')
        # the lane ends a little below its last head: under the glow, or the glyph's own descent
        timing = fall(rnd, end + (glow[1] * 0.5 if glow else 0.3) * em, seconds)
        if glows:
            out.append(
                f'<g class="ln{also}" {timing}>{"".join(glows)}'
                f'<text class="{sizes.cls(em)}" x="{f(x)}">{"".join(text)}</text></g>'
            )
        else:
            out.append(f'<text {timing} class="ln {sizes.cls(em)}{also}" x="{f(x)}">{"".join(text)}</text>')
    return "".join(out)


def curtain(rnd, n=46):
    """A dim curtain behind everything: random soft vertical bands, as one gradient."""
    stops, x = [], 0.0
    while x < 1:
        shade = rnd.choice(["#010402", "#010402", "#021208", "#03190c", "#042311", "#010703"])
        stops.append(f'<stop offset="{x:.3f}" stop-color="{shade}"/>')
        x += rnd.uniform(0.5, 1.6) / n
    return f'<linearGradient id="cu" x1="0" y1="0" x2="1" y2="0">{"".join(stops)}</linearGradient>'


def code_rain(seed=SEED):
    rnd = random.Random(seed)
    sizes = Sizes()
    defs, far = [], []
    for key, spec in PLANES.items():
        d, b = plane(rnd, sizes, key, **spec)
        defs.append(d)
        far.append(b)
    d, front = plane(rnd, sizes, "pf", share=lambda x: near_chat(x, 0.08, 280, 520), **FRONT)
    defs.append(d)

    # The largest, fastest lanes pick their places first; the smaller ones fit in around them.
    taken, sharp = [], []
    for spec in reversed(LANES):
        sharp.insert(0, lanes(rnd, sizes, taken, **spec))
    phone = lanes(rnd, sizes, taken, **PHONE_LANES)

    defs.append(
        curtain(rnd)
        + '<radialGradient id="hz" cx=".5" cy=".34" r=".72">'
        '<stop offset="0" stop-color="#0c3a1d" stop-opacity=".55"/>'
        '<stop offset=".55" stop-color="#062412" stop-opacity=".25"/>'
        '<stop offset="1" stop-color="#010402" stop-opacity="0"/></radialGradient>'
        '<radialGradient id="gl" fx=".5" fy=".75"><stop offset="0" stop-color="#c9ffdd" stop-opacity=".55"/>'
        '<stop offset=".16" stop-color="#5dff97" stop-opacity=".3"/>'
        '<stop offset=".5" stop-color="#2bff78" stop-opacity=".1"/>'
        '<stop offset="1" stop-color="#2bff78" stop-opacity="0"/></radialGradient>'
        '<radialGradient id="vg" cx=".5" cy=".5" r=".78">'
        '<stop offset=".5" stop-color="#000" stop-opacity="0"/>'
        '<stop offset="1" stop-color="#000" stop-opacity=".62"/></radialGradient>'
    )
    scene = (
        f'<defs>{"".join(defs)}</defs>'
        f'<rect width="{W}" height="{H}" fill="#010402"/>'
        f'<rect width="{W}" height="{H}" fill="url(#cu)" fill-opacity=".8"/>'
        f'<rect class="hz" width="{W}" height="{H}" fill="url(#hz)"/>'
        f'{"".join(far)}{phone}{"".join(sharp)}{front}'
        f'<rect class="dim" width="{W}" height="{H}" fill="#010402"/>'
        f'<rect width="{W}" height="{H}" fill="url(#vg)"/>'
    )
    style = (
        "text{font-family:ui-monospace,monospace;font-weight:600;writing-mode:vertical-rl;"
        f"text-orientation:upright;letter-spacing:{TRACK}em;text-anchor:end}}"
        + sizes.css()
        + "".join(f".{name}{{fill:{color}}}" for name, color in INK.items())
        # the white head's rim of light, and the glow under it
        + ".h{stroke:#43ff88;stroke-opacity:.38;stroke-width:2.4px;stroke-linejoin:round;paint-order:stroke}"
        "ellipse{fill:url(#gl)}"
        # a plane slides down by one tile; a lane falls from above the top to below the foot
        ".pl{animation:pl var(--d) var(--p) linear infinite}"
        "@keyframes pl{to{transform:translateY(var(--t))}}"
        ".ln{animation:ln var(--d) var(--p) linear infinite}"
        f"@keyframes ln{{from{{transform:translateY(var(--s))}}to{{transform:translateY({H}px)}}}}"
        # a flickering cell: its two glyphs take turns
        "@keyframes m{0%{visibility:visible}50%{visibility:hidden}}"
        + ",".join(f".n{i}" for i in range(len(FLICKER))) + "{visibility:hidden}"
        + "".join(
            f".m{i},.n{i}{{animation:m {d}s steps(1) infinite}}.n{i}{{animation-delay:-{d / 2:.2f}s}}"
            for i, d in enumerate(FLICKER)
        )
        # the haze behind it all breathes, slowly
        + ".hz{animation:hz 13s ease-in-out infinite alternate}@keyframes hz{to{fill-opacity:.6}}"
        ".ph,.dim{display:none}"
        "@media (prefers-reduced-motion:reduce){*{animation:none!important}}"
    )
    return root(scene, style)


# A phone shows only the middle strip, with the chat over all of it. It gets no
# planes (a tile the size of the picture is a lot of memory there) but its own
# far lanes, and the whole scene a little dimmer.
RAIN_PORTRAIT = (
    "@media (max-aspect-ratio:1/1),(max-height:480px)"
    "{.pl{display:none}.ph,.dim{display:inline}.dim{fill-opacity:.45}}"
)

RAIN_COLORS = {
    "label": "Code rain",
    # the accent is the rain's own green; danger stays red, success a lime green, warning amber
    "roles": {"accent": "#30e67a", "danger": "#ff5f56", "success": "#9be22d", "warning": "#f2c94c", "pro": "#4fd6ff"},
    "dark": {
        "gray": {
            "anchors": {
                "surface-0": "#040a06",
                "surface-1": "#08120b",
                "surface-2": "#0c1910",
                "surface-3": "#101f14",
                "text-primary": "#ddf9e3",
                "text-secondary": "#a9deb4",
                "text-muted": "#80ba8d",
            },
        },
    },
}

RAIN_GLASS = {"blur": 8, "tint": "#030805", "opacity": 0.68}

RAIN_ALT = "Green code characters falling in columns through a dark space, the far ones soft and out of focus"


def main():
    args = sys.argv[1:]

    def option(name):
        return args[args.index(name) + 1] if name in args else None

    svg = code_rain()
    phone = with_portrait(svg, RAIN_PORTRAIT)
    problems = scene_problems(svg)
    if problems:
        raise SystemExit("CODE_RAIN would not move in the desktop app:\n  " + "\n  ".join(problems))
    if len(phone) > LIMIT:
        raise SystemExit(f"CODE_RAIN with its portrait rules is {len(phone):,} characters, over the {LIMIT:,} limit")
    # the phone's copy is allowed its size @media, and nothing else the app refuses
    phone_problems = [p for p in scene_problems(phone) if "@media" not in p]
    if phone_problems:
        raise SystemExit("CODE_RAIN with its portrait rules is broken:\n  " + "\n  ".join(phone_problems))
    js = "\n".join([
        "// The code rain look. tools/rain.py writes this file; edit that, not this.",
        f"export const CODE_RAIN = {json.dumps(svg)}",
        f"export const CODE_RAIN_PORTRAIT = {json.dumps(RAIN_PORTRAIT)}",
        f"export const RAIN_COLORS = {json.dumps(RAIN_COLORS, indent=2)}",
        f"export const RAIN_GLASS = {json.dumps(RAIN_GLASS)}",
        f"export const RAIN_ALT = {json.dumps(RAIN_ALT)}",
        "",
    ])
    out = pathlib.Path(option("--out") or HOOKS / "rain-scene.js")
    out.write_text(js, encoding="utf-8")
    if option("--svg"):
        pathlib.Path(option("--svg")).write_text(svg, encoding="utf-8")
    print(
        f"CODE_RAIN: {len(svg):,} characters ({len(svg) / LIMIT:.0%} of the {LIMIT:,} limit), "
        f"{svg.count('<pattern')} planes, {svg.count('<text')} columns, {svg.count('<tspan')} runs -> {out}"
    )


if __name__ == "__main__":
    main()
