# -*- coding: utf-8 -*-
"""阶段2：从 CAD 装配中测量齿轮的齿数 / 齿顶圆 / 齿宽 / 螺旋角。

用法:
    python measure_gears.py <model.stp> <gears.json> [-o gear_params.json]

gears.json 格式（实例 id 与轴中心，轴中心可从 extract_instances 的结果读取）:
    { "5":  {"tag":"input_drive",  "cx":0, "cy":0},
      "6":  {"tag":"counter_input","cx":0, "cy":70.5} }

原理: 三角化点云 → 中段截面取最大半径轮廓 → FFT 找齿数基频 + 迟滞数峰 →
前后截面相位差求螺旋角。无需人工数齿，对斜齿/直齿都适用。
"""
import argparse, json, math, sys
import numpy as np


def section_profile(pts, cx, cy, z0, half_w, N=2048):
    """z0±half_w 截面，按 θ 取最大半径，返回 (ang, prof)。"""
    x = pts[:, 0] - cx
    y = pts[:, 1] - cy
    z = pts[:, 2]
    m = np.abs(z - z0) < half_w
    if m.sum() < 100:
        return None
    r = np.hypot(x[m], y[m])
    th = np.arctan2(y[m], x[m])
    idx = ((th + math.pi) / (2 * math.pi) * N).astype(int) % N
    prof = np.full(N, np.nan)
    for i in np.argsort(-r):
        b = idx[i]
        if np.isnan(prof[b]):
            prof[b] = r[i]
    ang = np.linspace(-math.pi, math.pi, N, endpoint=False)
    valid = ~np.isnan(prof)
    if valid.sum() < N * 0.5:
        prof = np.interp(ang, ang[valid], prof[valid], period=2 * math.pi)
    else:
        prof = np.where(valid, prof, np.nanmedian(prof))
    return ang, prof


def count_teeth(ang, prof, zmin=9, zmax=120):
    """FFT 基频 + 迟滞数峰，返回 (fft齿数, 实际峰数, 平滑轮廓)。"""
    N = len(ang)
    p = np.convolve(np.tile(prof, 3)[N:2 * N], np.ones(5) / 5, mode="same")
    sig = p - p.mean()
    sp = np.abs(np.fft.rfft(sig))
    freqs = np.fft.rfftfreq(N, d=1 / N)
    cand = (freqs >= zmin) & (freqs <= zmax)
    f0 = int(round(freqs[cand][np.argmax(sp[cand])]))
    period = N / f0
    hi = p.max() - (p.max() - p.min()) * 0.35
    lo = p.max() - (p.max() - p.min()) * 0.65
    peaks, i = [], 0
    while i < N:
        if p[i] > hi:
            j = i
            while j < N and p[j] > lo:
                j += 1
            s, e = max(0, i - 2), min(N, j + 3)
            pk = s + int(np.argmax(p[s:e]))
            if not peaks or (pk - peaks[-1]) % N > period * 0.6:
                peaks.append(pk)
            i = j
        else:
            i += 1
    if len(peaks) > 1 and (N - peaks[-1] + peaks[0]) < period * 0.6:
        peaks.pop()
    return f0, len(peaks), p


