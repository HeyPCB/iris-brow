"""Iris Brow's mechanical facts, measured from the built board, for the mechanism CAD.

Run under KiCad's Python (it carries pcbnew), after the pipeline:

    "${KICAD_APP:-/Applications/KiCad/KiCad.app}/Contents/Frameworks/Python.framework/Versions/Current/bin/python3" \
        boards/iris_brow/coords.py [build/iris_brow/iris_brow.kicad_pcb]

(the interpreter run.sh picks).

It writes build/iris_brow/coords.json, prints the same numbers, and draws build/iris_brow/windows.svg
(the F face with the shell windows; `img/iris_brow_windows.svg` is a copy). Board coordinates are the
brief's frame (mm from the board origin, x right, y down, seen from the F face). Head-frame
coordinates use the Iris spec's binding mapping for B4 (section 4.3): the F face at X_H = +22.0,
Y_H = x - 58, Z_H = 56 - y.

What it reads from the board: the Edge.Cuts bounding box; each mounting hole's and each
microphone's NPTH (position and drill); the touch pads' copper; J1's pads and its F.Fab/B.Fab
outline; every rule area (the brief's windows and keep-outs); and the routed length of each net
per copper layer. Two points come from datasheets, not from the board, and are named as such:
the VL53L1X emitter and receiver centres (ST DocID031281 Rev 3, Figures 18 and 19: 0.97 mm and
3.97 mm from one end of the 4.90 mm package, on its centre line) and the APDS-9306-065 active
area (Broadcom AV02-4755EN, p.18: 0.223 mm off the package centre, toward pins 3 and 4). They are
placed through each footprint's own position and rotation.
"""
import json
import math
import os
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]

import pcbnew  # noqa: E402

F_FACE_X_H = 22.0
CENTRE_X = 58.0
TOP_Z_H = 56.0
# footprint-frame offsets (mm, KiCad's y-down frame at rotation 0); see the docstring
TOF_EMITTER = (-1.52, 0.0)
TOF_RECEIVER = (1.48, 0.0)
ALS_ACTIVE = (0.0, 0.223)


def mm(v):
    return round(pcbnew.ToMM(v), 3)


def head(x, y):
    return {"X_H": F_FACE_X_H, "Y_H": round(x - CENTRE_X, 3), "Z_H": round(TOP_Z_H - y, 3)}


