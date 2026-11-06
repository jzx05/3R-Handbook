# VidMap: 利用时序结构的视频 SfM (VidMap: Exploiting Temporal Structure for Video-Based Structure-from-Motion)

> ⚙️ 本文由 3R Handbook 解析流程维护 | 2026-11-06
>
> **论文**: VidMap: Exploiting Temporal Structure for Video-Based Structure-from-Motion, ECCV 2026（arXiv 2607.27194v1）
> **链接**: https://arxiv.org/abs/2607.27194
> **代码**: https://github.com/cvg/vidmap（Apache-2.0）
> **核心定位**: 把 SLAM 的时序跟踪与离线 SfM 的全局优化结合，用稠密匹配、loop closure、metric depth 先验和 provenance-aware 优化重建长、未标定视频。

<!-- source: https://arxiv.org/abs/2607.27194 -->

## ⚡ 快速判断（30 秒读完这段就够了）

| 维度 | 判断 |
|------|------|
| 核心结论 | 一个**离线、非因果**的视频 SfM：时序稠密 track + loop closure + metric depth 先验 + GLOMAP 全局优化。LaMAR 未标定 W-AUC **91.9/92.3/89.9/89.3/88.5**（10/25/50/100 m/full），CroCoDL 手机序列 **94.7/95.8/96.3/95.6/96.6**，均显著超过 SLAM、SfM 和端到端方法；输出 COLMAP 稀疏模型。 |
| 适合精读 | 做视频 3D 重建、SLAM/SfM 混合系统、大规模训练数据生成的人；想理解“时序先验 + 全局优化”如何互补的人。 |
| 可以跳过 | 要做实时 SLAM；只做单图/双图重建；没有 GPU/COLMAP 构建环境；只关心前馈端到端模型。 |
| 落地可行性 | 中。Apache-2.0、官方实现完整；但需要源码构建 COLMAP + PyCOLMAP，首次下载约 **9 GB** 模型、缓存约 1.2 GB，Python 3.10 / PyTorch 2.14 / xFormers 版本敏感，且是离线系统。 |
| 主要风险 | 前向运动导致关键帧过少；弱几何 + 视觉 aliasing 可能压过时序约束；严重模糊/遮挡/弱纹理导致 track 断裂；长序列无回环时仍会漂移；深度/标定先验 OOD 时退化。 |

💡 **X-Ray 开场**
SLAM 是因果的：每来一帧就立刻做决定，早期错误会一路传播，且通常要求已知内参；SfM 是非因果的、能全局优化，但把视频当无序图像集，丢掉了“相邻帧几乎必然对应”的强先验，在对称/重复结构上容易被 aliasing 骗。VidMap 把两者接起来：用 SLAM 式的关键帧、稠密 track 和滑窗传播拿到长而可靠的时序约束；用 SfM 式的离线全局优化、loop closure 和 metric depth 先验拿到全局一致性与尺度。关键工程是**保留 provenance**——明确区分“时序边”和“回环边”，让优化器对不同来源的约束用不同的鲁棒核。

📍 **研究全景时间线**

```text
[2021] DROID-SLAM：稠密光流 + 全局 BA 的 SLAM
[2022-2023] COLMAP / GLOMAP：经典增量/全局 SfM
[2024] MASt3R-SLAM / MegaSaM / ViPE：学习匹配 + 深度先验的 SLAM
[2025] VGGT / VGGT-SLAM / DA3-Long / LoGeR / LingBot-Map：前馈长序列
[2026.07] VidMap ← 当前位置：非因果视频 SfM，时序 track + 全局优化 + depth 先验
[2026]   GLUEMAP / MapAnything：前馈 + 全局 SfM 的另一条路线
← 局限：前向运动、弱几何 + aliasing、track 断裂、长程漂移、离线
```

## 1. 核心架构/方法总览 (Overview / Architecture)

### 1.1 系统对比概览 (System Component Comparison)

