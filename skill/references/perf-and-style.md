# 性能与美术规范

目标：在不牺牲"教学演示可读性"的前提下，把 GPU/CPU 开销和 token 消耗压到最低。
所有数值都是**默认档**，精细出图时才临时上调。

## 目录
- [三档质量预算](#三档质量预算)
- [材质共享（最重要）](#材质共享最重要)
- [几何精度](#几何精度)
- [渲染与阴影](#渲染与阴影)
- [仪表 DOM 缓存](#仪表-dom-缓存)
- [按需渲染（可选）](#按需渲染可选)
- [美术设计变量](#美术设计变量)
- [金属质感：程序化环境光](#金属质感程序化环境光)
- [响应式与动效](#响应式与动效)

## 三档质量预算

| 项 | 低（快速预览） | 标准（默认） | 高（仅截图） |
|---|---|---|---|
| 像素比 pixelRatio | 1 | ≤1.5 | ≤2 |
| 阴影贴图 | 关 / 512 | 1024 | 2048 |
| 圆柱径向段数 | 12 | 16–20 | 24–32 |
| 齿轮每齿采样点 | 4 | 5–6 | 8 |
| 抗锯齿 | 关 | 开 | 开 |
| 环境贴图 | 无 | 程序化 PMREM | 程序化 PMREM |

切换方式：用一个 `QUALITY` 常量集中控制，不要把数字散落在各处。

## 材质共享（最重要）

**反模式**：在 `buildGear`/零件循环里每次 `new THREE.MeshStandardMaterial`，
即使颜色、金属度完全相同，也会产生重复材质与更多 draw call。

**正解**：建一个材质库，按 key 缓存复用；同一材质可被任意多 mesh 共享。

```js
const MAT = (() => {
  const cache = new Map();
  return (key, opts) => {
    if (!cache.has(key)) cache.set(key, new THREE.MeshStandardMaterial(opts));
    return cache.get(key);
  };
})();
// 钢件统一用 MAT('steel', {color:0x9aa3ad, metalness:.9, roughness:.35})
```

高亮不要 `new THREE.Color`，预分配常量并复用：

```js
const EMISSIVE_ON = new THREE.Color(0xff7a1a), EMISSIVE_OFF = new THREE.Color(0x000000);
mat.emissive = on ? EMISSIVE_ON : EMISSIVE_OFF;
```

## 几何精度

- 演示齿轮用**直线段近似渐开线**即可，每齿 4–6 点；不必生成真实渐开线曲线。
- `CylinderGeometry` 径向段数按上表，轴/孔等小件取低值，肉眼无差别。
- 相同几何也可复用：同规格的螺栓、轴承、小齿圈用同一个 `Geometry`。
- 大齿数（z>50）时优先降每齿点数，而不是整体放大几何。
- 静态、不参与运动的壳体可 `mergeGeometries` 合并，减少 draw call。

## 渲染与阴影

```js
renderer.setPixelRatio(Math.min(devicePixelRatio, 1.5));
key.shadow.mapSize.set(1024, 1024);
```

- 只让需要投影的件 `castShadow`；地面 `receiveShadow`，壳体等大件可只接收不投影。
- 阴影相机范围收紧到实际包围盒，别用过大的正交范围。
- 雾 `Fog` 远端按场景尺度设，避免无意义的远景绘制。

## 仪表 DOM 缓存

每帧 `getElementById` + `innerHTML` 即使数值没变也会触发解析与重排。
缓存节点，且只在显示值变化时写入：

```js
const el = { out: document.getElementById('dOut') };
let lastOut = null;
function updateDashboard(outRpm){
  const txt = Math.round(outRpm);
  if (txt !== lastOut){ el.out.textContent = txt; lastOut = txt; }
}
```

- 用 `textContent` 而非 `innerHTML`（无 HTML 时更快、更安全）。
- 进度条宽度按档位量化（如整数百分比），避免每帧微小改动。

## 按需渲染（可选）

暂停且无交互时持续 rAF 渲染是浪费。可改为"脏标记"渲染：
状态变化、控件交互、OrbitControls 的 `change` 事件时置 `needsRender`，
主循环里仅在运行或脏时 `render`。注意保留静态跳转后的一次渲染。

## 美术设计变量

把颜色、圆角、间距、阴影集中为 CSS 变量（design token），避免硬编码、保证统一：

```css
:root{
  --bg:#0c1016; --panel:rgba(14,19,27,.88);
  --ink:#e8edf4; --muted:#9db4d6;
  --accent:#ff8a2a; --accent2:#3fa0ff;
  --line:rgba(140,170,220,.28);
  --radius:12px; --gap:14px;
  --shadow:0 8px 32px rgba(0,0,0,.45);
}
```

- 强调色克制：一个主强调（橙，用于当前动力流/激活态）+ 一个辅助（蓝，信息/输入）。
- 面板统一毛玻璃 `backdrop-filter:blur(8px)`、圆角与阴影引用变量。
- 数字用 `font-variant-numeric:tabular-nums`，跳动时不抖动。

## 金属质感：程序化环境光

金属度高的材质需要环境反射才有质感，**不要为此下载 HDR**（省算力、免联网）。
用程序化渐变生成 PMREM 环境贴图，几行代码、体积为零：

```js
const pmrem = new THREE.PMREMGenerator(renderer);
const env = pmrem.fromScene(makeGradientEnv(), 0.04).texture;
scene.environment = env;   // 只影响 PBR 反射，不作为背景
```

`makeGradientEnv()` 返回一个含上下渐变 + 几条亮带的简单场景，模拟工作室柔光箱。
钢件反射立刻有层次，而画面背景仍是纯色。

## 响应式与动效

- 小屏（<760px）：左右面板改为底部抽屉或缩小宽度，`clamp()` 控制字号与间距。
- 按钮/面板过渡用 `transition:all .15s`，激活态加柔和发光，避免突兀。
- 尊重 `prefers-reduced-motion`：关闭非必要的发光/位移动效。
- 所有可点控件有 `:hover`/`:focus-visible` 态，键盘可达。
