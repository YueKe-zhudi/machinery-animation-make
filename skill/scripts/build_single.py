# -*- coding: utf-8 -*-
"""阶段5：把依赖 importmap + ES module 的多文件页面打包成单文件 HTML。

用法:
    python build_single.py <app.html> [-o single.html]

扫描主模块的所有 import，把它们（含 three、addons）内联为 Blob URL 并动态
import；addon 内部 "from 'three'" 会被改写为 three 的 Blob URL。产物在
file:// 双击即可打开，无需服务器、无需联网。
"""
import argparse, json, os, re, sys


def resolve_local(spec, imports, base):
    """把模块 specifier 解析为本地文件路径。"""
    if spec in imports:
        return imports[spec]
    for prefix, target in imports.items():
        if prefix.endswith("/") and spec.startswith(prefix):
            return target + spec[len(prefix):]
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("html")
    ap.add_argument("-o", "--out", default=None)
    args = ap.parse_args()
    base = os.path.dirname(os.path.abspath(args.html))
    html = open(args.html, encoding="utf-8").read()

    im = re.search(r'<script type="importmap">(.*?)</script>', html, re.S)
    if not im:
        sys.exit("未找到 importmap（可能已是单文件）")
    imports = json.loads(im.group(1)).get("imports", {})
    imports = {k: v for k, v in imports.items()
               if not v.startswith(("http", "data:", "blob:"))}

    # 主模块（最后一个 type=module 的 script，排除 importmap）
    mods = list(re.finditer(r'<script type="module">(.*?)</script>', html, re.S))
    if not mods:
        sys.exit("未找到主模块脚本")
    main_code = mods[-1]
    src = main_code.group(1)

    # 收集所有 import 语句
    import_re = re.compile(
        r"import\s+(\* as \w+|\{[^}]*\})\s+from\s+['\"]([^'\"]+)['\"];")
    specs = []
    for mm in import_re.finditer(src):
        if mm.group(2) not in specs:
            specs.append(mm.group(2))

    # 内联每个模块：源码先存为 raw（依赖处用占位符），运行时再替换为真实 Blob URL
    local_idx = {}   # spec -> 模块序号
    raw_codes = []
    for spec in specs:
        if resolve_local(spec, imports, base) is not None:
            local_idx[spec] = len(raw_codes)
            raw_codes.append(None)
    for i, spec in enumerate(s for s in specs if s in local_idx):
        rel = resolve_local(spec, imports, base)
        code = open(os.path.join(base, rel), encoding="utf-8").read()
        # 对其他本地模块的引用 → 占位符（运行时替换为该模块 Blob URL）
        for dep_spec, j in local_idx.items():
            code = code.replace(f"from '{dep_spec}'", f"from '__BLOB{j}__'")
        raw_codes[local_idx[spec]] = code

    # 扫描每个模块实际依赖的占位符（只替换这些，避免引用未创建的 URL）
    deps = []
    for code in raw_codes:
        found = [int(x) for x in re.findall(r"__BLOB(\d+)__", code)]
        deps.append(sorted(set(found)))

    blob_decls = []
    for i, code in enumerate(raw_codes):
        blob_decls.append(f"const __sRaw{i} = {json.dumps(code)};")
    for i in range(len(raw_codes)):
        fixed = f"__sRaw{i}"
        for j in deps[i]:
            if j == i:
                sys.exit("模块自引用，无法打包")
            fixed = f"{fixed}.split('__BLOB{j}__').join(__u{j})"
        blob_decls.append(f"const __s{i} = {fixed};")
        blob_decls.append(
            f"const __u{i} = URL.createObjectURL(new Blob("
            f"[__s{i}],{{type:'text/javascript'}}));")
    blob_urls = {spec: f"__u{i}" for spec, i in local_idx.items()}

    # 主代码：静态 import → 动态 import(blobURL)
    def conv(mm):
        clause, spec = mm.group(1), mm.group(2)
        url = blob_urls.get(spec, f"'{spec}'")
        if clause.startswith("* as "):
            return f"const {clause[5:]} = await import({url});"
        return f"const {clause} = await import({url});"

    new_src = import_re.sub(conv, src)
    loader = "\n".join(blob_decls) + "\n" + new_src

    # 先替换主模块（在 importmap 之后，不影响 importmap 位置），再移除 importmap
    new_tag = '<script type="module">\n' + loader + '\n</script>'
    html = html[:main_code.start()] + new_tag + html[main_code.end():]
    html = html[:im.start()] + html[im.end():]

    out = args.out or os.path.join(
        base, os.path.splitext(os.path.basename(args.html))[0] + "_single.html")
    open(out, "w", encoding="utf-8", newline="").write(html)
    print("已生成:", out, "(", round(os.path.getsize(out) / 1024), "KB )")


if __name__ == "__main__":
    main()