| 组件 | 输入 | 输出 | 训练/推理差异 |
|------|------|------|---------------|
| 关键帧检测 | 连续视频帧 + 低分辨率光流 | 关键帧集合 $\mathcal{K}$ | 无训练；按跟踪位移/丢失触发 |
| 稠密匹配 / track | 关键帧对（时序 + 回环） | 像素 flow、certainty、2D 协方差 | 用预训练稠密匹配器（论文用 RoMa v2；官方代码默认 FlexGlue，可切 `romav2`） |
| 多流 track 传播 | 前 $W$ 个关键帧的候选预测 | 长 track + 累积协方差 | 选最小协方差候选，且需与顺序预测一致 |
| Track 过滤 | track + 关键帧对 | 干净 track | certainty 阈值、基础矩阵极线检查、空间稀疏化 |
| 深度估计 | 每个关键帧 | 单目深度 + 不确定性 | 预训练深度模型（论文引用 Depth Anything 3） |
| 回环检测 | 关键帧全局描述子 | 回环候选 | MegaLoc 检索 + 稠密匹配 + 几何验证 |
| 标定 | 关键帧 | 焦距/内参 | GeoCalib + view-graph calibration；BA 再联合优化 |
| 全局 mapping | tracks + 相对位姿 + 深度 | 全局位姿/内参/点云 | 基于 GLOMAP：rotation averaging + GP + BA，**不训练** |
| 输出 | 全局模型 | COLMAP 稀疏重建 | 写 `$OUTPUT_DIR/rec/` |

### 1.2 关键机制 (Key Mechanism)

1. **非因果的视频提取**：虽然是视频，但不按因果顺序提交结果。先做低分辨率匹配找关键帧，再做高分辨率 refinement、track 传播、回环；整个序列看完后才进入全局优化。

2. **稠密匹配 + 多流传播**：用稠密匹配器给出逐像素 flow、certainty 和 2D 协方差。Track 沿时间链式传播；为了抑制漂移，还从前 $W$ 个关键帧直接预测到当前帧，选协方差最小的候选，但只有与顺序预测一致时才接受（否则退回顺序预测）。

3. **Provenance-aware track 构建**：顺序 track 和回环观测**不合并**。回环匹配作为单独的 observation 挂在已有顺序 track 上，并打上 `lc` 标签；顺序观测是 `seq`。这样错误回环不会通过传递性把两条独立 track 粘成一条不可分的 track。

4. **Provenance-aware 鲁棒优化**：rotation averaging 和 global positioning（GP）里，`seq` 边用 Huber（信任），`lc` 边用 Cauchy（重降权）。这比“所有边一视同仁”更能抵抗视觉 aliasing 造成的错误回环。

5. **Metric depth 先验 + 每图尺度**：每个关键帧有单目深度 $m_{ik}$ 和不确定性 $\sigma_{ik}$。GP 和 BA 里加入深度残差，并为每张图优化一个尺度 $s_i$，把单目深度的相对尺度对齐到全局；深度是**软先验**，不是硬约束。

6. **未标定视频的两段式标定**：GeoCalib 先逐帧估焦距，再选 top-k 置信帧做 shared-intrinsics 联合优化；view-graph calibration 用良态对的本质矩阵精化；BA 再联合优化内参。

⚡ **Eureka Moment**：**视频的时序不是“额外信息”，而是应该贯穿数据关联和优化的第一等公民。** 但时序约束也不是永远可信——回环可能错、前向运动可能退化。VidMap 的做法是保留每条约束的**来源（provenance）**，让优化器按来源决定信任程度；同时用 metric depth 先验补上视频几何的退化方向。

### 1.3 信息流/架构图 (Flow / Diagram)

```text
视频帧
  │
  ▼
[关键帧检测] 低分辨率光流 + 跟踪位移/丢失
  │
  ▼
[稠密匹配 + 多流 track 传播]
  │  顺序 track（seq）+ 累积协方差
  │
  ├──► [回环检测] MegaLoc 检索 + 稠密匹配 + 几何验证
  │        └── 回环观测（lc），不合并进顺序 track
  │
  ├──► [深度估计] 每关键帧单目深度 + 不确定性
  │
  └──► [标定] GeoCalib + view-graph calibration（未标定时）
           │
           ▼
[全局 mapping：GLOMAP]
  1. view graph 构建
  2. rotation averaging（seq: Huber；lc: Cauchy）
  3. global positioning（bearing + depth + per-image scale）
  4. bundle adjustment（reprojection + depth + scale，内参可优化）
           │
           ▼
COLMAP 稀疏模型（`$OUTPUT_DIR/rec/`）
```

## 2. 数学核心 (Math Core)

