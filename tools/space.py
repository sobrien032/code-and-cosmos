#!/usr/bin/env python3
"""Builds the deep space look into hooks/space-scene.js: a black hole whose
shadow, photon ring and accretion disk rise around the message box, with
small galaxies, star clusters and a nebula far behind it.

Run from anywhere:   python3 -I tools/space.py
To look first:       python3 -I tools/space.py --preview <folder>   (writes two SVGs there, not the mod)

The rules a scene has to keep are in tools/build_scenes.py (scene_problems).
This script refuses to write a scene that breaks one, because the desktop app
would then show it as a still picture.

What the app charges for. It redraws the whole scene every frame into a tiny
canvas, 64 by 40, and stops the motion for good if that averages over 5.56 ms,
or if a patch of that canvas flickers. Measured here:
- The time goes on how much stroked line there is (twice over when the line
  is painted with a gradient) and hardly at all on how many things move, or
  on dots, or on a gradient's number of stops. So the disk's fine rings are
  free (they are stops in the gradients that fill it), stars are dots, and
  soft glows are filled ellipses, never a blur filter.
- On that canvas a stroke of the disk under 23 units wide comes out thinner
  than a pixel at any window shape, and is drawn as a hairline that dims
  smoothly as it moves. A thin FILLED shape is not: it is sampled at a few
  points, so it flickers from frame to frame as it moves, and enough of them
  trip the flicker check. So everything that moves in the disk is a stroke
  of 22 units or less, and nothing that moves there is a thin fill.
- An arc that slides along its own circle changes nothing the eye can see.
  To show a ring turning, what rides on it has to cross it on a slant.
"""
import json
import math
import pathlib
import random
import re
import sys
from xml.dom import minidom
from xml.parsers.expat import ExpatError

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))  # python3 -I leaves the script's folder off the path
sys.dont_write_bytecode = True  # and no __pycache__ folder left in the mod

from build_scenes import LIMIT, Timing, f, scene_problems, with_portrait  # noqa: E402

HOOKS = HERE.parent / "hooks"

# Where the message box sits in the desktop window, measured on a screenshot.
BOX_TOP = 75         # points from the foot of the window to the top edge of the message box
OFF_CENTER = 27.5    # points the chat column sits right of the window's middle
PHONE_SIZE = 1.875   # how much larger the hole is drawn on a phone, where the scene is narrow


# ----------------------------------------------------------------------------
# Small helpers
# ----------------------------------------------------------------------------
def f2(n):
    """A number to two places, as short as it goes (for scales and opacities)."""
    s = f"{n:.2f}".rstrip("0").rstrip(".")
    if s.startswith("0."):
        s = s[1:]
    elif s.startswith("-0."):
        s = "-" + s[2:]
    return "0" if s in ("", "-0", "-") else s


def f4(n):
    """A number to four places, for gradient offsets."""
    s = f"{n:.4f}".rstrip("0").rstrip(".")
    return (s[1:] if s.startswith("0.") else s) or "0"


def _lin(v):
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def _srgb(v):
    v = min(1.0, max(0.0, v))
    return 12.92 * v if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055


def rgb(hex_color):
    return tuple(_lin(int(hex_color[i:i + 2], 16) / 255) for i in (1, 3, 5))


def hex_of(linear):
    return "#" + "".join(f"{round(_srgb(c) * 255):02x}" for c in linear)


def stops(pairs, color=None):
    """Gradient stops from (offset, alpha) with one color, or (offset, color, alpha)."""
    out = []
    for p in pairs:
        o, c, a = (p[0], color, p[1]) if color else p
        alpha = "" if a >= 1 else f' stop-opacity="{f2(a)}"'
        out.append(f'<stop offset="{f2(o)}" stop-color="{c}"{alpha}/>')
    return "".join(out)


# ----------------------------------------------------------------------------
# The black hole. Its own frame: the hole's center is (0, 0) and one unit is
# one point on a 2000 x 1195 window. Everything is laid out from three
# numbers: the shadow's radius, the disk's tilt, and how hard the hole bends
# the light that comes over its top.
#
# How it is drawn. The disk is flat rings of gas. The near half of each ring
# is a circle squashed flat (TILT). The far half is hidden behind the hole,
# but its light bends over the top, so that half is the same circle squashed
# much less: arch(r) high instead of TILT * r. The two halves meet on the
# hole's level line, where a squash changes nothing, so the join is exact.
#
# The disk is light, so it is added to the sky: glow and streaks are drawn
# opaque on black inside one group, a multiply overlay dims and reddens the
# side that turns away from us (Doppler), and the group is summed into the
# picture. Black in there means "no light", not "a black thing".
#
# What moves: the disk is cut into zones, and each zone of gas (bands of light
# and shade, streaks, hot spots, all slanted across the rings) turns at its
# own speed, the inner ones fastest, like a slow whirlpool. Two spiral arms
# start whole and are wound up and sheared by it. A broad soft shadow goes
# round the outer disk. Pearls of light run round the photon ring. A few
# streamers spiral in, and the whole hole rocks a little.
# ----------------------------------------------------------------------------
R = 320.0            # radius of the shadow
TILT = 0.16          # the near side of the disk, flattened: 0 would be edge-on
BEND = 243.0         # light bending: sets how high the far side arches over the hole
R_IN, R_OUT = 1.28 * R, 3.3 * R
ZONES = 20           # zones of gas, each turning at its own speed
T_IN = 26.0          # seconds for the innermost zone to go round once
SPIN = 2.05          # how the turn slows going outward: seconds per turn grow as radius ** SPIN
                     # (1.5 would be Kepler's; this is a little steeper, so the rim takes three minutes)
T_SHADE = 110.0      # seconds for the broad shadow in the outer disk to go round once
SHADE_FROM = 215     # where the shadow starts, degrees round from the left: on the right, the dim side


def arch(r):
    """How high the far side of the disk at radius r appears above the hole.

    A point directly behind the hole at distance r would be seen at r * TILT
    if light went straight. The hole bends it (thin-lens estimate), lifting
    the far half of every ring into an arch over the shadow.
    """
    y0 = TILT * r
    return (y0 + math.sqrt(y0 * y0 + 4 * BEND * r)) / 2


# The disk's own light by radius (in units of R_IN), as it would look with no
# Doppler shift: dark at the very edge of the gap, white hot just outside it,
# then gold, amber and embers. It is drawn opaque inside a group that is added
# to the sky as light, so black here means "nothing", not "a black thing".
V_OUT = R_OUT / R_IN
GLOW = [(0.90, "#000000"), (0.95, "#6b3310"), (1.00, "#ffd28a"), (1.06, "#fff4dc")] + [
    (1 + share * (V_OUT - 1), color) for share, color in [
        (.10, "#ffe19c"), (.19, "#ffc056"), (.30, "#fa9a32"), (.42, "#e87a24"), (.54, "#c6551b"),
        (.65, "#9a3714"), (.75, "#6c230e"), (.84, "#431509"), (.92, "#210a04"), (1, "#000000"),
    ]
]


