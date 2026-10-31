# 排查与踩坑

## 目录
- [离线/打包相关](#离线打包相关)
- [渲染与动画循环](#渲染与动画循环)
- [headless 截图](#headless-截图)
- [CAD 解析环境](#cad-解析环境)
- [几何与运动学](#几何与运动学)

## 离线/打包相关

**file:// 双击黑屏 / CORS 报错**
- 现象：用 importmap + ES module 的多文件页面，`file://` 打开时控制台报
  `CORS policy: Cross origin requests are only supported for HTTP…`，页面黑屏。
- 原因：浏览器禁止 `file://` 下用 fetch/import 加载本地模块。
- 解决：用 `scripts/build_single.py` 把所有模块内联为 Blob URL 动态加载；
  产物双击即用。开发期可用 `python -m http.server` 起本地服务。

**不能把多个模块源码简单拼进一个 `<script>`**
- 现象：`Identifier '_xxx' already declared`。
- 原因：各模块顶层私有变量同名，拼到同一作用域就冲突。
- 解决：保持模块作用域隔离——每个模块各自生成 Blob，再 `import(blobURL)`。

**addon 内 `from 'three'` 报错 `Failed to resolve module specifier`**
- 原因：改写时填了变量名（如 `__u0`），模块说明符必须是 URL。
- 解决：源码里用占位符，运行时把占位符替换成 three 的**真实 Blob URL 字符串**
  后再创建 addon 的 Blob（`build_single.py` 已处理）。

**`Cannot access '__uX' before initialization`**
- 原因：替换占位符时引用了尚未创建的 Blob URL。
- 解决：每个模块只替换它实际依赖的占位符，且依赖模块先创建（按依赖顺序）。

**`import * as THREE` 变成 `HREE`**
- 原因：`"* as "` 是 5 个字符，切片偏移写错（用了 6）。
- 解决：去掉前缀时用 `clause.slice(5)`。

## 渲染与动画循环

**后台/隐藏标签里动画不动（rAF 冻结）**
- 现象：页面 `visibilityState = hidden` 时 `requestAnimationFrame` 不触发，
  截图/自动化时画面静止。
- 解决：
  - 双驱动：rAF 之外再加 `setInterval(tick, 30)` 兜底；
  - 提供静态跳转函数（如 `jumpToGear(g)`），不依赖动画累积即可定位；
  - 支持 URL hash（`#g1`…）直接进入工况。

**首帧黑屏/闪烁**
- 顶层 `await import(...)` 异步加载期间场景未就绪；可先显示加载提示，
  加载完成后再渲染；确保 `renderer.render` 在首个工况数据就绪后调用。

## headless 截图

**Edge/Chrome headless 截图偶发黑屏（只截到 UI，3D 网格缺失）**
- 命令：
  ```
  msedge --headless=new --disable-gpu --window-size=1500,900
         --screenshot=OUT.png --virtual-time-budget=40000 URL
  ```
- 原因：`--disable-gpu` 用 SwiftShader 软件渲染，配合顶层 await，
  第一帧 3D 可能尚未绘制就截图；表现为文件明显偏小（如 70–90KB vs 正常 300+KB）。
- 解决：这是**工具时序问题，不是产物 bug**。多重试几次（常需 2–4 次）；
  加大 `--virtual-time-budget`（≥30000，顶层 await 建议 40000–50000）。
- 判定：用真实浏览器（或 Browser Use）打开正常即视为通过，勿因单次黑屏误判。

**同 query 改 hash 不重新加载**
- 自动化中同一 URL 仅改 `#hash` 可能不触发重载；加唯一查询参数 `?v=时间戳`。

## CAD 解析环境

**安装 cadquery / OCP**
- `pip install cadquery`（会带入 OCP = OpenCascade Python 绑定）。
- 导入按 `from OCP.XXX import ...`；不同版本个别类名/方法签名可能不同，
  以报错为准调整（如 `GetApplication_s`、`ShapeTool_s` 等静态方法）。
- 大文件（数十 MB STP）读取/三角化较慢，先对单个零件做诊断再批量。

**三角化精度**
- `BRepMesh_IncrementalMesh(shape, deflection, ...)`：deflection 越小越精细但越慢；
  测齿数用 0.15–0.2 即可，齿顶薄层可适当调小。

## 几何与运动学

**齿轮穿插/侧隙**
- 配对齿轮按理论节圆会视觉穿插；齿顶间留 0.5–1mm 侧隙，或略微缩小齿顶。

**齿数测错**
- 截面要取在齿宽中点、避开倒角/退刀槽；FFT 限定合理齿数范围（如 9–120），
  再用迟滞数峰交叉验证；斜齿取垂直于轴的端面。

**空套齿轮与轴转速混淆**
- 空套齿轮未挂挡时不随轴；务必为"轴"和"空套齿轮"分别存储角速度，
  挂挡（同步器锁死）后再令二者相等。

**转向符号**
- 外啮合带负号、内啮合/同带轮不带；倒挡经惰轮累计外啮合次数决定符号。
