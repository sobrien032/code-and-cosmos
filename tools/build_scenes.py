#!/usr/bin/env python3
"""Shared helpers for the two scene builders, tools/rain.py and tools/space.py.

Each builder writes its own look (hooks/rain-scene.js, hooks/space-scene.js):
run  python3 tools/rain.py  or  python3 tools/space.py  after a change.

What the desktop app does with a scene. This was read from the app's own code
on 14 Nov 2026; the app loads that code from the web, so it can change with no
app update. A scene is one SVG, at most 131,072 characters, no script,
nothing loaded.

- It only moves if the whole SVG passes a strict check. scene_problems() below
  is that check, and this script stops if a scene fails it. One thing off, such
  as an @media rule about size, and the app draws a still frame instead: the
  same SVG with every animation taken out, so each element sits where it is
  before its animation moves it.
- A scene that passes is played as an image. CSS @keyframes and SMIL both run
  there, from <style> classes or style="" attributes alike.
- While it plays the app samples it every frame, and puts the still frame back
  for good if a large area flashes (a quarter of any 341 by 256 pixel block
  swinging light and dark four times in a second) or if a sample costs more
  than 5.5 ms on average over 3 seconds. Both scenes avoid filters (blur,
  noise) for that reason: the whole backdrop is redrawn every frame while
  something in it moves.
- People who turn motion off get the still frame, so it has to look right.
"""
import html
import json
import math
import pathlib
import random
import re
from xml.dom import minidom
from xml.parsers.expat import ExpatError

W, H = 1600, 1000
LIMIT = 131_072


def f(n):
    """A number in as few characters as it takes."""
    s = f"{n:.1f}".rstrip("0").rstrip(".")
    return "0" if s in ("", "-0") else s


def root(body, style):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
        f'preserveAspectRatio="xMidYMid slice"><style>{style}</style>{body}</svg>'
    )


def with_portrait(svg, css):
    """The scene as a phone gets it: the same SVG plus its rules for a tall screen.

    hooks/register.tsx does the same splice, for the mobile app alone. The
    desktop app refuses to move a scene whose CSS asks @media about size.
    """
    return svg.replace("</style>", css + "</style>", 1)


class Timing:
    """Each element's animation speed and start point, as a class in the stylesheet.

    Put css() after the rules that use the `animation` shorthand, or the
    shorthand resets these.
    """

    def __init__(self, prefix):
        self.prefix, self.rules = prefix, []

    def cls(self, duration, delay=0.0):
        name = f"{self.prefix}{len(self.rules)}"
        self.rules.append(
            f".{name}{{animation-duration:{f(duration)}s;animation-delay:-{f(delay)}s}}"
        )
        return name

    def css(self):
        return "".join(self.rules)


# ----------------------------------------------------------------------------
# The desktop app's check: may this scene move? Ported from the app's code.
# ----------------------------------------------------------------------------
SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"
XML_NS = "http://www.w3.org/XML/1998/namespace"
XMLNS_NS = "http://www.w3.org/2000/xmlns/"
SMIL = {"animate", "animateMotion", "animateTransform", "set"}
ELEMENTS = SMIL | set(
    "circle clipPath defs desc ellipse feBlend feComposite feDropShadow feFlood feGaussianBlur "
    "feMerge feMergeNode feOffset filter g line linearGradient marker mask mpath path pattern "
    "polygon polyline radialGradient rect stop style svg symbol text textPath title tspan use".split()
)
FUNCTIONS = set(
    "color color-mix hsl hsla hwb lab lch light-dark oklab oklch rgb rgba "
    "abs acos asin atan atan2 calc clamp cos exp hypot log max min mod pow rem round sign sin "
    "sqrt tan var matrix matrix3d perspective rotate rotate3d rotatex rotatey rotatez scale "
    "scale3d scalex scaley scalez skew skewx skewy translate translate3d translatex translatey "
    "translatez cubic-bezier linear steps blur drop-shadow grayscale hue-rotate invert opacity "
    "saturate sepia is not nth-child nth-last-child nth-last-of-type nth-of-type where".split()
)
AT_RULES = {"keyframes", "layer", "media", "supports"}
_SPACE = re.compile(r"[\s\ufeff\x00-\x1f\x7f-\x9f]")
_LOCAL_ID = re.compile(r"#[A-Za-z_][A-Za-z0-9_.:-]*")
_LOCAL_URL = re.compile(r"url\(#[A-Za-z_][A-Za-z0-9_.:-]*\)", re.I)
_SIZE_UNIT = re.compile(
    r"(?:[0-9]|\.)(?:[dsl]?v(?:w|h|i|b|min|max)|cq(?:w|h|i|b|min|max))(?![a-z0-9_-])", re.I
)
_BANNED_WORD = re.compile(r"shape-rendering|vector-effect", re.I)
_MEDIA = re.compile(r"@media([^{]*)(\{|\Z)", re.I)
_MEDIA_ALLOWED = re.compile(
    r"\(\s*(?:prefers-reduced-motion(?:\s*:\s*(?:reduce|no-preference))?"
    r"|prefers-color-scheme(?:\s*:\s*(?:dark|light))?)\s*\)",
    re.I,
)
_MEDIA_WORDS = re.compile(r"(?:\s|,|all|and|not|only|or|screen)*", re.I)
_CALL = re.compile(r"""([^\s()\[\]{}<>;:,'"`=+*/!@#$%^&|~?]{0,64})\(""")
_AT = re.compile(r"""@([^\s{};("'/]*)""")
_MOVES = re.compile(r"animation|transition|@keyframes", re.I)