def glow_at(v):
    for (v0, c0), (v1, c1) in zip(GLOW, GLOW[1:]):
        if v <= v1:
            t = min(1, max(0, (v - v0) / (v1 - v0)))
            return tuple(x + (y - x) * t for x, y in zip(rgb(c0), rgb(c1)))
    return (0, 0, 0)


def lit(linear, gain, toward=None, share=0.0):
    """A streak's color: the glow under it made brighter, and pulled a little toward white gold."""
    c = [min(1.0, x * gain) for x in linear]
    if toward:
        c = [x + (y - x) * share for x, y in zip(c, rgb(toward))]
    return hex_of(c)


def at(r, a):
    """The point at radius r, `a` radians clockwise of straight up."""
    return r * math.sin(a), -r * math.cos(a)


def arc_d(r, mid, length, climb=0.0):
    """One arc of a ring, `length` radians long, centered `mid` radians clockwise of straight up.
    With `climb` it ends that much farther out than it starts, so it trails back (clockwise,
    against the turn) as it goes outward, the way gas shears in a disk. That slant is what
    lets the eye see a ring turn: an arc that only slides along its own circle shows nothing."""
    length = min(length, 5.6)
    (x0, y0), (x1, y1) = at(r - climb / 2, mid - length / 2), at(r + climb / 2, mid + length / 2)
    return f"M{round(x0)} {round(y0)}A{round(r)} {round(r)} 0 {int(length > math.pi)} 1 {round(x1)} {round(y1)}"


def strands(rnd, r0, count, length, gap, slant, trail=0.0):
    """A few neighbouring streaks across the top of their ring, each climbing outward by
    `slant` of its length as it trails back. With `trail` each sits a little behind the
    one inside it; without, they run side by side and end together, as one broad band."""
    out = []
    for j in range(count):
        r = r0 + j * gap
        size = length * (rnd.uniform(.7, 1.2) if j and trail else 1)
        out.append(arc_d(r, trail * (r - r0) / r0, size, r * size * slant))
    return "".join(out)


# How a streak fades along its length, from its leading end to its trailing end.
FADES = [
    [(0, 0), (.12, 1), (.4, .5), (1, 0)],               # a bright head and a long tail
    [(0, 0), (.25, .65), (.5, 1), (.75, .65), (1, 0)],  # brightest in the middle
]
HEATS = 4            # streaks and bands come in this many colors, from white hot to ember
HOT_ZONES = (1, 3, 6, 9, 12, 15)   # zones that carry a hot spot
STREAMERS = 3        # clumps of gas spiralling in
ARMS_WIND = 4.2      # how tightly the two spiral arms wind: radians of turn per e-fold of radius
ARMS_START = -2.5    # where the first arm leaves the inner edge, radians clockwise of straight up
DISK_FOOT = round(TILT * R_IN)   # how far below the hole's level line the near side's inner edge crosses


