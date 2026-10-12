"""Marási vektorfájl (SVG + DXF) generálása a "Sebészeti Osztály" táblához.

Használat:
    python3 generate.py <EB Garamond 500 woff> <EB Garamond 700 woff>

Minden méret mm-ben. Az SVG koordináta-rendszere bal felső sarok origójú (y lefelé),
a DXF bal alsó sarok origójú (y felfelé), ahogy a CAM programok várják.
"""

import io
import sys
from pathlib import Path

import ezdxf
import uharfbuzz as hb
from fontTools.pens.basePen import BasePen
from fontTools.ttLib import TTFont

W, H = 297.0, 210.0          # tábla mérete
HOLE_D = 12.5                # sarokfuratok átmérője
HOLE_OFFSET = 15.0           # furatközép távolsága a tábla szélétől
FLATTEN_STEPS = 12           # görbe szegmensenkénti felbontás a DXF-hez

OUT = Path(__file__).parent


class FlattenPen(BasePen):
    """Glif körvonalakat zárt sokszögekké bont (font egységben)."""

    def __init__(self, glyphset):
        super().__init__(glyphset)
        self.contours, self.cur = [], []

    def _moveTo(self, p):
        self.cur = [p]

    def _lineTo(self, p):
        self.cur.append(p)

    def _curveToOne(self, p1, p2, p3):
        p0 = self.cur[-1]
        for i in range(1, FLATTEN_STEPS + 1):
            t = i / FLATTEN_STEPS
            u = 1 - t
            self.cur.append((
                u**3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t**3 * p3[0],
                u**3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t**3 * p3[1],
            ))

    def _qCurveToOne(self, p1, p2):
        p0 = self.cur[-1]
        for i in range(1, FLATTEN_STEPS + 1):
            t = i / FLATTEN_STEPS
            u = 1 - t
            self.cur.append((
                u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0],
                u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1],
            ))

    def _closePath(self):
        if len(self.cur) > 2:
            if self.cur[0] == self.cur[-1]:
                self.cur.pop()
            self.contours.append(self.cur)
        self.cur = []

    _endPath = _closePath


class Font:
    def __init__(self, path):
        self.tt = TTFont(path)
        self.upem = self.tt["head"].unitsPerEm
        self.glyphset = self.tt.getGlyphSet()
        self.order = self.tt.getGlyphOrder()
        # A HarfBuzz nem olvas WOFF-ot, ezért sima TTF-ként adjuk át.
        self.tt.flavor = None
        data = io.BytesIO()
        self.tt.save(data)
        self.hbfont = hb.Font(hb.Face(data.getvalue()))

    def layout(self, text, tracking_em=0.0):
        """Visszaadja a (glifnév, x_offset, y_offset) listát és a teljes szélességet font egységben."""
        buf = hb.Buffer()
        buf.add_str(text)
        buf.guess_segment_properties()
        hb.shape(self.hbfont, buf, {"kern": True, "liga": False})
        x, out = 0, []
        track = tracking_em * self.upem
        for info, pos in zip(buf.glyph_infos, buf.glyph_positions):
            out.append((self.order[info.codepoint], x + pos.x_offset, pos.y_offset))
            x += pos.x_advance + track
        return out, x - track

    def text_contours(self, text, size_mm, cx, baseline, tracking_em=0.0):
        """Középre zárt szöveg kontúrjai mm-ben (SVG koordinátákban, y lefelé)."""
        glyphs, width = self.layout(text, tracking_em)
        s = size_mm / self.upem
        x0 = cx - width * s / 2
        contours = []
        for name, gx, gy in glyphs:
            pen = FlattenPen(self.glyphset)
            self.glyphset[name].draw(pen)
            for c in pen.contours:
                contours.append([(x0 + (px + gx) * s, baseline - (py + gy) * s) for px, py in c])
        return contours, width * s

    def size_for_width(self, text, width_mm, tracking_em=0.0):
        return width_mm * self.upem / self.layout(text, tracking_em)[1]


def bbox(contours):
    xs = [p[0] for c in contours for p in c]
    ys = [p[1] for c in contours for p in c]
    return min(xs), min(ys), max(xs), max(ys)


