"""Marási vektorfájlok (SVG + DXF) generálása a "Sebészeti Osztály" táblához.

Használat:
    python3 generate.py <EB Garamond 500 woff> <EB Garamond 700 woff>

Kimenetek (minden méret mm-ben):
  tabla-maras.dxf         betűk ívekből és egyenesekből (zárt LWPOLYLINE bulge-dzsal),
                          a CNC G2/G3 ívekként tudja marni – ez az ajánlott
  tabla-maras-spline.dxf  betűk pontos görbékként (kontúronként egy SPLINE)
  tabla-maras.svg         betűk pontos Bézier-görbékként

Az SVG bal felső sarok origójú (y lefelé), a DXF bal alsó sarok origójú (y felfelé).
"""

import io
import math
import sys
from pathlib import Path

import ezdxf
import uharfbuzz as hb
from ezdxf.math import Bezier4P, Vec3, bezier_to_bspline
from fontTools.pens.basePen import BasePen
from fontTools.ttLib import TTFont

W, H = 297.0, 210.0          # tábla mérete
HOLE_D = 12.5                # sarokfuratok átmérője
HOLE_OFFSET = 15.0           # furatközép távolsága a tábla szélétől
ARC_TOL = 0.01               # ívközelítés megengedett eltérése a görbétől (mm)

OUT = Path(__file__).parent


# ---------------------------------------------------------------------------
# Glif körvonalak szegmensekként: ("L", p0, p1) vagy ("C", p0, c1, c2, p3),
# mm-ben, DXF koordinátákban (y felfelé).

class SegmentPen(BasePen):
    def __init__(self, glyphset, transform):
        super().__init__(glyphset)
        self.tf = transform
        self.contours, self.cur, self.start, self.last = [], [], None, None

    def _moveTo(self, p):
        self.start = self.last = self.tf(p)
        self.cur = []

    def _lineTo(self, p):
        p = self.tf(p)
        if p != self.last:
            self.cur.append(("L", self.last, p))
        self.last = p

    def _curveToOne(self, p1, p2, p3):
        p3 = self.tf(p3)
        self.cur.append(("C", self.last, self.tf(p1), self.tf(p2), p3))
        self.last = p3

    def _qCurveToOne(self, p1, p2):
        # Másodfokú görbe pontosan átírva harmadfokúra.
        p0, q, p2 = self.last, self.tf(p1), self.tf(p2)
        c1 = (p0[0] + 2 / 3 * (q[0] - p0[0]), p0[1] + 2 / 3 * (q[1] - p0[1]))
        c2 = (p2[0] + 2 / 3 * (q[0] - p2[0]), p2[1] + 2 / 3 * (q[1] - p2[1]))
        self.cur.append(("C", p0, c1, c2, p2))
        self.last = p2

    def _closePath(self):
        if self.last != self.start:
            self.cur.append(("L", self.last, self.start))
        if self.cur:
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
        """(glifnév, x_offset, y_offset) lista és teljes szélesség font egységben, alávágással."""
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

    def text(self, text, size_mm, cx, baseline, tracking_em=0.0):
        """Középre zárt szöveg kontúrjai. baseline az SVG szerinti (felülről mért) y."""
        glyphs, width = self.layout(text, tracking_em)
        s = size_mm / self.upem
        x0 = cx - width * s / 2
        contours = []
        for name, gx, gy in glyphs:
            pen = SegmentPen(self.glyphset, lambda p, gx=gx, gy=gy: (
                round(x0 + (p[0] + gx) * s, 6), round(H - baseline + (p[1] + gy) * s, 6)))
            self.glyphset[name].draw(pen)
            contours += pen.contours
        return contours, width * s

    def size_for_width(self, text, width_mm, tracking_em=0.0):
        return width_mm * self.upem / self.layout(text, tracking_em)[1]


# ---------------------------------------------------------------------------
# Bézier görbék közelítése körívekkel (biarc), ARC_TOL pontossággal.

def _sub(a, b): return (a[0] - b[0], a[1] - b[1])
def _add(a, b): return (a[0] + b[0], a[1] + b[1])
def _mul(a, k): return (a[0] * k, a[1] * k)
def _dot(a, b): return a[0] * b[0] + a[1] * b[1]
def _cross(a, b): return a[0] * b[1] - a[1] * b[0]
def _len(a): return math.hypot(*a)