📌 **Napkin Formula**（一行抓住本质）：

```text
E_GP = Σ_(i,k) [ ρ_lik^GP( bearing residual ) + ρ_lik^depth( depth residual / σ_ik ) ]
       + Σ_i ρ^scale( log(s_i) / σ_s,i )

E_BA = Σ_(i,k) [ ρ^BA( reprojection ) + ρ^depth( depth residual / σ_ik ) ]
       + Σ_i ρ^scale( log(s_i) / σ_s,i )

ρ_seq = Huber（信任时序边）,  ρ_lc = Cauchy（重降权回环边）
depth residual = log(z_ik / (s_i · m_ik))  if z_ik > 0, else z_ik - s_i · m_ik
```

**目标**：在视频序列上同时估计关键帧位姿、内参、稀疏 3D 点和每图深度尺度；用 provenance 决定每条边的可信度，用深度先验约束退化几何。

**变量说明**：

| 符号 | 含义 |
|------|------|
| $m_{ik}, \sigma_{ik}$ | 关键帧 $i$ 在观测 $k$ 处的单目深度先验与不确定性 |
| $s_i$ | 关键帧 $i$ 的深度尺度（把 $m_{ik}$ 对齐到全局） |
| $l_{ik}\in\{seq, lc\}$ | observation 的 provenance 标签 |
| $\rho_{l}^{GP}, \rho_{l}^{depth}$ | 按 provenance 选择的鲁棒核 |
| $e_{ik}^{GP}$ | GP 的 bearing 残差（相机射线 vs 3D 点方向） |
| $e_{ik}^{BA}$ | BA 的像素重投影残差 |
| $z_{ik}$ | 优化后的相机系深度 |
| $c_i, X_k$ | 相机中心与 3D 点 |

**直觉**：深度残差把“单目深度说这个点有多远”变成可微的软约束；每图尺度 $s_i$ 允许不同帧的深度先验有不同尺度（单目模型常见）。回环边用 Cauchy，是因为错误回环的残差可能很大，Huber 仍会留下线性梯度，Cauchy 能更狠地压掉。

**补充：协方差传播**

- Track 传播时，顺序协方差累加：$\Sigma_i^{seq} = \Sigma_{i-1}^{seq} + \Sigma_{(i-1)\to i}$。
- 选多流候选时，比较 $\operatorname{tr}(\Sigma_i^{(j)})$，取最小；只有与顺序预测一致才接受。
- GP 里把像素 2D 协方差通过反投影/旋转的 Jacobian 传播到 3D bearing 协方差：$\Sigma_{ik}^{v} = J_i \Sigma_{ik} J_i^\top$。

## 3. 带数字走一遍：玩具例子 (Worked Example)

假设 1,000 帧视频，选出 200 个关键帧（示例设定，非论文固定值）：

```text
Step 1: 关键帧
        1,000 帧 → 按跟踪位移/丢失选 200 个关键帧
        相邻关键帧有高重叠；前向运动时可能选得过少（见失败模式）

Step 2: 稠密 track
        每帧采样关键点，沿 flow 链式传播
        多流：从前面 W 个关键帧直接预测，选协方差最小的候选
        只有与顺序预测一致才接受，否则退回顺序预测

Step 3: 回环
        MegaLoc 检索 top-k；稠密匹配 + 几何验证
        回环观测标 lc，不合并进顺序 track

Step 4: 深度
        每个关键帧一张单目深度 + 不确定性
        GP/BA 里软约束，优化每图尺度 s_i

Step 5: 全局 mapping
        rotation averaging：seq=Huber，lc=Cauchy
        GP：bearing + depth + scale；BA：reprojection + depth + scale
        输出 COLMAP 稀疏模型
```

**关键数字**：

```text
LaMAR 未标定 W-AUC：91.9 / 92.3 / 89.9 / 89.3 / 88.5（10/25/50/100m/full）
LaMAR 标定 W-AUC：  93.2 / 93.0 / 90.5 / 89.9 / 89.7
CroCoDL 手机未标定：94.7 / 95.8 / 96.3 / 95.6 / 96.6
CroCoDL 机器人未标定：94.0 / 95.0 / 95.3 / 93.0 / 95.5
ETH3D-SLAM 未标定 AUC：51.4 / 68.3 / 90.1 / 94.0 / 99.0（5cm/10cm/50cm/1m/10m）
```