def main(font_medium, font_bold):
    med, bold = Font(font_medium), Font(font_bold)
    cx = W / 2

    # A grafikai tervből lemért szélességek és alapvonalak (mm).
    name_size = bold.size_for_width("Dr. Sándor József", 190)
    line1_size = med.size_for_width("A Sebészeti Osztály felújítását támogatta", 210)
    year_track = 0.12

    layers = {
        # réteg: (kontúrok, javasolt mélység leírása)
        "SZOVEG_0.5mm": [],
        "SZOVEG_0.3mm": [],
    }
    l1, _ = med.text_contours("A Sebészeti Osztály felújítását támogatta", line1_size, cx, 52.0)
    n1, _ = bold.text_contours("Dr. Sándor József", name_size, cx, 96.0)
    es, _ = med.text_contours("és", line1_size * 1.05, cx, 119.0)
    n2, _ = bold.text_contours("Derczó István", name_size, cx, 151.0)
    yr, yr_w = med.text_contours("2026", line1_size * 1.05, cx, 186.0, year_track)
    layers["SZOVEG_0.3mm"] += l1
    layers["SZOVEG_0.5mm"] += n1 + es + n2 + yr

    # Évszám melletti díszvonalak: középvonalak, egy V-maró menettel.
    _, yr_top, _, yr_bot = bbox(yr)
    rule_y = (yr_top + yr_bot) / 2
    gap, rule_len = 9.0, 33.0
    rules = [
        [(cx - yr_w / 2 - gap - rule_len, rule_y), (cx - yr_w / 2 - gap, rule_y)],
        [(cx + yr_w / 2 + gap, rule_y), (cx + yr_w / 2 + gap + rule_len, rule_y)],
    ]

    holes = [(HOLE_OFFSET, HOLE_OFFSET), (W - HOLE_OFFSET, HOLE_OFFSET),
             (HOLE_OFFSET, H - HOLE_OFFSET), (W - HOLE_OFFSET, H - HOLE_OFFSET)]

    write_svg(layers, rules, holes)
    write_dxf(layers, rules, holes)

    print(f"Név betűméret: {name_size:.2f} mm (em), felső sor: {line1_size:.2f} mm (em)")
    for name, cs in layers.items():
        x0, y0, x1, y1 = bbox(cs)
        print(f"{name}: x {x0:.1f}–{x1:.1f}, y {y0:.1f}–{y1:.1f} mm, {len(cs)} kontúr")
    for label, cs in (("felső sor", l1), ("Dr. Sándor József", n1), ("és", es),
                      ("Derczó István", n2), ("2026", yr)):
        x0, y0, x1, y1 = bbox(cs)
        print(f"  {label}: {x1 - x0:.1f} × {y1 - y0:.1f} mm (y {y0:.1f}–{y1:.1f})")
    print(f"Díszvonalak: y = {rule_y:.2f} mm, {rule_len} mm hosszúak")


def poly_d(c):
    return "M" + " L".join(f"{x:.3f},{y:.3f}" for x, y in c) + " Z"


def write_svg(layers, rules, holes):
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" '
        f'width="{W}mm" height="{H}mm" viewBox="0 0 {W} {H}">',
        f'<g id="KONTUR" inkscape:groupmode="layer" inkscape:label="KONTUR (tábla széle, csak referencia)">'
        f'<rect x="0" y="0" width="{W}" height="{H}" fill="none" stroke="#888" stroke-width="0.1"/></g>',
        '<g id="FURAT" inkscape:groupmode="layer" inkscape:label="FURAT (Ø12.5)">'
        + "".join(f'<circle cx="{x}" cy="{y}" r="{HOLE_D / 2}" fill="none" stroke="#c00" stroke-width="0.1"/>'
                  for x, y in holes) + "</g>",
    ]
    for name, cs in layers.items():
        parts.append(
            f'<g id="{name}" inkscape:groupmode="layer" inkscape:label="{name}">'
            f'<path d="{" ".join(poly_d(c) for c in cs)}" fill="#000" fill-rule="nonzero" stroke="none"/></g>')
    parts.append(
        '<g id="VONAL_0.15mm" inkscape:groupmode="layer" inkscape:label="VONAL_0.15mm (középvonal)">'
        + "".join(f'<path d="M{a[0]:.3f},{a[1]:.3f} L{b[0]:.3f},{b[1]:.3f}" fill="none" stroke="#000" stroke-width="0.7"/>'
                  for a, b in rules) + "</g>")
    parts.append("</svg>")
    (OUT / "tabla-maras.svg").write_text("\n".join(parts), encoding="utf-8")


def write_dxf(layers, rules, holes):
    doc = ezdxf.new("R2010", setup=False)
    doc.units = ezdxf.units.MM
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    for name, color in (("KONTUR", 8), ("FURAT", 1), ("SZOVEG_0.5mm", 7), ("SZOVEG_0.3mm", 5), ("VONAL_0.15mm", 3)):
        doc.layers.add(name, color=color)

    def flip(p):
        return (p[0], H - p[1])

    msp.add_lwpolyline([(0, 0), (W, 0), (W, H), (0, H)], close=True, dxfattribs={"layer": "KONTUR"})
    for x, y in holes:
        msp.add_circle(flip((x, y)), HOLE_D / 2, dxfattribs={"layer": "FURAT"})
    for name, cs in layers.items():
        for c in cs:
            msp.add_lwpolyline([flip(p) for p in c], close=True, dxfattribs={"layer": name})
    for a, b in rules:
        msp.add_line(flip(a), flip(b), dxfattribs={"layer": "VONAL_0.15mm"})
    doc.saveas(OUT / "tabla-maras.dxf")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
