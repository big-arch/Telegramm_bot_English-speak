"""Portraits of the conversation partners, drawn in code.

No faces, deliberately. A face drawn with SVG primitives lands somewhere between
clip art and the uncanny valley, and a generated photograph of a person who does
not exist is a stranger the learner is invited to believe in. What these are
instead is closer to a book-jacket or a gig poster: each partner gets a colour
that is their mood, a large initial, and a fine line drawing of the thing their
life is about — Ethan's building elevation with a dimension line, Ava's skyline,
Jake's waves under a striped sun. It is the same move a good illustrator makes
when a likeness would be weaker than a symbol.

One source for both uses: the Mini App serves these as SVG directly, and
`scripts/render_avatars.py` rasterises them to PNG for Telegram, which will not
send an SVG as a photo.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

SIZE = 800

# Georgia where the device has it, Charter where the renderer has it. The
# initial carries the whole composition, so it gets the best serif available.
SERIF = "Georgia, 'Bitstream Charter', 'Charter', 'DejaVu Serif', serif"
SANS = "-apple-system, 'Helvetica Neue', 'Liberation Sans', Arial, sans-serif"


@dataclass(frozen=True)
class Look:
    top: str          # gradient, top-left
    bottom: str       # gradient, bottom-right
    subtitle: str     # small caps under the name
    motif: Callable[[], str]


# --------------------------------------------------------------------------- #
# Motifs. All drawn in the right and lower part of the square, so the initial
# at top-left is never crossed by a line — the composition is an L, and the
# eye enters at the letter.
# --------------------------------------------------------------------------- #


def _emma() -> str:
    """A London sash window in the rain, and Biscuit on the sill."""
    rain = "".join(
        f'<line x1="{x}" y1="{y}" x2="{x - 26}" y2="{y + 70}"/>'
        for x, y in [
            (520, 150), (600, 120), (680, 170), (760, 140), (560, 300),
            (650, 270), (730, 320), (500, 440), (610, 470), (700, 430),
            (770, 500), (540, 600), (660, 640), (750, 610),
        ]
    )
    window = (
        '<path d="M470 640 V300 Q470 180 590 180 Q710 180 710 300 V640 Z"/>'
        '<line x1="590" y1="180" x2="590" y2="640"/>'
        '<line x1="470" y1="420" x2="710" y2="420"/>'
        '<line x1="440" y1="640" x2="740" y2="640" stroke-width="3"/>'
    )
    # Sitting cat, three curves: back, ears, tail.
    cat = (
        '<path d="M600 640 Q596 600 610 585 L606 566 L618 578 Q626 575 634 578 '
        'L646 566 L642 585 Q656 600 652 640" fill="rgba(255,255,255,.5)" stroke="none"/>'
        '<path d="M652 632 Q690 628 684 604" stroke-width="3"/>'
    )
    return f'<g stroke-opacity=".28">{rain}</g><g>{window}</g>{cat}'


def _jake() -> str:
    """Pacific swell under a striped low sun."""
    sun = '<circle cx="590" cy="330" r="120" fill="rgba(255,255,255,.18)" stroke="none"/>'
    stripes = "".join(
        f'<rect x="460" y="{y}" width="260" height="{h}" fill="url(#bg)" stroke="none"/>'
        for y, h in [(352, 6), (376, 9), (404, 12), (436, 16)]
    )
    waves = "".join(
        f'<path d="M380 {y} q52 -{a} 104 0 t104 0 t104 0 t104 0 t104 0"/>'
        for y, a in [(480, 22), (530, 26), (580, 30), (630, 34), (680, 38), (730, 42)]
    )
    return f"{sun}{stripes}<g>{waves}</g>"


def _sofia() -> str:
    """Building blocks: A, B, C — the first three things anyone learns."""
    blocks = []
    for x, y, rot, letter in [(470, 470, -6, "A"), (600, 490, 5, "B"), (530, 330, -2, "C")]:
        blocks.append(
            f'<g transform="rotate({rot} {x + 60} {y + 60})">'
            f'<rect x="{x}" y="{y}" width="120" height="120" rx="18"/>'
            f'<text x="{x + 60}" y="{y + 86}" text-anchor="middle" font-family="{SERIF}" '
            f'font-size="72" fill="rgba(255,255,255,.75)" stroke="none">{letter}</text></g>'
        )
    dots = "".join(
        f'<circle cx="{x}" cy="{y}" r="5" fill="rgba(255,255,255,.4)" stroke="none"/>'
        for x, y in [(700, 250), (730, 300), (450, 640), (740, 660)]
    )
    return "".join(blocks) + dots


def _chen() -> str:
    """A ruled page and a single, precise quotation mark."""
    rules = "".join(
        f'<line x1="440" y1="{y}" x2="760" y2="{y}"/>' for y in range(200, 661, 30)
    )
    margin = '<line x1="480" y1="170" x2="480" y2="680" stroke-opacity=".6"/>'
    quote = (
        f'<text x="560" y="470" font-family="{SERIF}" font-size="320" '
        'fill="rgba(255,255,255,.55)" stroke="none">“</text>'
    )
    underline = '<line x1="540" y1="560" x2="720" y2="560" stroke-width="4"/>'
    return f'<g stroke-opacity=".22">{rules}</g>{margin}{quote}{underline}'


def _ava() -> str:
    """Manhattan at night: the Empire State, the Chrysler, and a thin moon.

    Drawn back to front with every building filled with the sky, so the nearer
    ones hide what stands behind them. Outlines crossing one another read as a
    wireframe rather than a city.
    """
    moon = (
        '<path d="M690 120 a62 62 0 1 0 62 80 a50 50 0 1 1 -62 -80 Z" '
        'fill="rgba(255,255,255,.7)" stroke="none"/>'
    )
    base = 700
    sky = 'fill="url(#bg)"'
    back = "".join(
        f'<rect x="{x}" y="{base - h}" width="{w}" height="{h}" {sky} stroke-opacity=".25"/>'
        for x, w, h in [(392, 60, 300), (600, 70, 330), (720, 70, 250)]
    )
    empire = (
        f'<path {sky} d="M500 {base} V430 H514 V380 H528 V330 H540 V262 H546 V196 H550 V262 '
        f'H556 V330 H568 V380 H582 V430 H596 V{base} Z"/>'
    )
    chrysler = (
        f'<path {sky} d="M650 {base} V430 Q650 380 678 344 Q706 380 706 430 V{base} Z"/>'
        '<path d="M660 410 Q678 370 696 410"/><path d="M666 388 Q678 362 690 388"/>'
        '<line x1="678" y1="344" x2="678" y2="296"/>'
    )
    front = "".join(
        f'<rect x="{x}" y="{base - h}" width="{w}" height="{h}" {sky}/>'
        for x, w, h in [(420, 70, 170), (590, 56, 120), (740, 60, 150)]
    )
    lights = "".join(
        f'<rect x="{x}" y="{y}" width="5" height="8" fill="rgba(255,236,200,.75)" stroke="none"/>'
        for x, y in [(436, 560), (462, 600), (520, 470), (560, 520), (540, 610),
                     (606, 610), (668, 470), (690, 540), (756, 580), (772, 640)]
    )
    ground = f'<line x1="380" y1="{base}" x2="800" y2="{base}" stroke-width="3"/>'
    return moon + back + empire + chrysler + front + lights + ground


def _ethan() -> str:
    """An elevation on blueprint grid, dimensioned the way he would."""
    grid = "".join(
        f'<line x1="{x}" y1="120" x2="{x}" y2="720"/>' for x in range(420, 801, 40)
    ) + "".join(f'<line x1="400" y1="{y}" x2="800" y2="{y}"/>' for y in range(120, 721, 40))
    floors = "".join(f'<line x1="500" y1="{y}" x2="720" y2="{y}"/>' for y in range(300, 641, 68))
    windows = "".join(
        f'<rect x="{x}" y="{y}" width="30" height="40"/>'
        for x in range(520, 700, 50) for y in range(314, 600, 68)
    )
    body = '<rect x="500" y="232" width="220" height="408" stroke-width="3"/>'
    roof = '<path d="M490 232 L610 176 L730 232"/>'
    # Dimension line with ticks and a figure, because an architect cannot draw
    # a building without saying how big it is.
    dim = (
        '<line x1="460" y1="232" x2="460" y2="640"/>'
        '<line x1="450" y1="232" x2="470" y2="232"/><line x1="450" y1="640" x2="470" y2="640"/>'
        f'<text x="446" y="446" font-family="{SANS}" font-size="20" letter-spacing="2" '
        'fill="rgba(255,255,255,.7)" stroke="none" transform="rotate(-90 446 446)" '
        'text-anchor="middle">12 400</text>'
    )
    ground = '<line x1="420" y1="640" x2="790" y2="640" stroke-width="3"/>'
    return f'<g stroke-opacity=".12">{grid}</g>{body}{roof}{floors}{windows}{dim}{ground}'


def _marcus() -> str:
    """A front page: a headline bar and three columns of copy."""
    headline = '<rect x="430" y="170" width="320" height="34" fill="rgba(255,255,255,.55)" stroke="none"/>'
    sub = '<rect x="430" y="220" width="220" height="14" fill="rgba(255,255,255,.3)" stroke="none"/>'
    rule = '<line x1="430" y1="258" x2="760" y2="258" stroke-width="3"/>'
    columns = []
    for x in (430, 545, 660):
        for i, y in enumerate(range(286, 681, 22)):
            width = 90 if (i + x) % 7 else 60
            columns.append(f'<line x1="{x}" y1="{y}" x2="{x + width}" y2="{y}"/>')
    # A pull quote the copy breaks around, set the way a newspaper sets one,
    # rather than a glyph lying on top of the columns.
    pull = (
        '<rect x="530" y="370" width="240" height="152" fill="url(#bg)" stroke="none"/>'
        '<line x1="548" y1="382" x2="752" y2="382"/>'
        '<line x1="548" y1="510" x2="752" y2="510"/>'
        f'<text x="596" y="560" font-family="{SERIF}" font-size="220" '
        'fill="rgba(255,255,255,.6)" stroke="none">”</text>'
    )
    return f'{headline}{sub}{rule}<g stroke-opacity=".3">{"".join(columns)}</g>{pull}'


LOOKS: dict[str, Look] = {
    "emma":   Look("#2E4B47", "#7D93A1", "LONDON · 29", _emma),
    "jake":   Look("#E8573F", "#F4B63A", "SAN DIEGO · 26", _jake),
    "sofia":  Look("#E0876F", "#B8638F", "TEACHER · 34", _sofia),
    "chen":   Look("#0D2744", "#1E6B74", "IELTS · 41", _chen),
    "ava":    Look("#24163A", "#B06A78", "NEW YORK · 35", _ava),
    "ethan":  Look("#0A3A8C", "#4474AA", "CHICAGO · 35", _ethan),
    "marcus": Look("#1B1B1D", "#6E1F27", "JOURNALIST · 38", _marcus),
}


def svg(key: str, name: str) -> str:
    """The portrait for one partner. Unknown keys get a neutral card, not an error."""
    look = LOOKS.get(key) or Look("#3A3A48", "#6A6A80", "", lambda: "")
    initial = (name.replace("Dr. ", "")[:1] or "?").upper()

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {SIZE} {SIZE}" width="{SIZE}" height="{SIZE}">
  <defs>
    <linearGradient id="bg" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="{SIZE}" y2="{SIZE}">
      <stop offset="0" stop-color="{look.top}"/>
      <stop offset="1" stop-color="{look.bottom}"/>
    </linearGradient>
    <radialGradient id="glow" cx=".18" cy=".12" r=".9">
      <stop offset="0" stop-color="#fff" stop-opacity=".22"/>
      <stop offset=".55" stop-color="#fff" stop-opacity="0"/>
    </radialGradient>
    <radialGradient id="vignette" cx=".5" cy=".5" r=".75">
      <stop offset=".6" stop-color="#000" stop-opacity="0"/>
      <stop offset="1" stop-color="#000" stop-opacity=".28"/>
    </radialGradient>
    <filter id="grain" x="0" y="0" width="100%" height="100%">
      <feTurbulence type="fractalNoise" baseFrequency=".85" numOctaves="2" stitchTiles="stitch"/>
      <feColorMatrix values="0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  0 0 0 .07 0"/>
    </filter>
  </defs>
  <rect width="{SIZE}" height="{SIZE}" fill="url(#bg)"/>
  <rect width="{SIZE}" height="{SIZE}" fill="url(#glow)"/>
  <g fill="none" stroke="#fff" stroke-opacity=".42" stroke-width="2"
     stroke-linecap="round" stroke-linejoin="round">{look.motif()}</g>
  <text x="58" y="360" font-family="{SERIF}" font-size="340" fill="#fff"
        fill-opacity=".94">{initial}</text>
  <rect x="64" y="628" width="44" height="4" fill="#fff" fill-opacity=".8"/>
  <text x="62" y="700" font-family="{SERIF}" font-size="58" fill="#fff">{name}</text>
  <text x="64" y="742" font-family="{SANS}" font-size="20" letter-spacing="6"
        fill="#fff" fill-opacity=".72">{look.subtitle}</text>
  <rect width="{SIZE}" height="{SIZE}" fill="url(#vignette)"/>
  <rect width="{SIZE}" height="{SIZE}" filter="url(#grain)"/>
</svg>"""