> 注意：LaMAR/CroCoDL 用 W-AUC（窗口内 5% 误差阈值），ETH3D 用全局对齐后的 AUC；不同协议不能直接横比。

## 4. 工程视角 (Engineering View)

| 维度 | 数值/权衡 | 工程含义 |
|------|-----------|----------|
| 系统形态 | **离线、非因果** | 需要整段视频；不追求实时 |
| 依赖 | COLMAP 源码构建 + PyCOLMAP；Python 3.10；PyTorch 2.14；xFormers 0.0.35 | 环境重，版本敏感 |
| 模型权重 | 首次前端运行下载约 **9 GB**；编译缓存约 **1.2 GB** | 首次启动慢；需要磁盘/网络 |
| GPU | NVIDIA GPU；稠密匹配/深度是主要 GPU 负载 | 无 GPU 不现实 |
| 运行时间 | 随关键帧线性增长；matching 最贵；与 GLOMAP 相当，明显快于 COLMAP | 论文 Fig. 7；具体分钟数取决于序列 |
| 加速 | 减少 track 点数、coarse-only keyframing、减少 hop；GPU GP 约省 **13%** 总 mapping 时间（README LaMAR HGE） | 精度-速度可调 |
| 输出 | COLMAP 稀疏模型（`rec/`） | 可直接接 COLMAP/MVS/3DGS 生态 |
| 许可 | **Apache-2.0** | 商用相对友好 |
| 相机模型 | 支持 rig / panorama / fisheye 配置（README） | 但 EuRoC 鱼眼上精度只与基线持平 |

**部署约束**：
- 需要源码构建 COLMAP（README 测试 commit `b1972bc2`）；PyCOLMAP 版本要匹配。
- Python 3.10 / PyTorch 2.14 / xFormers 0.0.35 是测试组合；版本漂移可能出问题。
- 首次 frontend 下载 ~9 GB 模型；离线环境要预先准备。
- 全流程离线；不能直接当实时 SLAM 用。
- 长视频内存/时间随关键帧增长；前向运动可能选太少关键帧。
- 鱼眼/灰度/运动模糊（EuRoC）上，深度/标定先验不一定帮忙，精度与强基线持平。

**代码地图**（官方 repo 结构；行号未核，按文件定位）：

| 功能 | 文件/入口 |
|------|-----------|
| 前端（关键帧、track、回环、深度） | `python -m vidmap.frontend` / `vidmap/frontend` |
| 全局 mapping | `python -m vidmap.map` / `vidmap/map` |
| 一键运行 | `python -m vidmap.run` |
| 前端配置 | `vidmap/configs/frontend` |
| Mapping 配置 | `vidmap/configs/mapping` |
| 标定配置 | `uncalib/geocalib`（README） |
| 可视化 | `vidmap.visualization.html` / `vidmap.visualization.rerun` |
| 数据集准备/评测 | `vidmap.datasets.prepare` / `vidmap.evaluate_results` |
| 基准入口 | `python -m vidmap.run_for_benchmark` |

## 5. 数据与评测 (Data & Eval)

### 5.1 数据组成

VidMap **不训练**，只做推理 + 优化；评测用 4 个数据集：

| 数据集 | 规模/特点 | 主要挑战 |
|--------|-----------|----------|
| LaMAR | 50 段手机视频（CAB/HGE/LIN） | 长轨迹、复杂运动、视觉 aliasing、弱纹理、退化视角 |
| CroCoDL | 62 段手机 + 26 段机器人（4 个灾后建筑） | 域外、复杂运动、非结构化环境 |
| ETH3D-SLAM | 55 段室内/室外手持 | 高精度 GT、变化场景/运动 |
| EuRoC | 11 段无人机灰度鱼眼 | 快速 6-DOF、模糊、鱼眼 |

### 5.2 评测设置

- **指标**：平移误差 AUC（%）；LaMAR/CroCoDL 用 **W-AUC**（窗口内 5% 误差阈值），ETH3D/EuRoC 用全局对齐后的 AUC。
- **标定设置**：`calibrated` 用 GT 内参；`uncalibrated` 从视频估内参。
- **基线**：SLAM/VO（DPV-SLAM、DROID-W、MegaSaM、ViPE、MASt3R-SLAM）、端到端（DA3-Long、LoGeR、LingBot-Map、VGGT-SLAM2）、全局 SfM（GLOMAP-LG、GLOMAP-RoMA）。