def value_problems(value):
    """Why the app refuses this CSS text or attribute value; empty if it passes."""
    why = []
    if "\\" in value:
        why.append("a backslash")
    unit = _SIZE_UNIT.search(value)
    if unit:
        near = value[max(0, unit.start() - 8):unit.end() + 4]
        why.append(f"a viewport or container unit, or a name that reads as one, at {near!r}")
    if _BANNED_WORD.search(value):
        why.append("shape-rendering or vector-effect")
    for media in _MEDIA.finditer(value):
        asked = _MEDIA_ALLOWED.sub("", media.group(1))
        if media.group(2) != "{" or not _MEDIA_WORDS.fullmatch(asked):
            why.append(
                f"@media{media.group(1)}: it may only ask prefers-reduced-motion and prefers-color-scheme"
            )
    if "data:" in _SPACE.sub("", value).lower():
        why.append("data:")
    if "url(" in _SPACE.sub("", _LOCAL_URL.sub("", value)).lower():
        why.append("a url() that is not exactly url(#id)")
    for call in _CALL.finditer(value):
        name = call.group(1).lower()
        if name not in ("", "url") and name not in FUNCTIONS:
            why.append(
                f"{call.group(1)}(): not a function the app allows "
                "(a bracket that is no call needs a space before it, as in '@media (')"
            )
    for at in _AT.finditer(value):
        if at.group(1).lower() not in AT_RULES:
            why.append(f"@{at.group(1)}: only @keyframes, @media, @supports and @layer")
    return why


def _attribute_problems(el, attr, doc_root):
    ns, name, value = attr.namespaceURI, attr.localName, attr.value
    if ns is None:
        allowed = not name.lower().startswith("on")
    elif ns == XLINK_NS:
        allowed = name == "href"
    elif ns == XML_NS:
        allowed = name in ("space", "lang")
    else:
        allowed = ns == XMLNS_NS and value in (SVG_NS, XLINK_NS)
    if not allowed or _BANNED_WORD.search(name) or (el.localName == "style" and name == "media"):
        return ["the app does not allow this attribute"]
    if name.lower() == "href" and ns != XMLNS_NS:
        return [] if _LOCAL_ID.fullmatch(value) else ["href has to be #id"]
    if name == "attributeName" and el.localName in SMIL:
        target = re.sub(r"^.*:", "", value.strip().lower(), flags=re.S)
        if el.hasAttributeNS(None, "href"):
            aims_at_root = el.getAttributeNS(None, "href") == "#" + doc_root.getAttribute("id")
        elif el.hasAttributeNS(XLINK_NS, "href"):
            aims_at_root = el.getAttributeNS(XLINK_NS, "href") == "#" + doc_root.getAttribute("id")
        else:
            aims_at_root = el.parentNode is doc_root
        if target in ("href", "media", "style") or (target in ("height", "width") and aims_at_root):
            return [f"SMIL may not animate {target} here"]
    return [] if ns == XMLNS_NS else value_problems(value)


def scene_problems(svg):
    """Why the desktop app would not let this scene move; empty if it would.

    The app parses the scene as strict XML and walks every node. It allows only
    the elements in ELEMENTS, in the SVG namespace; no on* attribute; href only
    as #id; and every attribute value and the whole <style> text must pass
    value_problems. Text inside <text> is not checked.
    """
    if len(svg) > LIMIT:
        return [f"{len(svg):,} characters, over the {LIMIT:,} limit"]
    try:
        doc = minidom.parseString(svg.encode("utf-8"))
    except ExpatError as error:
        return [f"not well-formed XML: {error}"]
    doc_root = doc.documentElement
    problems = []
    if doc.doctype is not None:
        problems.append("a doctype")
    moves = False

    def walk(parent):
        nonlocal moves
        for node in parent.childNodes:
            if node.nodeType == node.ELEMENT_NODE:
                name = node.localName
                if node.namespaceURI != SVG_NS or name not in ELEMENTS:
                    hint = "" if node.namespaceURI == SVG_NS else " (is xmlns on the root?)"
                    problems.append(f"<{node.tagName}> is not an element the app allows{hint}")
                    continue
                for i in range(node.attributes.length):
                    attr = node.attributes.item(i)
                    for why in _attribute_problems(node, attr, doc_root):
                        problems.append(f'<{name} {attr.name}="{attr.value[:48]}">: {why}')
                if name == "style":
                    if any(child.nodeType == child.ELEMENT_NODE for child in node.childNodes):
                        problems.append("<style> holds an element")
                    text = "".join(
                        child.data for child in node.childNodes
                        if child.nodeType in (child.TEXT_NODE, child.CDATA_SECTION_NODE)
                    )
                    problems.extend(f"<style>: {why}" for why in value_problems(text))
                    moves = moves or bool(_MOVES.search(text))
                moves = moves or name in SMIL or bool(_MOVES.search(node.getAttribute("style")))
                walk(node)
            elif node.nodeType not in (node.TEXT_NODE, node.CDATA_SECTION_NODE, node.COMMENT_NODE,
                                       node.DOCUMENT_TYPE_NODE):
                problems.append(f"a {node.nodeName} node: only elements, text and comments are allowed")

    walk(doc)
    if not problems and not moves:
        problems.append("nothing in it moves: no animation in <style> or a style attribute, and no SMIL")
    return list(dict.fromkeys(problems))
