"""Badge rendering, shared by every action in this repo that draws one.

Text is laid out from measured font metrics and pinned with `textLength`, so a
viewer resolving Verdana, DejaVu Sans, Noto or nothing at all gets the same
badge: the glyphs adjust to the box rather than the box guessing at the glyphs.
Nothing is scaled and no font is fetched.

Adding a style is one class plus one line in `STYLES`.
"""

import hashlib
import typing


class Geom(typing.NamedTuple):
    """Everything a badge style needs to lay its bars out."""

    label_w: float
    value_w: float
    width: float
    height: int
    fraction: float
    color: str
    label_color: str


class Flat:
    """The classic two-slab badge: label on the left, value on the right."""

    BAR = 0

    def bars(self, geom):
        return (
            f'<rect width="{geom.label_w}" height="{geom.height}" fill="{geom.label_color}"/>'
            f'<rect x="{geom.label_w}" width="{geom.value_w}" height="{geom.height}"'
            f' fill="{geom.color}"/>'
        )


class Gauge:
    """Two slabs, but the value slab is a fill gauge.

    Reads as a proportion at a glance, at the cost of putting the value text
    over two different backgrounds.
    """

    TRACK = "#30363d"
    BAR = 0

    def bars(self, geom):
        fill = round(geom.value_w * geom.fraction, 1)
        return (
            f'<rect width="{geom.label_w}" height="{geom.height}" fill="{geom.label_color}"/>'
            f'<rect x="{geom.label_w}" width="{geom.value_w}" height="{geom.height}"'
            f' fill="{self.TRACK}"/>'
            f'<rect x="{geom.label_w}" width="{fill}" height="{geom.height}"'
            f' fill="{geom.color}"/>'
        )


class Meter:
    """One solid field, with the proportion as a rule along the bottom edge.

    Every glyph sits on the same background, so contrast never depends on where
    the fill happens to end -- the failure mode of any badge that runs text over
    a partial fill. The colour still carries the reading twice: the value text
    and the rule beneath it.
    """

    TRACK = "#30363d"
    BAR = 3

    def bars(self, geom):
        fill = round(geom.width * geom.fraction, 1)
        y = geom.height - self.BAR
        return (
            f'<rect width="{geom.width}" height="{geom.height}" fill="{geom.label_color}"/>'
            f'<rect y="{y}" width="{geom.width}" height="{self.BAR}" fill="{self.TRACK}"/>'
            f'<rect y="{y}" width="{fill}" height="{self.BAR}" fill="{geom.color}"/>'
        )


STYLES = {"flat": Flat, "gauge": Gauge, "meter": Meter}