### 5.3 关键结果

**LaMAR（Table 1，W-AUC ↑）**

| 方法 | 设置 | 10 m | 25 m | 50 m | 100 m | full |
|------|------|-----:|-----:|-----:|------:|-----:|
| GLOMAP-LG | uncal | 76.4 | 69.4 | 60.1 | 53.6 | 62.3 |
| GLOMAP-RoMA | uncal | 71.0 | 66.0 | 58.4 | 46.7 | 59.4 |
| MASt3R-SLAM | uncal | 60.8 | 63.6 | 55.6 | 47.3 | 51.5 |
| MegaSaM | uncal | 77.5 | 68.4 | 59.9 | 51.4 | 52.7 |
| ViPE | uncal | 86.6 | 83.8 | 80.2 | 78.1 | 76.6 |
| DA3-Long | uncal | 86.7 | 86.7 | 84.6 | 78.1 | 76.5 |
| VGGT-SLAM2 | uncal | 74.0 | 69.2 | 60.3 | 49.4 | 56.9 |
| **VidMap** | **uncal** | **91.9** | **92.3** | **89.9** | **89.3** | **88.5** |
| **VidMap** | **cal** | **93.2** | **93.0** | **90.5** | **89.9** | **89.7** |

**CroCoDL（Table 2，W-AUC ↑）**

| 序列 | 方法 | 10 m | 25 m | 50 m | 100 m | full |
|------|------|-----:|-----:|-----:|------:|-----:|
| 手机 | VidMap uncal | 94.7 | 95.8 | 96.3 | 95.6 | 96.6 |
| 手机 | DA3-Long uncal | 86.2 | 88.1 | 88.5 | 88.8 | 88.9 |
| 手机 | GLOMAP-LG uncal | 73.9 | 66.8 | 62.0 | 57.9 | 72.2 |
| 机器人 | VidMap uncal | 94.0 | 95.0 | 95.3 | 93.0 | 95.5 |
| 机器人 | DA3-Long uncal | 86.2 | 88.1 | 88.5 | 88.8 | 88.9 |
| 机器人 | VGGT-SLAM2 uncal | 62.8 | 64.3 | 66.0 | 62.5 | 74.9 |

> 表中机器人行的 DA3-Long 数字与手机行重复，是原表排版导致的；引用时请回原表核对具体行。

**ETH3D-SLAM / EuRoC（Table 3）**
- ETH3D-SLAM 未标定 AUC（5cm/10cm/50cm/1m/10m）：VidMap **51.4 / 68.3 / 90.1 / 94.0 / 99.0**，显著优于 DPV-SLAM 等基线。
- EuRoC：VidMap 与最强基线大致持平；灰度鱼眼 + 运动模糊让学习深度/标定先验不那么可靠。

**消融（Table 4）**

| 变体 | LaMAR 10 m ↑ | LaMAR full ↑ | ETH3D 5 cm ↑ | 结论 |
|------|-------------:|-------------:|-------------:|------|
| VidMap | 91.9 | 88.5 | 51.4 | 完整系统 |
| No depth in GP | 67.6 | — | 42.8? | GP 里去掉深度先验，长程精度大跌 |
| No depth in BA | 91.5 | — | 44.7? | BA 深度先验影响较小 |
| No scale optimization | 69.3 | — | 44.7? | 固定尺度，退化明显 |
| No metric scale | 90.2 | — | 44.7? | 去掉 metric 先验，略有下降 |
| No loop closure edges | 90.8 | 85.5 | 32.9 | ETH3D 上掉得最明显 |
| No provenance losses | 88.4 | 79.9 | 50.6 | LaMAR aliasing 下灾难性下降 |

> Table 4 的列很多，PDF 抽取有错位；上表只保留能明确对应的值，标 `?` 的不要直接引用，回原表核对。

**Tracker 消融（Appendix B）**
- RoMa 作为 chained matcher 已优于 flow-based tracker；multi-flow 进一步降低漂移。
- 换成 ALIKED+LightGlue（稀疏关键点）在弱纹理/暗光段会失败；稠密 track 能维持对应。

