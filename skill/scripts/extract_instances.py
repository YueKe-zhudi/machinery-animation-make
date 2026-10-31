# -*- coding: utf-8 -*-
"""阶段1：遍历 CAD 装配（STEP/STP），提取每个零件实例的世界坐标、包围盒、层级。

用法:
    python extract_instances.py <model.stp> [-o instances.json]

依赖: cadquery 或 OCP (pip install cadquery)。输出 JSON 列表，每个元素含
name / depth / x,y,z（世界平移）/ bbox / id，用于后续定位轴、齿轮、机构。
"""
import argparse, json, sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stp", help="STEP/STP 装配文件路径")
    ap.add_argument("-o", "--out", default="instances.json")
    args = ap.parse_args()

    from OCP.STEPCAFControl import STEPCAFControl_Reader
    from OCP.TDocStd import TDocStd_Document
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.XCAFApp import XCAFApp_Application
    from OCP.XCAFDoc import XCAFDoc_DocumentTool, XCAFDoc_ShapeTool
    from OCP.TDF import TDF_LabelSequence, TDF_Label
    from OCP.TDataStd import TDataStd_Name
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    def get_name(label):
        attr = TDataStd_Name()
        if label.FindAttribute(TDataStd_Name.GetID_s(), attr):
            return attr.Get().ToExtString()
        return "?"

    def bbox(shape):
        b = Bnd_Box()
        BRepBndLib.Add_s(shape, b)
        if b.IsVoid():
            return None
        xmin, ymin, zmin, xmax, ymax, zmax = b.Get()
        return [round(xmin, 2), round(ymin, 2), round(zmin, 2),
                round(xmax, 2), round(ymax, 2), round(zmax, 2)]

    app = XCAFApp_Application.GetApplication_s()
    doc = TDocStd_Document(TCollection_ExtendedString("XmlXCAF"))
    app.NewDocument(TCollection_ExtendedString("XmlXCAF"), doc)
    reader = STEPCAFControl_Reader()
    reader.SetNameMode(True)
    if reader.ReadFile(args.stp) != 1:
        sys.exit("无法读取 STEP 文件: " + args.stp)
    reader.Transfer(doc)

    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    labels = TDF_LabelSequence()
    shape_tool.GetShapes(labels)
    root = None
    for i in range(1, labels.Length() + 1):
        if XCAFDoc_ShapeTool.IsAssembly_s(labels.Value(i)):
            root = labels.Value(i)
            break
    if root is None:
        sys.exit("未找到装配根节点（可能是单零件，无需实例提取）")

    instances = []

    def walk(asm, parent_loc, depth):
        comps = TDF_LabelSequence()
        XCAFDoc_ShapeTool.GetComponents_s(asm, comps)
        for j in range(1, comps.Length() + 1):
            c = comps.Value(j)
            loc = XCAFDoc_ShapeTool.GetLocation_s(c)
            world = parent_loc.Multiplied(loc) if parent_loc is not None else loc
            proto = TDF_Label()
            XCAFDoc_ShapeTool.GetReferredShape_s(c, proto)
            shape_w = shape_tool.GetShape_s(c).Located(world)
            t = world.Transformation()
            v = t.TranslationPart()
            instances.append(dict(
                name=get_name(proto), depth=depth,
                x=round(v.X(), 2), y=round(v.Y(), 2), z=round(v.Z(), 2),
                bbox=bbox(shape_w)))
            if XCAFDoc_ShapeTool.IsAssembly_s(proto):
                walk(proto, world, depth + 1)

    walk(root, None, 0)
    for k, ins in enumerate(instances):
        ins["id"] = k
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(instances, f, ensure_ascii=False, indent=1)
    print("实例数:", len(instances), "→", args.out)


if __name__ == "__main__":
    main()