def main():
    pcb = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / "build/iris_brow/iris_brow.kicad_pcb"
    brief = json.loads((HERE / "board.json").read_text())
    ox, oy = brief["board"]["origin"]
    brd = pcbnew.LoadBoard(str(pcb))

    def local(pt):
        return (round(mm(pt.x) - ox, 3), round(mm(pt.y) - oy, 3))

    def place(fp, off):
        """A footprint-frame point -> board frame, through the footprint's own position and rotation."""
        a = math.radians(fp.GetOrientationDegrees())
        x, y = off
        if fp.IsFlipped():
            raise ValueError("%s: datasheet offsets are for a top-side part" % fp.GetReference())
        p = fp.GetPosition()
        bx = pcbnew.ToMM(p.x) + x * math.cos(a) + y * math.sin(a)
        by = pcbnew.ToMM(p.y) - x * math.sin(a) + y * math.cos(a)
        return (round(bx - ox, 3), round(by - oy, 3))

    out = {"board": str(pcb.relative_to(REPO)) if pcb.is_absolute() and REPO in pcb.parents else str(pcb),
           "frame": "mm from the board origin, x right, y down, seen from the F face; head: X_H 22.0 at the F face, "
                    "Y_H = x - 58, Z_H = 56 - y"}
    bb = brd.GetBoardEdgesBoundingBox()
    out["outline_bbox"] = {"x0": round(mm(bb.GetX()) - ox, 3), "y0": round(mm(bb.GetY()) - oy, 3),
                           "x1": round(mm(bb.GetRight()) - ox, 3), "y1": round(mm(bb.GetBottom()) - oy, 3)}
    out["outline_brief"] = {"points": brief["board"]["shape"]["points"], "fillets": brief["board"]["shape"]["fillets"]}
    fps = {fp.GetReference(): fp for fp in brd.GetFootprints()}

    holes = []
    for ref in sorted(r for r in fps if r.startswith("H")):
        for pad in fps[ref].Pads():
            if pad.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH:
                x, y = local(pad.GetPosition())
                holes.append({"ref": ref, "x": x, "y": y, "drill": mm(pad.GetDrillSize().x), "head": head(x, y)})
    out["holes"] = holes

    windows = []
    for ref, name in (("MK2", "MIC R sound port (robot right)"), ("MK1", "MIC L sound port (robot left)")):
        for pad in fps[ref].Pads():
            if pad.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH:
                x, y = local(pad.GetPosition())
                windows.append({"what": name, "ref": ref, "x": x, "y": y, "drill": mm(pad.GetDrillSize().x),
                                "source": "the footprint's NPTH, measured", "head": head(x, y)})
    u1, u2 = fps["U1"], fps["U2"]
    for what, off in (("VL53L1X emitter (EMT, 0.70 mm aperture)", TOF_EMITTER),
                      ("VL53L1X receiver (RTN, 0.85 mm lens)", TOF_RECEIVER)):
        x, y = place(u1, off)
        windows.append({"what": what, "ref": "U1", "x": x, "y": y,
                        "source": "ST DocID031281 Rev 3 Fig. 18-19, through U1's placement", "head": head(x, y)})
    x, y = place(u2, ALS_ACTIVE)
    windows.append({"what": "APDS-9306 active area", "ref": "U2", "x": x, "y": y,
                    "source": "Broadcom AV02-4755EN p.18, through U2's placement", "head": head(x, y)})
    out["windows"] = windows

    parts = {}
    for ref in ("U1", "U2", "MK1", "MK2", "J1", "TP1", "TP2"):
        fp = fps[ref]
        x, y = local(fp.GetPosition())
        parts[ref] = {"x": x, "y": y, "rot": round(fp.GetOrientationDegrees(), 1),
                      "side": "B" if fp.IsFlipped() else "F", "value": fp.GetValue()}
    for ref in ("TP1", "TP2"):
        pb = fps[ref].Pads()[0].GetBoundingBox()
        parts[ref]["copper"] = {"x0": round(mm(pb.GetX()) - ox, 3), "y0": round(mm(pb.GetY()) - oy, 3),
                                "x1": round(mm(pb.GetRight()) - ox, 3), "y1": round(mm(pb.GetBottom()) - oy, 3)}
    j1 = fps["J1"]
    parts["J1"]["pins"] = {p.GetNumber(): local(p.GetPosition()) for p in j1.Pads() if p.GetNumber() in ("1", "8")}
    fab = [g.GetBoundingBox() for g in j1.GraphicalItems() if g.GetLayer() in (pcbnew.F_Fab, pcbnew.B_Fab)
           and g.GetClass() == "PCB_SHAPE"]
    if fab:
        parts["J1"]["body_y"] = [round(min(mm(b.GetY()) for b in fab) - oy, 3), round(max(mm(b.GetBottom()) for b in fab) - oy, 3)]
    out["parts"] = parts

    areas = []
    for z in brd.Zones():
        if not z.GetIsRuleArea():
            continue
        b = z.GetBoundingBox()
        bans = [k for k, f in (("pour", z.GetDoNotAllowZoneFills), ("tracks", z.GetDoNotAllowTracks),
                               ("vias", z.GetDoNotAllowVias), ("footprints", z.GetDoNotAllowFootprints)) if f()]
        areas.append({"name": z.GetZoneName(), "layers": [brd.GetLayerName(l) for l in z.GetLayerSet().CuStack()],
                      "bbox": [round(mm(b.GetX()) - ox, 2), round(mm(b.GetY()) - oy, 2),
                               round(mm(b.GetRight()) - ox, 2), round(mm(b.GetBottom()) - oy, 2)], "no": bans})
    out["rule_areas"] = sorted(areas, key=lambda a: a["name"])

    length = defaultdict(lambda: defaultdict(float))
    vias = defaultdict(int)
    for t in brd.GetTracks():
        if t.GetClass() == "PCB_VIA":
            vias[t.GetNetname()] += 1
        else:
            length[t.GetNetname()][brd.GetLayerName(t.GetLayer())] += pcbnew.ToMM(t.GetLength())
    out["nets"] = {n: {"by_layer_mm": {l: round(v, 1) for l, v in sorted(ls.items())},
                       "total_mm": round(sum(ls.values()), 1), "vias": vias.get(n, 0)}
                   for n, ls in sorted(length.items())}

    poly = pcbnew.SHAPE_POLY_SET()
    brd.GetBoardPolygonOutlines(poly, True)
    ring = poly.Outline(0)
    outline = [local(ring.CPoint(k)) for k in range(ring.PointCount())]

    dest = REPO / "build/iris_brow/coords.json"
    tmp = dest.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(out, indent=2) + "\n")
    os.replace(str(tmp), str(dest))
    svg = REPO / "build/iris_brow/windows.svg"
    tmp = svg.with_suffix(".svg.tmp")
    tmp.write_text(window_map(out, outline))
    os.replace(str(tmp), str(svg))
    print(json.dumps(out, indent=2))