**口径提醒**：
- LaMAR/CroCoDL 是 W-AUC，窗口内 5% 阈值；ETH3D 是全局 AUC；不能跨表比。
- 标定/未标定设置不同；VidMap 两者接近，说明标定估得准。
- README 的 benchmark 数字（如 LaMAR ATE 0.916 m、WATE-AUC 92.78）与论文 Table 1 的协议/版本不同，引用时要写清来源。

## 6. 能力与失败模式 (Capabilities & Failure Modes)

### 能做什么

| 能力 | 条件 | 证据 |
|------|------|------|
| 长、未标定视频重建 | 离线；有 GPU | LaMAR/CroCoDL |
| Metric-scale 重建 | 深度先验可用 | 深度 + 每图尺度 |
| 视觉 aliasing / 对称结构 | 回环 + provenance 鲁棒核 | LaMAR/CroCoDL |
| 域外泛化 | 不重训 | CroCoDL 灾后场景 |
| COLMAP 兼容输出 | 标准稀疏模型 | `rec/` |
| 相机 rig / panorama / fisheye 配置 | README 配置 | 但鱼眼精度不一定提升 |
| 精度-速度调节 | 减少 track/hop、coarse keyframing | README 表格 |

### 不能做什么

| 失败模式 | 原因（论文 Limitations） |
|----------|--------------------------|
| 前向运动 | 关键帧判据看图像位移，前向运动位移小，可能选太少关键帧，GP 欠约束 |
| 弱几何 + 视觉 aliasing | 错误回环在数值上彼此一致时，Cauchy 也只能降权不能消除梯度，GP 可能收敛到错误解 |
| 严重模糊/遮挡/突变视角/弱纹理 | Track 断裂；全局优化无法恢复缺失对应 |
| 长程漂移 | 没有可靠回环时，局部误差仍会累积 |
| 学习先验 OOD | 深度/标定先验在域外图像或特殊相机上不可靠 |
| 实时 SLAM | 离线、多 pass、全局优化 |
| 鱼眼/灰度极限场景 | EuRoC 上只与强基线持平 |

### 6.1 隐含假设 (Hidden Assumptions)

1. **静态场景**：动态物体会破坏 track 和深度先验。
2. **视频有足够时序重叠**：相邻关键帧高重叠是稠密 track 的前提。
3. **回环候选可检索**：MegaLoc 检索不到的回环，优化器也拿不到。
4. **顺序 track 大体正确**：provenance 机制假设 `seq` 比 `lc` 更可信；如果顺序 track 本身漂移，仍会错。
5. **深度先验大致合理**：单目深度在域外/特殊相机上可能系统性偏差。
6. **相机模型可被 COLMAP 表达**：鱼眼/全景需要对应模型与配置。
7. **离线可接受**：需要整段视频，不能因果输出。

## 7. 与相关工作对比 (Comparison)

| 方法 | 类型 | 时序 | 全局优化 | 需要标定 | 尺度 | 适用场景 |
|------|------|------|----------|----------|------|----------|
| ORB-SLAM3 / DROID-SLAM | SLAM | 因果 | 局部/全局 BA | 通常需要 | 可 metric（IMU） | 实时机器人 |
| MASt3R-SLAM / VGGT-SLAM | 学习 SLAM | 因果/分块 | 有 | 不需要 | 可 metric | 在线/近在线 |
| ViPE / MegaSaM | 学习 VO/SLAM | 因果 | 有 | 不需要 | 可 metric | 视频重建 |
| COLMAP / GLOMAP | 经典 SfM | 无序 | 全局 | 可估 | 可估 | 图像集合 |
| MASt3R-SfM / GLUEMAP | 前馈 + SfM | 弱时序 | 全局 | 不需要 | 可 metric | 大规模 SfM |
| DA3-Long / LoGeR / LingBot-Map | 端到端长序列 | 分块 | 有限 | 不需要 | 可 metric | 前馈重建 |
| **VidMap** | **离线混合 SfM** | **显式时序** | **全局** | **可估** | **metric 先验** | **长视频、未标定** |