def black_hole(rnd):
    defs, far, near = [], [], []
    q = (R_OUT / R_IN) ** (1 / ZONES)
    x0 = -R_OUT - 24
    top = -arch(R_OUT) - 24
    foot = TILT * R_OUT + 24

    # --- the glow under the streaks -------------------------------------------------
    # The disk's light by radius, with fine lighter and darker rings in it (the
    # grooves). Far side: one filled ellipse per step of GLOW, largest first; the
    # next one in covers its middle. Near side: the same colors as one circle,
    # squashed flat. Both read the same list, so they agree along the level line.
    rim = [v * R_IN for v, _ in GLOW]
    flat = [0] + [arch(rim[j - 1]) / arch(rim[j]) * rim[j] for j in range(1, len(GLOW))]

    def smooth(rho):
        """GLOW at this radius. Each step holds its inner color out to `flat`, where
        the far side's ellipse comes out from under the one inside it, then ramps."""
        for j in range(1, len(GLOW)):
            if rho <= rim[j]:
                t = min(1, max(0, (rho - flat[j]) / (rim[j] - flat[j])))
                return tuple(x + (y - x) * t for x, y in zip(rgb(GLOW[j - 1][1]), rgb(GLOW[j][1])))
        return (0, 0, 0)

    marks, rho = [], rim[0]
    while rho < R_OUT:
        roll = rnd.random()
        level = rnd.uniform(.5, .66) if roll < .1 else rnd.uniform(1.2, 1.38) if roll < .2 else \
            min(1.2, max(.74, rnd.gauss(1, .09)))
        marks.append((rho, level))
        rho += rnd.uniform(3.5, 12)
    marks.append((R_OUT, 1))
    points = sorted(set([m[0] for m in marks] + rim + flat[1:]))

    def groove(rho):
        for (r0, l0), (r1, l1) in zip(marks, marks[1:]):
            if rho <= r1:
                return l0 + (l1 - l0) * min(1, max(0, (rho - r0) / (r1 - r0)))
        return 1

    def shade(rho):
        return hex_of([min(1.0, c * groove(rho)) for c in smooth(rho)])

    def gradient_stops(inner, outer, scale):
        inside = [(0, shade(inner))] if inner > 0 else []
        return "".join(
            f'<stop offset="{f4(o)}" stop-color="{c}"/>'
            for o, c in inside + [(rho / scale, shade(rho)) for rho in points if inner <= rho <= outer]
        )

    for j in range(len(GLOW) - 1, 0, -1):
        defs.append(f'<radialGradient id="e{j}">{gradient_stops(rim[j - 1], rim[j], rim[j])}</radialGradient>')
        far.append(f'<ellipse rx="{f(rim[j])}" ry="{f(arch(rim[j]))}" fill="url(#e{j})"/>')
    defs.append(
        f'<radialGradient id="nb" gradientUnits="userSpaceOnUse" cx="0" cy="0" r="{f(R_OUT)}">'
        f'<stop offset="0" stop-color="#000"/>{gradient_stops(0, R_OUT, R_OUT)}</radialGradient>'
    )
    near.append(f'<circle r="{f(R_OUT)}" style="fill:url(#nb)"/>')

    # --- what turns ----------------------------------------------------------------------
    # A ring that is the same all the way round looks still however fast it turns. So the
    # gas is given light and shade that changes round every ring, and every piece of it
    # lies on a slant across the rings, trailing back as it goes outward:
    # - bands: broad soft lengths of light (clumps) and of shade (gaps), a few to a zone;
    # - streaks: thin bright and dark ones, in small bundles;
    # - hot spots: a bright knot with a tail, in a few zones;
    # - two spiral arms. Each zone has a bright band and a dark one on each arm, and the
    #   zones start lined up, so the arms run unbroken from the inner edge to the rim. Then
    #   every zone turns at its own speed, the inner ones fastest, and the arms wind up and
    #   shear into the loose spiral scraps a real disk is made of.
    # Every one is a stroke no wider than 22 units. The app samples the scene on a tiny
    # canvas, where such a stroke is drawn as a hairline and dims smoothly as it moves; a
    # thin filled shape would flicker there from frame to frame and trip the flash check.
    # (Tried and dropped: drawing each zone once into a <pattern> tile and turning the
    # tile. The app's own measure fell by more than half, but the graphics card's work to
    # put the scene on screen rose by between a half and one and a half times over.)
    for h in range(HEATS):
        v = 1.03 + (V_OUT - 1.2) * (h + .5) / HEATS
        cool = h / (HEATS - 1)
        for n, fade in enumerate(FADES):
            defs.append(f'<linearGradient id="s{h}{n}">'
                        + stops(fade, lit(glow_at(v), 2.6 - .3 * cool, "#fff6e2", .5 * (1 - cool) ** 1.5))
                        + "</linearGradient>")
    for n, fade in enumerate(FADES):
        defs.append(f'<linearGradient id="d{n}">{stops(fade, "#260c02")}</linearGradient>')
    defs.append('<linearGradient id="rk">' + stops([(0, 0), (.5, .8), (1, 0)], "#000") + "</linearGradient>")
    defs.append('<linearGradient id="hk">' + stops([(0, "#ffb54a", 0), (.3, "#fff3d6", .9), (.5, "#ffffff", 1),
                                                    (.7, "#fff3d6", .9), (1, "#ffb54a", 0)]) + "</linearGradient>")
    pitch = 1 / ARMS_WIND                                # how steeply the arms cut across the rings

    def arm(r):
        return ARMS_START + ARMS_WIND * math.log(r / R_IN)

    for i in range(ZONES):
        lo, hi = R_IN * q ** i, R_IN * q ** (i + 1)
        r = math.sqrt(lo * hi)
        u = i / (ZONES - 1)                      # 0 at the inner edge, 1 at the rim
        heat = 1 - u                             # how much is going on: most near the hole
        h = min(HEATS - 1, int(u * HEATS))
        span = hi - lo
        wide = min(22, max(11, span * .62))      # a band's stroke: as wide as a hairline on the app's canvas allows
        full = 3 if span > 32 else 2             # and how many of them make a band as broad as the zone
        by_paint = {}

        def streak(paint, d, width, opacity, where=None):
            turn = rnd.uniform(0, 360) if where is None else math.degrees(where) % 360
            by_paint.setdefault(paint, []).append(
                f'<path d="{d}" stroke-width="{f(width)}" opacity="{f2(opacity)}" transform="rotate({f(turn)})"/>'
            )

        # How far out this zone's streaks may reach. The far side squashes a zone by one
        # figure, right for its own radius; a streak that climbs well beyond that is drawn a
        # little too high there, and would stand proud of the disk's rim.
        reach = min(R_OUT * .968, .98 * arch(R_OUT) * r / arch(r))

        def held(radius, climb, across=0.0):
            """A radius that keeps a streak of this climb, and this far across, inside the disk."""
            return min(max(radius, R_IN * .995 + climb / 2), reach - climb / 2 - across - wide / 2)

        def band(paint, where, radius, length, slant, opacity, count=2):
            """A broad soft length of light or of shade: wide strokes side by side."""
            climb, gap = radius * length * slant, wide * .82
            streak(paint, strands(rnd, held(radius, climb, gap * (count - 1)), count, length, gap, slant),
                   wide, opacity, where)

        def knot(paint, length, width, opacity):
            """A clump of gas: a spindle, thick in the middle and drawn out to a point at each end."""
            radius, where, climb = held(rnd.uniform(lo, hi), 8), rnd.uniform(0, math.tau), rnd.uniform(3, 8)
            streak(paint, arc_d(radius, 0, length / radius, climb), width, opacity, where)
            streak(paint, arc_d(radius, 0, 2.3 * length / radius, 2.3 * climb), width * .4, opacity, where)

        # this zone's pieces of the two arms: a bright band, and a dark one trailing it
        for half in (0, math.pi):
            at_arm = arm(r) + half + rnd.gauss(0, .035)
            band("d1", at_arm + .4 + rnd.gauss(0, .03), r - wide * .4, rnd.uniform(.42, .58), pitch * .75,
                 rnd.uniform(.38, .54), full)
            band(f"s{h}1", at_arm, r - wide * .4, rnd.uniform(.42, .58), pitch * .75, .4 + .3 * u, full)
        # clumps and gaps of the zone's own, where chance puts them
        for _ in range(rnd.choice([1, 2])):
            band(f"d{rnd.randrange(2)}", None, rnd.uniform(lo, hi), rnd.uniform(.4, 1.0), rnd.uniform(.05, .14),
                 rnd.uniform(.36, .56), rnd.choice([1, full]))
        for _ in range(rnd.choice([1, 2]) if u > .2 else 1):
            band(f"s{h}{rnd.randrange(2)}", None, rnd.uniform(lo, hi), rnd.uniform(.3, .8), rnd.uniform(.05, .14),
                 rnd.uniform(.32, .6), rnd.choice([1, full]))
        for _ in range(rnd.choice([1, 2])):
            knot(f"s{h}1", rnd.uniform(70, 130), rnd.uniform(5, 9), rnd.uniform(.5, .85))
        knot("d1", rnd.uniform(80, 150), rnd.uniform(5, 9), rnd.uniform(.35, .5))
        # streaks: fine bright ones, and dark lanes
        for _ in range(round(2.6 + 2.4 * heat)):
            length, slant = rnd.uniform(.2, .9), rnd.uniform(.03, .1)
            streak(f"s{h}{rnd.randrange(2)}",
                   strands(rnd, held(rnd.uniform(lo, hi), r * length * slant, 14), rnd.choice([2, 3, 4]), length,
                           rnd.uniform(3, 6), slant, 3), rnd.uniform(1.3, 2.4), rnd.uniform(.55, .95))
        length, slant = rnd.uniform(.6, 1.5), rnd.uniform(.03, .08)
        streak(f"d{rnd.randrange(2)}",
               strands(rnd, held(rnd.uniform(lo, hi), r * length * slant, 14), rnd.choice([2, 3]), length,
                       rnd.uniform(4, 8), slant, 3), rnd.uniform(1.6, 3.2), rnd.uniform(.3, .5))
        # a hot spot: a bright knot of gas with a tail behind it
        if i in HOT_ZONES:
            where = rnd.uniform(0, math.tau)
            streak(f"s{h}0", arc_d(held(r, span * .3), .3, .64, span * .3), 3.4, .9, where)
            streak("hk", arc_d(held(r, 4), 0, 110 / r, 4), rnd.uniform(6.5, 8.5), 1, where)
            streak("hk", arc_d(held(r, 4), 0, 44 / r, 2), rnd.uniform(11, 13), .8, where)
        defs.append(f'<g id="z{i}">'
                    + "".join(f'<g stroke="url(#{paint})">{"".join(paths)}</g>' for paint, paths in by_paint.items())
                    + "</g>")

        period = T_IN * (r / (R_IN * math.sqrt(q))) ** SPIN
        use = f'<use href="#z{i}" class="z" style="animation-duration:{f(period)}s"/>'
        near.append(use)
        far.append(f'<g transform="scale(1 {f2(arch(r) / r)})">{use}</g>')

    # --- matter falling in: a few bright streamers that spiral from the rim to the hole ---
    fall_from = R_OUT * .9
    falls = [(0, 1.0, 0), (40, .8, -150), (70, .61, -340), (100, .42, -620)]   # percent, size, turn
    defs.append(
        f'<path id="st" d="{arc_d(fall_from, .2, .42)}{arc_d(fall_from - 7, .23, .3)}" '
        'stroke="url(#s00)" stroke-width="3.6"/>'
    )
    for n in range(STREAMERS):
        period = rnd.uniform(34, 52)
        timing = f'style="animation-duration:{f(period)}s;animation-delay:-{f(period * (n + rnd.random()) / STREAMERS)}s"'
        turned = f'<g transform="rotate({rnd.randrange(360)})"><use href="#st" class="st" {timing}/></g>'
        near.append(turned)
        far.append(f'<g class="sk" {timing}>{turned}</g>')

    gap = R_IN * .93
    egg = f"M{f(-gap)} 0A{f(gap)} {f(arch(gap))} 0 0 1 {f(gap)} 0A{f(gap)} {f(TILT * gap)} 0 0 1 {f(-gap)} 0Z"
    defs.append(
        # the far half runs 2 units past the level line so the near half's soft edge lands on its own colors
        f'<clipPath id="up"><rect x="{f(x0)}" y="{f(top)}" width="{f(-2 * x0)}" height="{f(2 - top)}"/></clipPath>'
        f'<clipPath id="lo"><rect x="{f(x0)}" width="{f(-2 * x0)}" height="{f(foot)}"/></clipPath>'
        # the dark gap between the hole and the disk: the ring and the bent starlight show only there
        f'<clipPath id="rc"><path d="{egg}"/></clipPath>'
        # and under the near side's rim the foot of the ring comes back into view (a phone shows it)
        f'<clipPath id="rl"><rect x="{f(-R - 40)}" y="{f(TILT * R_OUT * .97)}" width="{f(2 * R + 80)}" '
        f'height="{f(R)}"/></clipPath>'
        # Doppler: the side turning toward us is brighter and whiter, the side turning away dimmer and redder
        f'<linearGradient id="dop" gradientUnits="userSpaceOnUse" x1="{f(x0)}" x2="{f(-x0)}">'
        + stops([(0, "#ffffff", 1), (.21, "#ffffff", 1), (.305, "#ffeed2", 1), (.36, "#e0a05c", 1),
                 (.5, "#cc8a4a", 1), (.62, "#96491e", 1), (.78, "#6a2810", 1), (1, "#4a170a", 1)])
        + "</linearGradient>"
        # the disk hides the sky and its own haze behind it, right out to its rim
        '<radialGradient id="oc">' + stops([(0, 1), (.9, 1), (.99, 0)], "#000") + "</radialGradient>"
        # the photon ring's glow sits outside it; inside is the shadow
        '<radialGradient id="rg">'
        + stops([(.908, "#ffd9a0", 0), (.917, "#ffeccc", 1), (.934, "#ffdca6", .55), (.962, "#ffc27a", .18),
                 (1, "#ffc27a", 0)])
        + "</radialGradient>"
        # and it too is dimmer on the side turning away
        '<linearGradient id="rd">' + stops([(0, 0), (.4, .05), (.72, .5), (1, .68)], "#000") + "</linearGradient>"
        # light the disk throws around itself
        '<radialGradient id="hz">' + stops([(0, "#ff9a44", .19), (.5, "#d2622a", .085), (1, "#7a2a10", 0)])
        + "</radialGradient>"
        '<radialGradient id="bl">' + stops([(0, "#ffe2b0", .3), (.4, "#ffb866", .12), (1, "#ff9a44", 0)])
        + "</radialGradient>"
    )

    box = f'x="{f(x0)}" y="{f(top)}" width="{f(-2 * x0)}" height="{f(foot - top)}"'
    inset = f'x="{f(x0 + 4)}" y="{f(top + 4)}" width="{f(-2 * x0 - 8)}" height="{f(foot - top - 8)}"'
    flat_disk = f'transform="scale(1 {TILT})"'
    light = (
        '<g class="br">'
        f'<ellipse cy="-150" rx="1700" ry="1000" fill="url(#hz)"/>'
        f'<ellipse cx="{f(-1.55 * R)}" cy="{f(-.25 * R)}" rx="{f(1.9 * R)}" ry="{f(1.25 * R)}" fill="url(#bl)"/>'
        "</g>"
    )
    shadow = (
        f'<g clip-path="url(#up)"><ellipse rx="{f(R_OUT)}" ry="{f(arch(R_OUT))}" fill="url(#oc)"/></g>'
        f'<g clip-path="url(#lo)"><circle r="{f(R_OUT)}" style="fill:url(#oc)" {flat_disk}/></g>'
        f'<circle r="{f(R - 1)}" style="fill:#000"/>'
    )
    # Starlight from behind the hole, bent into thin arcs beside it. The two sets slide opposite ways.
    def bent(radii):
        return "".join(
            arc_d(R * k, side * math.pi / 2 + rnd.uniform(-.75, .75), rnd.uniform(.08, .4))
            for k in radii for side in (-1, 1)
        )

    lens = (
        '<g clip-path="url(#rc)" stroke="#cfe0ff" stroke-width="1.1">'
        f'<path class="la" d="{bent([1.06, 1.1, 1.15])}" stroke-opacity=".3"/>'
        f'<path class="lb" d="{bent([1.08, 1.125, 1.17])}" stroke-opacity=".2"/>'
        "</g>"
    )
    # The disk is not quite even: a broad soft shadow lies over one side of its outer part,
    # and goes round with the gas out there, slowly. It is the largest thing that turns.
    defs.append(
        f'<radialGradient id="lp" gradientUnits="userSpaceOnUse" cx="{f(-.8 * R_OUT)}" cy="0" r="{f(.56 * R_OUT)}">'
        + stops([(0, .36), (.5, .24), (1, 0)], "#170602") + "</radialGradient>"
    )
    shade = f'<circle class="lp" r="{f(R_OUT)}" style="fill:url(#lp)"/>'
    disk = (
        '<g class="glow">'
        f'<rect class="bk" {box}/>'
        f'<g clip-path="url(#up)">{"".join(far)}'
        f'<g transform="scale(1 {f2(arch(R_OUT) / R_OUT)}) rotate({SHADE_FROM})">{shade}</g></g>'
        f'<g clip-path="url(#lo)"><g {flat_disk}>{"".join(near)}<g transform="rotate({SHADE_FROM})">{shade}</g></g></g>'
        f'<rect {inset} fill="url(#dop)" class="mul"/>'
        "</g>"
    )

    def beads(count, radius, short, long, paint, width, opacity):
        """Short soft arcs spread round a ring: pearls of light (or dim stretches) that travel along it."""
        return "".join(
            f'<path d="{arc_d(radius, 0, rnd.uniform(short, long))}" stroke="url(#{paint})" stroke-width="{f(width)}" '
            f'opacity="{f2(opacity)}" transform="rotate({f(360 * (k + rnd.uniform(-.3, .3)) / count)})"/>'
            for k in range(count)
        )

    ring = (
        '<g clip-path="url(#rc)">'
        f'<circle class="br" r="{f(R * 1.09)}" style="fill:url(#rg)"/>'
        f'<circle r="{f(R * 1.04)}" stroke="#ffdcae" stroke-opacity=".3"/>'
        f'<circle r="{f(R)}" stroke="#fffaf0" stroke-width="3"/>'
        # light going round the hole: dim gaps and bright knots that run along the ring, the way the disk turns
        f'<g class="sa">{beads(5, R, .3, .7, "rk", 3.6, .8)}</g>'
        f'<g class="sb">{beads(7, R, .08, .22, "hk", 3.9, .9)}</g>'
        f'<g class="sc">{beads(5, R * 1.04, .2, .5, "hk", 1.8, .6)}</g>'
        f'<circle r="{f(R + 6)}" stroke="url(#rd)" stroke-width="40"/>'
        "</g>"
        # The foot of the ring, below the disk. On a desktop window only a sliver of it would show,
        # under the message box, so it is drawn on phones alone (SPACE_PORTRAIT turns it on).
        '<g class="lr" clip-path="url(#rl)">'
        f'<circle r="{f(R * 1.09)}" style="fill:url(#rg)"/>'
        f'<circle r="{f(R)}" stroke="#fffaf0" stroke-width="3"/>'
        f'<circle r="{f(R + 6)}" stroke="url(#rd)" stroke-width="40"/>'
        "</g>"
    )
    body = f'<g class="bh"><g class="wob">{light}{shadow}{lens}{disk}{ring}</g></g>'

    def keys(frames):
        return "".join(f"{pct}%{{{rule}}}" for pct, rule in frames)

    css = (
        "circle,path{fill:none}path{stroke-linecap:round}"
        # The disk is light, so it is added to the sky: drawn on black, tinted by the Doppler
        # overlay, then summed in. A renderer that cannot add draws the disk plain instead.
        ".glow{mix-blend-mode:plus-lighter}.mul{mix-blend-mode:multiply}.lr{display:none}"
        "@supports not (mix-blend-mode:plus-lighter){.bk,.mul{display:none}}"
        # the disk turns: every zone at its own speed
        ".z{animation:sp 60s linear infinite}"
        f".lp{{animation:sp {f(T_SHADE)}s linear infinite}}"
        "@keyframes sp{to{transform:rotate(-360deg)}}"
        # streamers fall in, speeding up; on the far side their arch grows steeper as they near the hole
        ".st{opacity:0;animation:fa 40s linear infinite}.sk{animation:fk 40s linear infinite}"
        "@keyframes fa{"
        + keys([(pct, f"transform:rotate({turn}deg) scale({f2(size)})" + (";opacity:0" if pct in (0, 100) else ""))
                for pct, size, turn in falls] + [(22, "opacity:.45"), (55, "opacity:.95"), (90, "opacity:.9")])
        + "}@keyframes fk{"
        + keys([(pct, f"transform:scale(1,{f2(arch(fall_from * size) / (fall_from * size))})") for pct, size, _ in falls])
        + "}"
        # the whole hole rocks very slowly, like a top
        ".wob{animation:wo 71s ease-in-out infinite alternate}"
        "@keyframes wo{from{transform:rotate(-1.3deg)}to{transform:rotate(1.3deg)}}"
        # its light breathes, the ring shimmers, the bent starlight slides
        ".br{animation:br 9s ease-in-out infinite alternate}@keyframes br{from{opacity:.8}to{opacity:1}}"
        ".sa{animation:sp 29s linear infinite}.sb{animation:sp 21s linear infinite}.sc{animation:sp 37s linear infinite}"
        ".la{animation:la 90s ease-in-out infinite alternate}.lb{animation:la 90s ease-in-out infinite alternate-reverse}"
        "@keyframes la{from{transform:rotate(-7deg)}to{transform:rotate(7deg)}}"
    )
    return "".join(defs), body, css