def window_map(m, outline):
    """The F face as the forehead shell sees it: outline, holes, touch copper, and the shell windows
    the Iris spec sizes (section 4.3: a 6 x 3.5 mm ToF slot, a 2 mm ALS hole, 1.0 mm mic holes),
    each centred on the measured or datasheet point above. 10 px per mm."""
    s, mx, my = 10.0, 30.0, 70.0
    X = lambda x: mx + x * s  # noqa: E731
    Y = lambda y: my + y * s  # noqa: E731
    w, h = X(116.0) + mx, Y(12.0) + 75.0
    e = ['<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d" '
         'font-family="Helvetica, Arial, sans-serif">' % (w, h, w, h),
         '<rect width="100%" height="100%" fill="#ffffff"/>',
         '<text x="%.1f" y="22" font-size="15" font-weight="bold" fill="#222">Iris Brow, F face (toward the forehead '
         'shell): shell windows in board mm (x right, y down) and head mm (Y_H = x - 58, Z_H = 56 - y)</text>' % mx,
         '<polygon points="%s" fill="#eef3ea" stroke="#333" stroke-width="1.2"/>'
         % " ".join("%.1f,%.1f" % (X(x), Y(y)) for x, y in outline),
         '<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#999" stroke-dasharray="4 4"/>'
         % (X(58), Y(-1.5), X(58), Y(13.5))]
    for ref in ("TP1", "TP2"):
        c = m["parts"][ref]["copper"]
        e.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="12" fill="#e9c74a" stroke="#a88a12"/>'
                 % (X(c["x0"]), Y(c["y0"]), (c["x1"] - c["x0"]) * s, (c["y1"] - c["y0"]) * s))
        e.append('<text x="%.1f" y="%.1f" font-size="11" text-anchor="middle" fill="#5a4a00">%s touch %.0f x %.0f</text>'
                 % (X((c["x0"] + c["x1"]) / 2), Y(c["y1"]) + 14, ref, c["x1"] - c["x0"], c["y1"] - c["y0"]))
    for hl in m["holes"]:
        e.append('<circle cx="%.1f" cy="%.1f" r="%.1f" fill="#fff" stroke="#333"/>' % (X(hl["x"]), Y(hl["y"]), hl["drill"] / 2 * s))
        e.append('<text x="%.1f" y="%.1f" font-size="11" text-anchor="middle" fill="#333">%s M2 (Y %+.0f)</text>'
                 % (X(hl["x"]), Y(-0.6), hl["ref"], hl["head"]["Y_H"]))
    win = {w_["what"]: w_ for w_ in m["windows"]}
    emt, rtn = win["VL53L1X emitter (EMT, 0.70 mm aperture)"], win["VL53L1X receiver (RTN, 0.85 mm lens)"]
    sx = m["parts"]["U1"]["x"]
    sy = m["parts"]["U1"]["y"]
    e.append('<rect x="%.1f" y="%.1f" width="60" height="35" rx="6" fill="none" stroke="#c0392b" stroke-width="2" '
             'stroke-dasharray="6 3"/>' % (X(sx - 3.0), Y(sy - 1.75)))
    for pt, lab in ((emt, "EMT"), (rtn, "RTN")):
        e.append('<circle cx="%.1f" cy="%.1f" r="3" fill="#c0392b"/>' % (X(pt["x"]), Y(pt["y"])))
        e.append('<text x="%.1f" y="%.1f" font-size="10" text-anchor="middle" fill="#c0392b">%s</text>'
                 % (X(pt["x"]), Y(pt["y"]) + 13, lab))
    e.append('<text x="%.1f" y="%.1f" font-size="11" text-anchor="middle" fill="#c0392b">ToF slot 6 x 3.5 at (%.2f, %.2f) '
             'Y %+.2f Z %.2f</text>' % (X(sx), Y(12.0) + 30, sx, sy, sx - 58.0, 56.0 - sy))
    als = win["APDS-9306 active area"]
    e.append('<circle cx="%.1f" cy="%.1f" r="10" fill="none" stroke="#d35400" stroke-width="2" stroke-dasharray="4 2"/>'
             % (X(als["x"]), Y(als["y"])))
    e.append('<text x="%.1f" y="%.1f" font-size="11" text-anchor="middle" fill="#d35400">ALS 2 mm at (%.2f, %.3f) '
             'Y %+.2f Z %.3f</text>' % (X(als["x"]), Y(12.0) + 46, als["x"], als["y"], als["head"]["Y_H"], als["head"]["Z_H"]))
    for k in ("MIC R sound port (robot right)", "MIC L sound port (robot left)"):
        p = win[k]
        e.append('<circle cx="%.1f" cy="%.1f" r="5" fill="none" stroke="#2471a3" stroke-width="2"/>' % (X(p["x"]), Y(p["y"])))
        e.append('<circle cx="%.1f" cy="%.1f" r="%.1f" fill="#2471a3"/>' % (X(p["x"]), Y(p["y"]), p["drill"] / 2 * s))
        e.append('<text x="%.1f" y="%.1f" font-size="11" text-anchor="%s" fill="#2471a3">%s: 1 mm hole at (%.1f, %.1f) '
                 'Y %+.1f Z %.1f</text>' % (X(p["x"]) + (-6 if p["x"] < 58 else 6), Y(12.0) + 30,
                                            "start" if p["x"] < 58 else "end", k.split(" sound")[0], p["x"], p["y"],
                                            p["head"]["Y_H"], p["head"]["Z_H"]))
    e.append('<text x="%.1f" y="%.1f" font-size="10" fill="#555">Outline: Edge.Cuts as built. Windows: Iris spec 4.3 '
             'sizes on measured centres (ports: the footprint NPTH; EMT/RTN and ALS: datasheet offsets through the '
             'part placement). F face at X_H +22.0; the shell inner face is at least 2.0 mm in front of it.</text>'
             % (mx, h - 8))
    e.append("</svg>\n")
    return "\n".join(e)


if __name__ == "__main__":
    main()
    sys.stdout.flush()
    os._exit(0)  # pcbnew can crash at interpreter teardown