def _unit(a):
    n = _len(a)
    return (a[0] / n, a[1] / n) if n > 1e-12 else None


def _bez(c, t):
    p0, p1, p2, p3 = c
    u = 1 - t
    return (u**3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t**3 * p3[0],
            u**3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t**3 * p3[1])


def _split(c):
    p0, p1, p2, p3 = c
    m = lambda a, b: ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    a, b, cc = m(p0, p1), m(p1, p2), m(p2, p3)
    d, e = m(a, b), m(b, cc)
    f = m(d, e)
    return (p0, a, d, f), (f, e, cc, p3)


def _tangents(c):
    p0, p1, p2, p3 = c
    t0 = _unit(_sub(p1, p0)) or _unit(_sub(p2, p0)) or _unit(_sub(p3, p0))
    t1 = _unit(_sub(p3, p2)) or _unit(_sub(p3, p1)) or _unit(_sub(p3, p0))
    return t0, t1


def _arc(a, ta, b):
    """Ív a-ból b-be, a-ban ta érintővel: (bulge, középpont, sugár) vagy egyenesnél (0, None, None)."""
    chord = _sub(b, a)
    s = _cross(ta, chord)
    c = _dot(ta, chord)
    alpha = math.atan2(s, c)              # érintő és húr közti előjeles szög
    if abs(alpha) < 1e-9:
        return 0.0, None, None
    n = (-ta[1], ta[0])
    r = _dot(chord, chord) / (2 * _dot(n, chord))
    return math.tan(alpha / 2), _add(a, _mul(n, r)), abs(r)


def _biarc(p0, t0, p1, t1):
    """Két érintőfolytonos ív p0→p1. Visszaad: [(start, end, bulge, center, r), ...] vagy None."""
    v = _sub(p1, p0)
    t = _add(t0, t1)
    denom = 2 * (1 - _dot(t0, t1))
    if denom < 1e-9:
        vt2 = _dot(v, t1)
        if abs(vt2) < 1e-9:
            return None
        d = _dot(v, v) / (4 * vt2)
    else:
        vt = _dot(v, t)
        d = (-vt + math.sqrt(vt * vt + denom * _dot(v, v))) / denom
    pm = _mul(_add(_add(p0, p1), _mul(_sub(t0, t1), d)), 0.5)
    out = []
    for a, ta, b in ((p0, t0, pm), (pm, None, p1)):
        if ta is None:
            # A második ív kezdő érintője az első ív végérintője.
            b0, c0, _ = out[0][2], out[0][3], out[0][4]
            if c0 is None:
                ta = t0
            else:
                rad = _sub(pm, c0)
                ta = _unit((-rad[1], rad[0]) if b0 > 0 else (rad[1], -rad[0]))
        bulge, center, r = _arc(a, ta, b)
        out.append((a, b, bulge, center, r))
    return out


def _dist_to_piece(p, piece):
    a, b, bulge, center, r = piece
    if center is None:
        ab = _sub(b, a)
        L2 = _dot(ab, ab)
        t = 0 if L2 == 0 else max(0.0, min(1.0, _dot(_sub(p, a), ab) / L2))
        return _len(_sub(p, _add(a, _mul(ab, t))))
    # Szögtartományon belül a körtől mért távolság, különben a végpontoktól.
    ang = lambda q: math.atan2(q[1] - center[1], q[0] - center[0])
    sweep = 4 * math.atan(bulge)
    ra = (ang(p) - ang(a)) * (1 if sweep > 0 else -1) % (2 * math.pi)
    if ra <= abs(sweep):
        return abs(_len(_sub(p, center)) - r)
    return min(_len(_sub(p, a)), _len(_sub(p, b)))


def bezier_to_arcs(c, depth=0):
    """[(pont, bulge), ...] a görbe kezdőpontjától (a végpont nélkül)."""
    t0, t1 = _tangents(c)
    pieces = _biarc(c[0], t0, c[3], t1) if t0 and t1 else None
    if pieces:
        err = max(min(_dist_to_piece(_bez(c, i / 16), pc) for pc in pieces) for i in range(1, 16))
        if err <= ARC_TOL or depth >= 10:
            return [(pc[0], pc[2]) for pc in pieces if _len(_sub(pc[1], pc[0])) > 1e-9]
    if depth >= 10:
        return [(c[0], 0.0)]
    l, r = _split(c)
    return bezier_to_arcs(l, depth + 1) + bezier_to_arcs(r, depth + 1)