# ----------------------------------------------------------------------------
# The sky far behind the hole: stars, a faint band of the Milky Way, and small
# far-off things (galaxies, star clusters, wisps of nebula) pinned to the top
# corners, clear of the words in the middle and of the hole at the foot.
# ----------------------------------------------------------------------------
SW, SH = 1600, 1000  # the star field's own frame; it is cropped to fill any window
STAR_COLORS = [      # real star colors, from hot blue to cool orange
    ("#9db4ff", .12), ("#bccbff", .20), ("#e2e8ff", .28), ("#fff8f0", .22), ("#ffe2b8", .12), ("#ffc685", .06),
]


def star_color(rnd):
    roll, total = rnd.random(), 0.0
    for color, share in STAR_COLORS:
        total += share
        if roll <= total:
            return color
    return STAR_COLORS[-1][0]


def dots(points, color, width, extra=""):
    """Round dots, as one path: each is a line of no length with a round cap."""
    d = "".join(f"M{round(x)} {round(y)}h0" for x, y in points)
    return f'<path d="{d}" stroke="{color}" stroke-width="{f(width)}"{extra}/>'


def stars(rnd, timing, count, width, opacity, place, twinkling=0.0):
    """Stars grouped by color. A share of them twinkle, a handful at a time."""
    by_color, twinklers = {}, []
    for _ in range(count):
        point, color = place(rnd), star_color(rnd)
        if rnd.random() < twinkling:
            twinklers.append((point, color))
        else:
            by_color.setdefault(color, []).append(point)
    out = [dots(points, color, width, f' stroke-opacity="{f2(opacity)}"') for color, points in by_color.items()]
    for i in range(0, len(twinklers), 5):
        group = twinklers[i:i + 5]
        seconds = rnd.uniform(2.8, 7)
        out.append(dots([point for point, _ in group], group[0][1], width * 1.15,
                        f' class="tw {timing.cls(seconds, rnd.uniform(0, seconds))}"'))
    return "".join(out)