class Badge:
    """An SVG badge. The bar geometry is delegated to a style from `STYLES`.

    Text is laid out from real font metrics and pinned with `textLength`, so the
    result is identical whether the viewer resolves Verdana, DejaVu Sans or a
    fallback: the glyphs adjust to the box rather than the box guessing at the
    glyphs. Nothing is scaled, and no font is fetched.
    """

    HEIGHT, PADDING, FONT, RADIUS = 20, 10, 11, 3
    BASELINE = 14  # 11px text sits optically centred in a 20px box here.

    # Advance widths of printable ASCII in DejaVu Sans at 11px, measured from
    # the font. Index is `ord(ch) - 32`; anything outside is charged as "M".
    WIDTHS = (
        3.5, 4.41, 5.06, 9.22, 7, 10.45, 8.58, 3.02, 4.29, 4.29, 5.5, 9.22, 3.5,
        3.97, 3.5, 3.71, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 3.71, 3.71, 9.22, 9.22,
        9.22, 5.84, 11, 7.53, 7.55, 7.68, 8.47, 6.95, 6.33, 8.52, 8.27, 3.24,
        3.24, 7.21, 6.13, 9.49, 8.23, 8.66, 6.63, 8.66, 7.64, 6.98, 6.72, 8.05,
        7.53, 10.88, 7.54, 6.72, 7.54, 4.29, 3.71, 4.29, 9.22, 5.5, 5.5, 6.74,
        6.98, 6.05, 6.98, 6.77, 3.87, 6.98, 6.97, 3.06, 3.06, 6.37, 3.06, 10.72,
        6.97, 6.73, 6.98, 6.98, 4.52, 5.73, 4.31, 6.97, 6.51, 9, 6.51, 6.51, 5.77,
        7, 3.71, 7, 9.22
    )

    def __init__(self, style, label, value, percent, color, label_color):
        self.style = style
        self.label, self.value, self.percent = label, value, percent
        self.color, self.label_color = color, label_color

    @classmethod
    def of(cls, name, **kw):
        if name not in STYLES:
            raise SystemExit(
                f"::error::unknown badge style {name!r}; expected one of "
                + ", ".join(sorted(STYLES))
            )
        return cls(STYLES[name](), **kw)

    @classmethod
    def text_width(cls, text):
        """Rendered width of `text`, in px, at the badge font size."""
        fallback = cls.WIDTHS[ord("M") - 32]
        return sum(
            cls.WIDTHS[ord(ch) - 32] if 32 <= ord(ch) < 127 else fallback
            for ch in text
        )

    @classmethod
    def slab(cls, text):
        """Width of the half holding `text`, padded either side."""
        return round(cls.text_width(text) + 2 * cls.PADDING, 1)

    @staticmethod
    def color_for(percent, thresholds, fallback="#e5534b"):
        """First `min:color` entry, highest first, whose min is at or below `percent`."""
        for entry in thresholds.split(","):
            floor, _, color = entry.partition(":")
            floor = floor.strip()
            if floor.isdigit() and percent >= int(floor):
                return color.strip() or fallback
        return fallback

    @staticmethod
    def escape(text):
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def _text(self, centre, body, raw, weight, fill, shadow=True):
        # Drawn twice where a shadow is wanted: a translucent black copy one
        # pixel lower keeps light text legible over a light fill.
        length = round(self.text_width(raw), 1)
        common = (
            f'text-anchor="middle" textLength="{length}" '
            f'lengthAdjust="spacingAndGlyphs" font-weight="{weight}"'
        )
        x = round(centre, 1)
        under = (
            f'<text x="{x}" y="{self.BASELINE + 1}" fill="#010101" '
            f'fill-opacity=".25" {common}>{body}</text>'
            if shadow
            else ""
        )
        return under + (
            f'<text x="{x}" y="{self.BASELINE}" fill="{fill}" {common}>{body}</text>'
        )

    def render(self):
        label, value = self.escape(self.label), self.escape(self.value)
        label_w, value_w = self.slab(self.label), self.slab(self.value)
        width = round(label_w + value_w, 1)
        height = self.HEIGHT + getattr(self.style, "BAR", 0)
        geom = Geom(
            label_w=label_w,
            value_w=value_w,
            width=width,
            height=height,
            fraction=max(0.0, min(self.percent, 100.0)) / 100.0,
            color=self.color,
            label_color=self.label_color,
        )
        # A style that paints one flat field wants the value in the accent
        # colour and no shadow; a style that paints coloured slabs wants white
        # text with a shadow to survive whatever is behind it.
        solid = getattr(self.style, "BAR", 0) > 0
        label_fill = "#adbac7" if solid else "#fff"
        value_fill = self.color if solid else "#fff"

        # The id is per-badge, so two badges inlined in one document do not share
        # a clip path. Derived from a stable digest rather than hash(), which is
        # salted per process and would change the bytes on every run.
        digest = hashlib.sha1(f"{self.label}\x00{self.value}".encode()).hexdigest()
        cid = f"c{digest[:8]}"
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}"'
            f' viewBox="0 0 {width} {height}" role="img"'
            f' aria-label="{label}: {value}">'
            f"<title>{label}: {value}</title>"
            f'<clipPath id="{cid}">'
            f'<rect width="{width}" height="{height}" rx="{self.RADIUS}"/></clipPath>'
            f'<g clip-path="url(#{cid})" shape-rendering="crispEdges">'
            f"{self.style.bars(geom)}</g>"
            f'<g font-family="Verdana,DejaVu Sans,Noto Sans,Geneva,sans-serif"'
            f' font-size="{self.FONT}">'
            f"{self._text(label_w / 2, label, self.label, 'normal', label_fill, not solid)}"
            f"{self._text(label_w + value_w / 2, value, self.value, 'bold', value_fill, not solid)}"
            f"</g></svg>\n"
        )