def _fit_run(run):
    """Egyetlen biarc a sima görbelánc elejétől a végéig, ha mindenhol belefér a tűrésbe."""
    t0, _ = _tangents(run[0])
    _, t1 = _tangents(run[-1])
    if not (t0 and t1):
        return None
    pieces = _biarc(run[0][0], t0, run[-1][3], t1)
    if not pieces:
        return None
    for c in run:
        for i in range(0 if c is not run[0] else 1, 16):
            if min(_dist_to_piece(_bez(c, i / 16), pc) for pc in pieces) > ARC_TOL:
                return None
    return [(pc[0], pc[2]) for pc in pieces if _len(_sub(pc[1], pc[0])) > 1e-9]


def _smooth_join(a, b):
    """Érintőfolytonos-e a két görbe találkozása (a betű sarkait nem simítjuk le)."""
    _, ta = _tangents(a)
    tb, _ = _tangents(b)
    return ta and tb and _dot(ta, tb) > math.cos(math.radians(2))


def contour_to_bulge_polyline(contour):
    pts, i = [], 0
    while i < len(contour):
        seg = contour[i]
        if seg[0] == "L":
            pts.append((seg[1], 0.0))
            i += 1
            continue
        # A sima görbeláncot mohón a lehető leghosszabb biarc-cal fedjük le.
        best, j = None, i
        while j < len(contour) and contour[j][0] == "C" and (j == i or _smooth_join(contour[j - 1][1:], contour[j][1:])):
            fit = _fit_run([s[1:] for s in contour[i:j + 1]])
            if fit is None:
                break
            best, j = fit, j + 1
        if best is None:
            pts += bezier_to_arcs(seg[1:])
            i += 1
        else:
            pts += best
            i = j
    return [(p[0], p[1], 0, 0, b) for p, b in pts]


# ---------------------------------------------------------------------------

def bbox(contours):
    pts = [p for c in contours for seg in c for p in seg[1:]]
    xs, ys = [p[0] for p in pts], [H - p[1] for p in pts]   # SVG-szerinti y
    return min(xs), min(ys), max(xs), max(ys)


def main(font_medium, font_bold):
    med, bold = Font(font_medium), Font(font_bold)
    cx = W / 2

    # A grafikai tervből lemért szélességek és alapvonalak (mm, felülről).
    name_size = bold.size_for_width("Dr. Sándor József", 190)
    line1_size = med.size_for_width("A Sebészeti Osztály felújítását támogatta", 210)
    year_track = 0.12

    l1, _ = med.text("A Sebészeti Osztály felújítását támogatta", line1_size, cx, 52.0)
    n1, _ = bold.text("Dr. Sándor József", name_size, cx, 96.0)
    es, _ = med.text("és", line1_size * 1.05, cx, 119.0)
    n2, _ = bold.text("Derczó István", name_size, cx, 151.0)
    yr, yr_w = med.text("2026", line1_size * 1.05, cx, 186.0, year_track)
    layers = {"SZOVEG_0.5mm": n1 + es + n2 + yr, "SZOVEG_0.3mm": l1}

    # Évszám melletti díszvonalak: középvonalak, egy V-maró menettel.
    _, yr_top, _, yr_bot = bbox(yr)
    rule_y = H - (yr_top + yr_bot) / 2
    gap, rule_len = 9.0, 33.0
    rules = [((cx - yr_w / 2 - gap - rule_len, rule_y), (cx - yr_w / 2 - gap, rule_y)),
             ((cx + yr_w / 2 + gap, rule_y), (cx + yr_w / 2 + gap + rule_len, rule_y))]

    holes = [(HOLE_OFFSET, HOLE_OFFSET), (W - HOLE_OFFSET, HOLE_OFFSET),
             (HOLE_OFFSET, H - HOLE_OFFSET), (W - HOLE_OFFSET, H - HOLE_OFFSET)]

    write_svg(layers, rules, holes)
    n_arcs = write_dxf_arcs(layers, rules, holes)
    write_dxf_splines(layers, rules, holes)

    print(f"Név betűméret: {name_size:.2f} mm (em), felső sor: {line1_size:.2f} mm (em)")
    for label, cs in (("felső sor", l1), ("Dr. Sándor József", n1), ("és", es),
                      ("Derczó István", n2), ("2026", yr)):
        x0, y0, x1, y1 = bbox(cs)
        print(f"  {label}: {x1 - x0:.1f} × {y1 - y0:.1f} mm (y {y0:.1f}–{y1:.1f})")
    print(f"Ív-DXF: {n_arcs} csomópont, tűrés {ARC_TOL} mm")