def soft(name, color, peak=1.0):
    return (f'<radialGradient id="{name}">'
            + stops([(0, peak), (.45, peak * .45), (1, 0)], color) + "</radialGradient>")


def blob(x, y, rx, ry, paint, opacity, turn):
    return (f'<ellipse cx="{f(x)}" cy="{f(y)}" rx="{f(rx)}" ry="{f(ry)}" fill="url(#{paint})" '
            f'opacity="{f2(opacity)}" transform="rotate({f(turn)} {f(x)} {f(y)})"/>')


def cloud(rnd, count, center, spread, size, paints, opacity, turn=(-40, 40), squash=(.35, .8)):
    out = []
    for _ in range(count):
        rx = rnd.uniform(*size)
        out.append(blob(center[0] + rnd.gauss(0, spread[0]), center[1] + rnd.gauss(0, spread[1]), rx,
                        rx * rnd.uniform(*squash), rnd.choice(paints), rnd.uniform(*opacity), rnd.uniform(*turn)))
    return "".join(out)


def place(x, y, turn=0, size=1.0, lean=1.0):
    """Where a small thing drawn 100 units across goes: moved, turned, sized, and leaned back."""
    return f'transform="translate({f(x)} {f(y)}) rotate({f(turn)}) scale({f2(size)} {f2(size * lean)})"'