def analyze(pts, cx, cy):
    """返回单个齿轮的参数 dict。"""
    x = pts[:, 0] - cx
    y = pts[:, 1] - cy
    r = np.hypot(x, y)
    z = pts[:, 2]
    rmax = np.percentile(r, 99.9)
    tm = r > rmax * 0.97
    zt = z[tm]
    zc = (zt.min() + zt.max()) / 2
    fw = zt.max() - zt.min()
    sec = section_profile(pts, cx, cy, zc, max(2.0, fw * 0.12))
    if sec is None:
        return None
    ang, prof = sec
    f0, npeaks, _ = count_teeth(ang, prof)
    # 螺旋角：前后截面相位差
    zf, zr = zc - fw * 0.33, zc + fw * 0.33
    sf = section_profile(pts, cx, cy, zf, 1.8)
    sr = section_profile(pts, cx, cy, zr, 1.8)
    beta = 0.0
    if sf and sr:
        af, pf = sf
        ar, pr = sr
        pf, pr = pf - pf.mean(), pr - pr.mean()
        cf, cr = np.fft.rfft(pf), np.fft.rfft(pr)
        dphi = np.angle(cr[f0]) - np.angle(cf[f0])
        while dphi > math.pi / f0:
            dphi -= 2 * math.pi
        while dphi < -math.pi / f0:
            dphi += 2 * math.pi
        beta = math.degrees(math.atan(rmax * 0.93 * abs(dphi) / (zr - zf)))
    return dict(rmax=round(float(rmax), 2), zc=round(float(zc), 2),
                facew=round(float(fw), 2), teeth_fft=f0, teeth=npeaks,
                helix_deg=round(float(beta), 1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stp")
    ap.add_argument("gears", help="齿轮清单 JSON（实例id→{tag,cx,cy}）")
    ap.add_argument("-o", "--out", default="gear_params.json")
    args = ap.parse_args()

    from OCP.STEPCAFControl import STEPCAFControl_Reader
    from OCP.TDocStd import TDocStd_Document
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.XCAFApp import XCAFApp_Application
    from OCP.XCAFDoc import XCAFDoc_DocumentTool, XCAFDoc_ShapeTool
    from OCP.TDF import TDF_LabelSequence, TDF_Label
    from OCP.TDataStd import TDataStd_Name
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopoDS import TopoDS
    from OCP.BRep import BRep_Tool
    from OCP.TopLoc import TopLoc_Location

    def get_name(label):
        attr = TDataStd_Name()
        if label.FindAttribute(TDataStd_Name.GetID_s(), attr):
            return attr.Get().ToExtString()
        return "?"

    def tessellate(shape, deflection=0.2):
        BRepMesh_IncrementalMesh(shape, deflection, False, 0.35, True)
        pts = []
        ex = TopExp_Explorer(shape, TopAbs_FACE)
        while ex.More():
            face = TopoDS.Face_s(ex.Current())
            loc = TopLoc_Location()
            tri = BRep_Tool.Triangulation_s(face, loc)
            if tri is not None:
                trsf = loc.Transformation()
                for i in range(1, tri.NbNodes() + 1):
                    p = tri.Node(i).Transformed(trsf)
                    pts.append((p.X(), p.Y(), p.Z()))
            ex.Next()
        return np.array(pts)

    app = XCAFApp_Application.GetApplication_s()
    doc = TDocStd_Document(TCollection_ExtendedString("XmlXCAF"))
    app.NewDocument(TCollection_ExtendedString("XmlXCAF"), doc)
    reader = STEPCAFControl_Reader()
    reader.SetNameMode(True)
    reader.ReadFile(args.stp)
    reader.Transfer(doc)
    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    labels = TDF_LabelSequence()
    shape_tool.GetShapes(labels)
    root = next((labels.Value(i) for i in range(1, labels.Length() + 1)
                 if XCAFDoc_ShapeTool.IsAssembly_s(labels.Value(i))), None)
    instances = []

    def walk(asm, ploc):
        comps = TDF_LabelSequence()
        XCAFDoc_ShapeTool.GetComponents_s(asm, comps)
        for j in range(1, comps.Length() + 1):
            c = comps.Value(j)
            loc = XCAFDoc_ShapeTool.GetLocation_s(c)
            world = ploc.Multiplied(loc) if ploc is not None else loc
            proto = TDF_Label()
            XCAFDoc_ShapeTool.GetReferredShape_s(c, proto)
            instances.append((get_name(proto),
                              shape_tool.GetShape_s(c).Located(world)))
            if XCAFDoc_ShapeTool.IsAssembly_s(proto):
                walk(proto, world)

    walk(root, None)
    gears = json.load(open(args.gears, encoding="utf-8"))
    results = {}
    for iid, spec in gears.items():
        name, shape = instances[int(iid)]
        info = analyze(tessellate(shape), spec["cx"], spec["cy"])
        if info:
            info["tag"], info["step_name"] = spec.get("tag", ""), name
            results[iid] = info
            print(json.dumps({"id": iid, **info}, ensure_ascii=False))
    json.dump(results, open(args.out, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("→", args.out)


if __name__ == "__main__":
    main()