DXF_LAYERS = (("KONTUR", 8), ("FURAT", 1), ("SZOVEG_0.5mm", 7), ("SZOVEG_0.3mm", 5), ("VONAL_0.15mm", 3))


def _new_dxf(rules, holes):
    doc = ezdxf.new("R2010", setup=False)
    doc.units = ezdxf.units.MM
    for name, color in DXF_LAYERS:
        doc.layers.add(name, color=color)
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (W, 0), (W, H), (0, H)], close=True, dxfattribs={"layer": "KONTUR"})
    for x, y in holes:
        msp.add_circle((x, y), HOLE_D / 2, dxfattribs={"layer": "FURAT"})
    for a, b in rules:
        msp.add_line(a, b, dxfattribs={"layer": "VONAL_0.15mm"})
    return doc, msp


def write_dxf_arcs(layers, rules, holes):
    doc, msp = _new_dxf(rules, holes)
    n = 0
    for name, cs in layers.items():
        for c in cs:
            pts = contour_to_bulge_polyline(c)
            n += len(pts)
            msp.add_lwpolyline(pts, format="xyseb", close=True, dxfattribs={"layer": name})
    doc.saveas(OUT / "tabla-maras.dxf")
    return n


def write_dxf_splines(layers, rules, holes):
    doc, msp = _new_dxf(rules, holes)
    for name, cs in layers.items():
        for c in cs:
            curves = []
            for seg in c:
                if seg[0] == "L":
                    a, b = Vec3(seg[1]), Vec3(seg[2])
                    curves.append(Bezier4P([a, a.lerp(b, 1 / 3), a.lerp(b, 2 / 3), b]))
                else:
                    curves.append(Bezier4P([Vec3(p) for p in seg[1:]]))
            msp.add_spline(dxfattribs={"layer": name}).apply_construction_tool(bezier_to_bspline(curves))
    doc.saveas(OUT / "tabla-maras-spline.dxf")


def write_svg(layers, rules, holes):
    f = lambda p: f"{p[0]:.4f},{H - p[1]:.4f}"

    def path_d(c):
        d = [f"M{f(c[0][1])}"]
        for seg in c:
            d.append(f"L{f(seg[2])}" if seg[0] == "L" else f"C{f(seg[2])} {f(seg[3])} {f(seg[4])}")
        return "".join(d) + "Z"

    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" '
        f'width="{W}mm" height="{H}mm" viewBox="0 0 {W} {H}">',
        f'<g id="KONTUR" inkscape:groupmode="layer" inkscape:label="KONTUR (tábla széle, csak referencia)">'
        f'<rect x="0" y="0" width="{W}" height="{H}" fill="none" stroke="#888" stroke-width="0.1"/></g>',
        '<g id="FURAT" inkscape:groupmode="layer" inkscape:label="FURAT (Ø12.5)">'
        + "".join(f'<circle cx="{x}" cy="{H - y}" r="{HOLE_D / 2}" fill="none" stroke="#c00" stroke-width="0.1"/>'
                  for x, y in holes) + "</g>",
    ]
    for name, cs in layers.items():
        parts.append(
            f'<g id="{name}" inkscape:groupmode="layer" inkscape:label="{name}">'
            f'<path d="{" ".join(path_d(c) for c in cs)}" fill="#000" fill-rule="nonzero" stroke="none"/></g>')
    parts.append(
        '<g id="VONAL_0.15mm" inkscape:groupmode="layer" inkscape:label="VONAL_0.15mm (középvonal)">'
        + "".join(f'<path d="M{f(a)} L{f(b)}" fill="none" stroke="#000" stroke-width="0.7"/>' for a, b in rules)
        + "</g>")
    parts.append("</svg>")
    (OUT / "tabla-maras.svg").write_text("\n".join(parts), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