def spiral_galaxy(rnd, timing, at, seconds, crowd=1.0):
    """A spiral seen at a slant: a warm core, two soft arms that go blue as they wind out,
    and the grain of star clouds and pink gas knots along them."""
    arms, blue, white, pink = [], [], [], []
    for arm in (0, 1):
        points = []
        for k in range(40):
            turn = k / 39 * 2.3 * math.pi
            r = 9 * math.exp(.33 * turn)
            a = turn + arm * math.pi
            points.append((r * math.cos(a), r * math.sin(a)))
            for _ in range(round(3 * crowd)) if r > 16 else []:
                roll = rnd.random()
                spread = 2 + r * .085
                star = (points[-1][0] + rnd.gauss(0, spread), points[-1][1] + rnd.gauss(0, spread))
                (pink if roll < .09 else white if roll < .3 else blue).append(star)
        arms.append("M" + "L".join(f"{round(x)} {round(y)}" for x, y in points))
    arms = "".join(arms)
    return (
        f"<g {at}>"
        '<circle r="104" style="fill:url(#gd)"/>'
        f'<g class="gx {timing.cls(seconds, rnd.uniform(0, seconds))}" stroke="url(#ga)" stroke-linejoin="round">'
        f'<path d="{arms}" stroke-width="22" stroke-opacity=".13"/>'
        f'<path d="{arms}" stroke-width="12" stroke-opacity=".2"/>'
        f'<path d="{arms}" stroke-width="4.5" stroke-opacity=".5"/>'
        + dots(blue, "#b9ccff", 2.4, ' stroke-opacity=".8"')
        + dots(white, "#f2f5ff", 3.3, ' stroke-opacity=".9"')
        + dots(pink, "#ff8fb4", 3.8, ' stroke-opacity=".85"')
        + "</g>"
        '<ellipse rx="34" ry="24" fill="url(#gc)"/>'
        "</g>"
    )


def edge_on_galaxy(at):
    """A spiral seen from the side: a thin bright disk, a bulge, and the dust lane across it."""
    return (
        f"<g {at}>"
        '<ellipse rx="112" ry="26" fill="url(#gd)" opacity=".5"/>'
        '<ellipse rx="100" ry="8.5" fill="url(#ge)"/>'
        '<ellipse rx="25" ry="14" fill="url(#gc)"/>'
        '<path d="M-70 1.6Q0 2.6 70 1.2" stroke="url(#gl)" stroke-width="2.3"/>'
        "</g>"
    )


def elliptical_galaxy(at):
    return (f'<g {at}><ellipse rx="100" ry="74" fill="url(#gd)" opacity=".6"/>'
            '<ellipse rx="62" ry="45" fill="url(#gc)"/></g>')


def globular_cluster(rnd, at):
    """Hundreds of thousands of old stars in a ball: drawn as a hundred and fifty, packed to the middle."""
    warm, white, big = [], [], []
    for _ in range(150):
        r = abs(rnd.gauss(0, 30))
        a = rnd.uniform(0, math.tau)
        roll = rnd.random()
        (big if roll < .1 else warm if roll < .5 else white).append((r * math.cos(a), r * math.sin(a)))
    return (f'<g {at}><circle r="66" style="fill:url(#gc)" opacity=".42"/>'
            + dots(warm, "#ffdca8", 2.6, ' stroke-opacity=".85"') + dots(white, "#f4f6ff", 2.2, ' stroke-opacity=".9"')
            + dots(big, "#fff1d8", 4.2)
            + "</g>")


def open_cluster(rnd, at):
    """A young cluster: a few hot blue stars, still wrapped in the dust that lights up around them."""
    bright = [(rnd.gauss(0, 30), rnd.gauss(0, 24)) for _ in range(8)]
    faint = [(rnd.gauss(0, 46), rnd.gauss(0, 36)) for _ in range(22)]
    return (
        f"<g {at}>"
        + cloud(rnd, 7, (0, 0), (26, 20), (30, 62), ["nh"], (.14, .26), squash=(.5, .9))
        + dots(faint, "#cfdcff", 3, ' stroke-opacity=".8"')
        + dots(bright, "#eef3ff", 6.5)
        + "".join(f'<circle cx="{f(x)}" cy="{f(y)}" r="13" style="fill:url(#sh)" opacity=".55"/>' for x, y in bright[:5])
        + "</g>"
    )


def nebula(rnd, at):
    """A patch of glowing hydrogen: red filaments curled round a teal heart, with a dust lane across."""
    out = []
    for a, b, start, end, tilt in [(78, 44, 190, 350, -8), (56, 32, 10, 170, 12), (40, 22, 100, 320, -20)]:
        t = math.radians(tilt)
        for _ in range(6):
            phi = math.radians(rnd.uniform(start, end))
            px, py = a * math.cos(phi), b * math.sin(phi)
            x = px * math.cos(t) - py * math.sin(t) + rnd.gauss(0, 5)
            y = px * math.sin(t) + py * math.cos(t) + rnd.gauss(0, 4)
            along = math.degrees(math.atan2(b * math.cos(phi), -a * math.sin(phi))) + tilt
            rx = rnd.uniform(12, 34)
            out.append(blob(x, y, rx, rx * rnd.uniform(.3, .6), rnd.choice(["nr", "nr", "np"]),
                            rnd.uniform(.12, .26), along + rnd.uniform(-12, 12)))
    return (
        f"<g {at}>"
        + cloud(rnd, 5, (0, 0), (50, 30), (50, 100), ["nh"], (.05, .1), turn=(-20, 20), squash=(.55, .95))
        + "".join(out)
        + cloud(rnd, 6, (5, -3), (15, 10), (9, 24), ["nt"], (.16, .3), squash=(.5, .9))
        + "".join(blob(-48 + i * 22 + rnd.gauss(0, 4), 26 - i * 10 + rnd.gauss(0, 3), rnd.uniform(15, 30),
                       rnd.uniform(4.5, 8), "nk", rnd.uniform(.3, .5), -26 + rnd.uniform(-8, 8)) for i in range(5))
        + "</g>"
    )