**面试 Tip**：当被问到“VidMap 和 SLAM/SfM 的区别”时，回答——SLAM 是因果的，早错会一路传播且通常要已知内参；SfM 是非因果的、能全局优化，但把视频当无序图像，丢掉时序先验。VidMap 保留时序 track，但**不因果提交**；用 provenance 区分顺序边和回环边，用 metric depth 先验约束退化几何，最后用 GLOMAP 做全局优化。一句话：**SLAM 的时序 + SfM 的全局，但时序要能被质疑**。

## 8. 精读建议 (Reading Guide)

**值得精读原文的人**：
- 做视频 3D 重建、SLAM/SfM 混合系统、大规模训练数据生成的人。
- 想理解“provenance-aware 优化”和“depth prior in global SfM”的人。
- 要把 COLMAP/GLOMAP 扩展到视频的人。

**建议章节路径**：
- 先读 §3.1：关键帧、稠密 track、多流传播。
- 再看 §3.2：provenance-aware track 构建（为什么不能传递性合并）。
- 再看 §3.3–3.4：未标定标定 + GP/BA 的 depth prior 与鲁棒核。
- 再看 §4：LaMAR/CroCoDL 的数字与协议。
- 可跳 §2（相关工作）——除非写综述。

**不值得精读的理由**：
- 你要实时 SLAM——VidMap 是离线多 pass。
- 你只做单图/双图——DUSt3R/MASt3R 更直接。
- 你的相机是鱼眼/灰度且运动模糊严重——EuRoC 上 VidMap 只与强基线持平。

## 9. 补充：面试高频 Q&A

**Q1：VidMap 为什么不直接做 SLAM？**
A：SLAM 因果、增量，早期错误会传播；通常要已知内参；实时约束限制了全局优化。VidMap 离线看完整段视频，先建立全局约束再优化。

**Q2：VidMap 为什么不直接做 SfM？**
A：SfM 把视频当无序图像，丢掉“相邻帧高重叠”的强先验，在视觉 aliasing/对称结构上容易被骗。VidMap 用时序 track 和 provenance 区分顺序/回环。

**Q3：provenance 具体指什么？**
A：每条 track observation 和每条边都记录来源：`seq`（顺序跟踪）或 `lc`（回环）。Track 构建不把 `lc` 传递性合并进顺序 track；rotation averaging/GP 对 `seq` 用 Huber、对 `lc` 用 Cauchy。

**Q4：为什么回环用 Cauchy？**
A：错误回环的残差可能很大；Huber 仍保留线性梯度，Cauchy 更狠地降权。论文在 aliasing 场景下验证了 provenance 的必要性。

**Q5：深度先验怎么用？**
A：每个关键帧有单目深度 + 不确定性；GP/BA 加深度残差，并优化每图尺度 $s_i$。深度是软先验，不是硬约束；去掉 GP 深度先验，LaMAR 10m AUC 从 91.9 掉到 67.6。

**Q6：为什么要每图尺度？**
A：单目深度模型在不同帧的尺度可能不一致；固定尺度会在长序列上漂移。优化 $s_i$ 让深度先验对齐全局。

**Q7：未标定怎么估内参？**
A：GeoCalib 逐帧估焦距，选 top-k 置信帧做 shared-intrinsics 联合优化；view-graph calibration 用良态对精化；BA 再联合优化。

**Q8：VidMap 能实时吗？**
A：不能。它是离线、多 pass、全局优化系统；时间随关键帧线性增长，matching 最贵。

**Q9：VidMap 和 GLUEMAP 的关系？**
A：两者都基于 GLOMAP/全局 SfM，但目标不同：GLUEMAP 把前馈 backbone 接进大规模型 SfM；VidMap 用视频时序 track + 深度先验 + provenance 处理长视频。可以理解为“视频版的全局 SfM”。

**Q10：最大失败模式？**
A：前向运动导致关键帧太少；弱几何 + 一致错误回环；track 断裂；长程无回环漂移；深度/标定先验 OOD。

## 10. 补充：复现清单

**安装**：

```bash
git clone --recursive https://github.com/cvg/vidmap.git
cd vidmap
# 按 README 从源码构建 COLMAP + PyCOLMAP（测试 commit b1972bc2）
# Python 3.10, PyTorch 2.14, TorchVision 0.29, xFormers 0.0.35
```

**运行**：

