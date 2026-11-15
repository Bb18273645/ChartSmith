# 更新日志

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [1.0.0] - 2026-11-15

首个正式发布版本：功能、配置项与 JSON 契约从此保持稳定（0.2.0 的能力全部包含在内）。

### 新增

- **授权：AGPL-3.0-or-later + 商业双许可**。`LICENSE` 为 AGPL 官方全文；新增 `NOTICE`（版权与上游信息）、`ADDITIONAL-TERMS.md`（依 AGPL §7(b) 的署名与上游说明要求）、`COMMERCIAL-LICENSE.md`（商业许可说明与申请流程）；源文件加入 `SPDX-License-Identifier: AGPL-3.0-or-later`。
- **开源发布配套**：GitHub 用 README（预览图 / 安装 / JSON 契约 / 配置 / QQ·TG 适配 / 工作原理 / FAQ）、`docs/插件介绍.md`（插件市场提交文案）、`docs/发布说明-v1.0.0.md`（Release 正文）、`docs/二改与授权须知.md`（AGPL 合规与商业授权指南）。
- `.gitattributes` 统一 LF 换行；`.gitignore` 排除运行时 `data/` 与缓存目录。

### 变更

- `metadata.yaml`：版本号改为 `1.0.0`，补充 `repo`、`social_link`、`tags` 与多行 `desc`，便于上架插件市场。
- 文档与示例统一按 `v1.0.0` 标注。

## [0.2.0] - 2026-11-15

面向 QQ / Telegram 的打磨版本：图片发得更干净、手机上看字更大、失败不再静默。

### 新增

- 方向自适应（`auto_direction`）：同时计算上下（TB）和左右（LR）两版布局，按「宽度为主、高度为辅」挑手机上更好读的一版。
- 输出尺寸上限：`max_width`（默认 2048）、`max_height`（默认 3200），超过等比缩小，避免群图被 QQ 二次压缩发糊。
- emoji 清洗：`✅ ❌ ⚠` 等中文字体缺字形的 emoji 映射为 `√ × !`，其余 emoji 删除，杜绝豆腐块。

### 变更

- **发送方式**：图片与说明文字改为合成一条消息链发送——QQ 上一个气泡发完，TG 上按「图 + 一行说明」顺序发。
- **输出像素**：`scale` 语义改为输出像素倍率，默认 2 倍（原来 1 倍），手机上不再被拉糊。
- 插件内渲染改为先写临时文件再原子替换，避免并发或崩溃留下半张图。
- `metadata.yaml` 补充 `repo`、`social_link`、`tags` 与多行 `desc`，方便上架插件市场。
- **授权方式**：采用 **AGPL-3.0-or-later + 商业双许可**。社区使用按 AGPL 免费（需开源修改、保留声明、标注上游，见 `ADDITIONAL-TERMS.md`）；闭源集成 / 免开源 SaaS 等场景需购买商业许可（见 `COMMERCIAL-LICENSE.md`）。
- 工具参数 `spec` 增加默认值：模型的调用漏参时返回友好提示，而不是抛 `TypeError`。
- 字体探测不再为了读取 AstrBot 数据目录而触发其初始化，插件目录里跑测试不会凭空生成 `data/`。

### 修复

- 回边（环、失败重试、回调）改为走图外侧的独立轨道，不再从同层其它节点背后穿过。
- 连线标签在跨层长边上会被中间节点挡住的问题（标签改为贴近起点放置）。

### 内部

- 拆分 `layout.py` / `render.py`，布局引擎可脱离 Pillow 单独测试。
- 测试从 13 项增加到 42 项，覆盖清洗、方向自适应、像素倍率、尺寸上限、发送链路与配置一致性。
- 新增 `scripts/preview.py`，一条命令生成 6 张预览图。

## [0.1.0] - 2026-11-14

首个版本。

### 新增

- `render_diagram` LLM 工具：模型给出节点和连线的 JSON，插件渲染成图片并发送。
- 分层布局：Kahn 拓扑排序求最长路径分层，层内两轮重心排序降低交叉，等宽节点与正交走线。
- Pillow 本地渲染：自动探测中文（微软雅黑 / 苹方 / Noto CJK），2 倍超采样，深色文字 + 浅色卡片配色。
- 结构校验与裁剪：节点 ≤ 16、连线 ≤ 24，超出在图下方注明省略数量。
- 缓存与限流：按 `sha256(spec)` 缓存 PNG（7 天 / 200 张），每会话每分钟渲染上限。
- 调试指令 `/diagram` 与中文别名 `/图匠`。
- 失败降级：JSON 不合法、无节点、渲染失败都回一句文字提示，不崩溃。
- 配置项：`max_nodes`、`max_edges`、`per_minute`、`max_parallel`、`scale`、`font_path`。