def far_sky(rnd, timing):
    defs = (
        '<radialGradient id="sky" cx=".26" cy=".16" r="1">'
        + stops([(0, "#080b1b", 1), (.5, "#04060e", 1), (1, "#020308", 1)]) + "</radialGradient>"
        + soft("mw", "#b7c6ff") + soft("mk", "#010207")
        # galaxies: arms and disk go from warm at the core to blue at the rim
        + '<radialGradient id="ga" gradientUnits="userSpaceOnUse" cx="0" cy="0" r="106">'
        + stops([(0, "#fff4e2", 1), (.3, "#e3e9ff", .9), (.7, "#a9bfff", .5), (1, "#8fa8ff", 0)]) + "</radialGradient>"
        + '<radialGradient id="gc">' + stops([(0, "#fffaee", 1), (.35, "#ffe9c4", .62), (1, "#ffd9a0", 0)])
        + "</radialGradient>"
        + '<radialGradient id="gd">' + stops([(0, "#cdd9ff", .38), (.6, "#9db4ff", .14), (1, "#9db4ff", 0)])
        + "</radialGradient>"
        + '<radialGradient id="ge">' + stops([(0, "#fff3dc", .95), (.35, "#dfe6ff", .62), (1, "#9db4ff", 0)])
        + "</radialGradient>"
        + '<linearGradient id="gl" gradientUnits="userSpaceOnUse" x1="-72" x2="72">'
        + stops([(0, 0), (.3, .8), (.7, .8), (1, 0)], "#120a08") + "</linearGradient>"
        # nebula light: hydrogen red and pink, oxygen teal, blue haze, and dust that blocks it
        + soft("nr", "#ff3f6e") + soft("np", "#ff79b4") + soft("nt", "#38d6c8") + soft("nh", "#5b7bff")
        + soft("nk", "#010208")
        # a bright star: a soft halo, four thin spikes, a hard core
        + '<radialGradient id="sh">' + stops([(0, "#ffffff", .95), (.22, "#d2e1ff", .4), (1, "#d2e1ff", 0)])
        + "</radialGradient>"
        + '<radialGradient id="sp">' + stops([(0, "#ffffff", .9), (1, "#cfe0ff", 0)]) + "</radialGradient>"
        + "".join(
            f'<linearGradient id="{name}" gradientUnits="userSpaceOnUse" x1="0" x2="{x}" y2="{y}">'
            + stops([(0, "#ffffff", 1), (.25, "#cfe0ff", .7), (1, "#cfe0ff", 0)]) + "</linearGradient>"
            for name, x, y in [("mt", 150, -54), ("mu", -120, -40)]
        )
        + '<g id="bs"><circle r="10" style="fill:url(#sh)"/>'
        '<path d="M-28 0H28M0-28V28" stroke="url(#sp)" stroke-width=".9"/>'
        '<circle r="1.5" style="fill:#fff"/></g>'
    )

    def anywhere(r):
        return r.uniform(0, SW), r.uniform(0, SH)

    def in_band(r):
        return r.uniform(-300, SW + 300), 330 + r.gauss(0, 60)

    band = (
        '<g transform="rotate(-13 800 330)">'
        + cloud(rnd, 13, (800, 330), (640, 34), (90, 210), ["mw"], (.04, .085))
        + stars(rnd, timing, 330, .8, .5, in_band)
        + cloud(rnd, 6, (800, 334), (600, 10), (80, 170), ["mk"], (.2, .4), turn=(-5, 5), squash=(.16, .3))
        + "</g>"
    )
    bright = "".join(
        f'<use href="#bs" transform="translate({x} {y}) scale({f2(size)})" '
        f'class="bt {timing.cls(seconds, rnd.uniform(0, seconds))}"/>'
        for x, y, size, seconds in [
            (152, 118, 1.2, 7), (436, 372, .8, 5), (86, 566, .9, 8), (1322, 92, 1.0, 6), (1506, 318, 1.3, 9),
            (1188, 452, .75, 5), (704, 76, .85, 7), (958, 214, .7, 6),
        ]
    )
    field = (
        f'<svg width="100%" height="100%" viewBox="0 0 {SW} {SH}" preserveAspectRatio="xMidYMid slice">'
        f'<rect width="{SW}" height="{SH}" fill="url(#sky)"/>'
        + band
        # galaxies too far off to show a shape: a few faint smudges
        + "".join(
            blob(x, y, rx, rx * squash, paint, opacity, turn)
            for x, y, rx, squash, paint, opacity, turn in [
                (246, 468, 7, .5, "gc", .55, 25), (1392, 566, 6, .6, "gd", .9, -40), (612, 148, 5, .45, "gc", .5, 70),
                (1016, 118, 6, .7, "gd", .8, 10), (1548, 742, 5, .5, "gc", .45, -20), (58, 316, 5, .6, "gd", .8, 50),
            ]
        )
        + stars(rnd, timing, 360, .7, .42, anywhere)
        + stars(rnd, timing, 520, .95, .62, anywhere)
        + stars(rnd, timing, 210, 1.5, .82, anywhere, twinkling=.34)
        + stars(rnd, timing, 54, 2.3, .95, anywhere, twinkling=.5)
        + bright
        # now and then, a meteor
        + '<path class="me" d="M0 0L150 -54" stroke="url(#mt)" stroke-width="1.6"/>'
        '<path class="me mf" d="M0 0L-120 -40" stroke="url(#mu)" stroke-width="1.3"/>'
        + "</svg>"
    )
    # Pinned to the top corners: they keep their place and their size on any window.
    left = (
        '<svg width="100%" height="100%" viewBox="0 0 800 800" preserveAspectRatio="xMinYMin meet">'
        + nebula(rnd, place(124, 306, -18, .54))
        + spiral_galaxy(rnd, timing, place(262, 176, -24, .5, .52), 420)
        + open_cluster(rnd, place(400, 214, 0, .32))
        + elliptical_galaxy(place(118, 262, 30, .1))
        + edge_on_galaxy(place(356, 96, 38, .17))
        + "</svg>"
    )
    right = (
        '<svg width="100%" height="100%" viewBox="0 0 800 800" preserveAspectRatio="xMaxYMin meet">'
        + edge_on_galaxy(place(560, 158, -27, .58))
        + globular_cluster(rnd, place(470, 276, 0, .3))
        + elliptical_galaxy(place(676, 302, -20, .2))
        + spiral_galaxy(rnd, timing, place(690, 96, 12, .2, .78), 520, .5)
        + elliptical_galaxy(place(520, 62, 60, .08))
        + "</svg>"
    )
    css = (
        ".tw{animation:tw 4s ease-in-out infinite}@keyframes tw{0%,100%{opacity:.95}50%{opacity:.2}}"
        ".bt{animation:bt 6s ease-in-out infinite}@keyframes bt{0%,100%{opacity:1}50%{opacity:.5}}"
        ".gx{animation:sp 400s linear infinite}"
        ".me{opacity:0;animation:me 47s linear -33s infinite}"
        ".mf{animation-name:mf;animation-duration:83s;animation-delay:-41s}"
        "@keyframes me{0%{transform:translate(520px,60px);opacity:0}.5%{opacity:.9}"
        "2.6%,100%{transform:translate(230px,172px);opacity:0}}"
        "@keyframes mf{0%{transform:translate(1180px,40px);opacity:0}.4%{opacity:.8}"
        "1.6%,100%{transform:translate(1420px,126px);opacity:0}}"
    )
    return defs, field + left + right, css