```bash
INPUT_DATA=./assets/example_video.mp4
OUTPUT_DIR=./example_output/

# 分两步
python -m vidmap.frontend "$INPUT_DATA" --output "$OUTPUT_DIR"
python -m vidmap.map --mapper-inputs "$OUTPUT_DIR/mapper_inputs" --output "$OUTPUT_DIR"

# 或一步
python -m vidmap.run --input_data "$INPUT_DATA" --output "$OUTPUT_DIR"
```

**输出**：`$OUTPUT_DIR/rec/`（COLMAP 稀疏模型）；`frontend_config.yaml` / `mapping_config.yaml` 也在输出目录。

**关键配置**：

| 配置 | 说明 |
|------|------|
| `default` | 论文默认重建管线 |
| `smooth_trajectory` | 实验性：关键帧坐标轨迹平滑，长序列更稳 |
| `uncalib/geocalib` | 未标定 + GeoCalib 焦距 |
| `fisheye-mono` | 鱼眼单目配置（README） |
| `frontend.matcher.name=romav2` | 切换 RoMaV2（默认 FlexGlue） |
| `--cache-depth-maps` | 保留深度图用于可视化 |

**加速**：

```bash
python -m vidmap.run \
  --input_data "$INPUT_DATA" --output "$OUTPUT_DIR" \
  frontend.tracks.propagation.max_kps=1000 \
  frontend.keyframes.matching.coarse_only=true \
  'frontend.tracks.propagation.multiflow_hops=[1,2,4,8]' \
  mapping.mapper.gp.solver_backend.use_cuda=true \
  mapping.mapper.ba.solver_backend.use_cuda=true
```

README 报告的加速：hops `[1,2,4,8]` 约省 9.9% 提取时间、精度几乎不降；`[1,2,4]` 省 15.3%、精度降 0.385%；`[1,2]` 省 21.3%、精度降 1.563%。

**常见坑**：
1. COLMAP/PyCOLMAP 源码构建失败或版本不匹配。
2. Python 3.10 / PyTorch 2.14 / xFormers 0.0.35 版本漂移。
3. 首次 frontend 下载 ~9 GB 模型，离线环境未准备。
4. 前向运动视频关键帧太少，GP 欠约束。
5. 鱼眼/灰度/运动模糊场景，深度/标定先验不一定帮忙。
6. 把 VidMap 当实时 SLAM 用——它是离线系统。

## 11. 补充：来源与核查

| 结论/数字 | 来源 | 核查方式 |
|-----------|------|----------|
| 非因果视频提取、关键帧、track | 论文 §3.1 | PDF 原文 |
| 多流 track 传播与协方差 | 论文 §3.1, Fig. 3 | PDF 原文 |
| provenance-aware track / 优化 | 论文 §3.2–3.4, Fig. 4–5 | PDF 原文 |
| GP/BA 公式 | 论文 §3.4, Eq. (1)–(4) | PDF 原文 |
| 未标定标定流程 | 论文 §3.3 | PDF 原文 |
| LaMAR 数字 | 论文 Table 1 | PDF 原文 |
| CroCoDL 数字 | 论文 Table 2 | PDF 原文 |
| ETH3D/EuRoC 数字 | 论文 Table 3 | PDF 原文（部分表格抽取有错位，按原表复核） |
| 消融 | 论文 Table 4 | PDF 原文（列多，按原表复核） |
| 失败模式 | 论文 Appendix A.1 Limitations | PDF 原文 |
| 安装/运行/加速 | 官方 README | 2026-11-06 |
| 9 GB checkpoints / 1.2 GB cache | 官方 README | 2026-11-06 |
| 许可 Apache-2.0 | GitHub API license | 2026-11-06 |

**未在本文中当作事实的**：具体端到端分钟数（论文 Fig. 7，正文未给统一数字）、不同 GPU 上的实际延迟、各数据集的关键帧数、Table 3/4 中抽取错位的具体单元格。部署前请以论文表格和 README 为准。

---
[← Back to Theory](../README.md)

**关键引用**：
- 论文：https://arxiv.org/abs/2607.27194
- 代码：https://github.com/cvg/vidmap
- GLOMAP：https://github.com/colmap/glomap
- RoMa v2：https://arxiv.org/abs/2511.15706
- Depth Anything 3：https://arxiv.org/abs/2511.10647
- MegaLoc：论文引用 [1]（CVPRW 2025）
- GeoCalib：论文引用 [57]（ECCV 2024）