# ----------------------------------------------------------------------------
# The scene
# ----------------------------------------------------------------------------
def deep_space(seed=11):
    rnd = random.Random(seed)
    timing = Timing("t")
    hole_defs, hole_body, hole_css = black_hole(rnd)
    sky_defs, sky, sky_css = far_sky(random.Random(seed + 1), timing)
    # The hole is pinned to the foot of the window and sized by the window: one unit is one
    # point on a 2000 x 1195 window, and it shrinks in step on a shorter or a narrow one
    # ("meet" fits a 1500 x 1195 box inside the window, and the disk spills out of the box).
    # It sits 27.5 units right of the middle, where the chat column is (the sidebar is wider
    # than the panel on the right). The outer layer lifts it 87 points whatever its size, so
    # the near side of the disk always meets the top edge of the message box.
    hole = (
        f'<svg y="-{BOX_TOP + 12}" width="100%" height="100%" overflow="visible">'
        f'<svg width="100%" height="100%" viewBox="{-750 - OFF_CENTER} {DISK_FOOT - 1195} 1500 1195" '
        'preserveAspectRatio="xMidYMax meet" overflow="visible">'
        + hole_body + "</svg></svg>"
    )
    style = (
        hole_css + sky_css + timing.css()
        + "@media (prefers-reduced-motion:reduce){*{animation-play-state:paused!important}}"
    )
    return (
        '<svg xmlns="http://www.w3.org/2000/svg">'
        f"<style>{style}</style><defs>{hole_defs}{sky_defs}</defs>{sky}{hole}</svg>"
    )


# A phone: the scene's box is narrow, so "meet" has made the hole small. Draw it larger,
# so its ring spans four fifths of the screen; put it back in the middle, since no sidebar
# pushes the message box off center there; and lift it a little, the box being taller.
SPACE_PORTRAIT = (
    f"@media (max-aspect-ratio:1/1){{.bh{{transform:translate({-OFF_CENTER}px,-120px) scale({PHONE_SIZE})}}"
    ".lr{display:inline}}"
)

# The look's colors, for hooks/make-colors.js: space-black surfaces with a breath of indigo,
# cool white words (they read against the amber of the disk), and a starlight-blue accent
# so the reds, greens and ambers keep their own meanings.
SPACE_COLORS = {
    "label": "Deep space",
    "roles": {"accent": "#7fb0ff", "danger": "#ff6a7c", "success": "#58e0a4", "warning": "#ffc257", "pro": "#c59bff"},
    "dark": {
        "gray": {
            "anchors": {
                "surface-0": "#06070e",
                "surface-1": "#0b0e1b",
                "surface-2": "#101425",
                "surface-3": "#14192d",
                "text-primary": "#eceff8",
                "text-secondary": "#c0c7da",
                "text-muted": "#949db6",
            },
        },
    },
}
# How the app frosts its panels over the scene. The chat column gets this veil from top to
# bottom, and the hole sits behind it: a light blur keeps the photon ring a line, and the
# tint does the work of keeping words readable where the disk arches behind them.
SPACE_GLASS = {"blur": 2, "tint": "#05060c", "opacity": 0.6}
SPACE_ALT = (
    "A black hole rising around the message box: its dark shadow ringed with light, and a glowing disk of gas "
    "turning slowly round it, arching over the top and sweeping across in front, brighter on the left. "
    "Small galaxies and stars far behind."
)


def still_size(svg):
    """The most the app's still frame of a scene can come to, in characters.

    The app keeps a still copy of the scene, for people who turn motion off and to fall
    back on. It writes every empty element out in full there (<path ...></path> for
    <path .../>), so the copy is longer than the scene, and it has to fit the same limit:
    past it the app has no still frame at all and shows nothing.
    """
    return len(svg) + sum(len(tag) + 2 for tag in re.findall(r"<([A-Za-z]+)[^<>]*/>", svg))


def main():
    svg = deep_space()
    phone = with_portrait(svg, SPACE_PORTRAIT)
    print(f"DEEP_SPACE: {len(phone):,} characters with its phone rules ({len(phone) / LIMIT:.0%} of the limit)")
    if len(phone) > LIMIT:
        raise SystemExit(f"DEEP_SPACE is over the {LIMIT:,} character limit")
    if still_size(phone) > LIMIT:
        raise SystemExit(
            f"DEEP_SPACE's still frame could come to {still_size(phone):,} characters, over the {LIMIT:,} limit: "
            "the app would have nothing to show people who turn motion off"
        )
    problems = scene_problems(svg)
    try:
        minidom.parseString(phone.encode("utf-8"))
    except ExpatError as error:
        problems.append(f"with its phone rules it is not well-formed XML: {error}")
    if "--preview" in sys.argv:
        folder = pathlib.Path(sys.argv[sys.argv.index("--preview") + 1])
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "space.svg").write_text(svg)
        (folder / "space-phone.svg").write_text(phone)
        for line in problems:
            print("  PROBLEM:", line)
        print(f"wrote {folder / 'space.svg'} and {folder / 'space-phone.svg'}; the mod is untouched")
        return
    if problems:
        raise SystemExit("DEEP_SPACE would not move in the desktop app:\n  " + "\n  ".join(problems))
    lines = [
        "// The deep space look. tools/space.py writes this file; edit that, not this.",
        "",
        "/** The scene the desktop app plays: a black hole around the message box. */",
        f"export const DEEP_SPACE = {json.dumps(svg)}",
        "",
        "/** Extra CSS for phones only: a size @media here would freeze the scene on desktop. */",
        f"export const DEEP_SPACE_PORTRAIT = {json.dumps(SPACE_PORTRAIT)}",
        "",
        f"export const SPACE_COLORS = {json.dumps(SPACE_COLORS, indent=2)}",
        "",
        f"export const SPACE_GLASS = {json.dumps(SPACE_GLASS)}",
        "",
        f"export const SPACE_ALT = {json.dumps(SPACE_ALT)}",
        "",
    ]
    (HOOKS / "space-scene.js").write_text("\n".join(lines))
    print(f"wrote {HOOKS / 'space-scene.js'}")


if __name__ == "__main__":
    main()
