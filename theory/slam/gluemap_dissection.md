# GLUEMAP: 全局 SfM 遇上前馈重建 (Global Structure-from-Motion Meets Feedforward Reconstruction)

> ⚙️ 本文由 3R Handbook 解析流程维护 | 2026-11-06
>
> **论文**: Global Structure-from-Motion Meets Feedforward Reconstruction, CVPR 2026（arXiv 2605.26103v2）
> **链接**: https://arxiv.org/abs/2605.26103
> **代码**: https://github.com/colmap/gluemap（new BSD）
> **核心定位**: 把前馈重建接进经典全局 SfM：星图局部推理 + 运动平均 + 增强 BA，兼顾前馈的局部鲁棒性与经典 SfM 的大规模精度。

<!-- source: https://arxiv.org/abs/2605.26103 -->

## ⚡ 快速判断（30 秒读完这段就够了）

| 维度 | 判断 |
|------|------|
| 核心结论 | 不是训练新网络，而是把 π³ / Pi3X / VGGT / MapAnything 当成“局部重建器”，塞进全局 SfM 的四个阶段：检索建图 → 星图前馈推理 → 运动平均 → 增强 BA。ETH3D AUC@5 **83.6**（GT 标定 **89.0**），SMERF minimal 20° **82.0**，可扩展到**数万张**图像；纯前馈方法在 LaMAR 上直接 OOM。 |
| 适合精读 | 做大规模 SfM / 3D 重建系统、想把前馈模型产品化、需要 COLMAP 兼容输出的人；想理解“前馈到底补了经典 SfM 什么”的人。 |
| 可以跳过 | 只做两视图/少量图重建（DUSt3R/VGGT 更直接）；只做 SLAM 在线系统；不关心全局优化/BA 的人。 |
| 落地可行性 | 中高。代码 BSD、有官方实现、能输出 COLMAP 格式；但依赖 Ceres/Eigen/METIS/Boost/OpenMP，安装较重，需要 GPU 跑 backbone。 |
| 主要风险 | 依赖前馈局部重建质量；鱼眼不支持；纯旋转运动不行；需要组合多个前馈模型/权重；系统复杂、调参多。 |

💡 **X-Ray 开场**
纯前馈方法（DUSt3R/MASt3R/VGGT）在低纹理、低重叠、对称结构上很鲁棒，但一到大场景就受显存和全局一致性限制；经典 SfM（COLMAP/GLOMAP）能扩展到数万图、精度高，但在难场景容易失败。GLUEMAP 的洞见是：**不要让前馈做全局，让它只做局部**。用检索建一个稀疏图，对每个视图取一个星图（中心图 + 邻居），用前馈一次推理局部几何；再用经典的运动平均把局部拼成全局，最后用 SIFT + 前馈 + 虚拟 track 做增强 BA。两者各做自己擅长的事。

📍 **研究全景时间线**

```text
[2016-2023] COLMAP / GLOMAP：增量/全局 SfM，SIFT + BA
[2023.12]   DUSt3R：成对 pointmap + 全局对齐
[2024.06]   MASt3R：匹配头 + metric + 快速互惠匹配
[2024.09]   MASt3R-SfM：前馈匹配 + 稀疏全局对齐
[2025.03]   VGGT：多视图一次前向；Fast3R / VGGT-Long / VGGT-SLAM
[2026.05]   GLUEMAP ← 当前位置：前馈局部 + 全局 SfM + 增强 BA
← 局限：依赖前馈质量、鱼眼、纯旋转、系统复杂
```

## 1. 核心架构/方法总览 (Overview / Architecture)

### 1.1 系统对比概览 (System Component Comparison)

| 组件 | 输入 | 输出 | 训练/推理差异 |
|------|------|------|---------------|
| 检索建图 | 图像集合 | 稀疏 view graph（SALAD + Doppelgangers++） | 无训练；用现成模型 |
| 星图切分 | view graph | 每张图一个 star（中心 + ≤25 邻居） | 无训练 |
| 前馈局部推理 | 每个 star 的图像 | 局部位姿、深度、焦距、track | 用 π³/Pi3X/VGGT/MapAnything，冻结 |
| 全局运动平均 | 局部位姿/深度 | 全局内参、旋转、相机中心/尺度 | 优化，无训练 |
| 增强 BA | SIFT tracks + 前馈 tracks + 虚拟 tracks | 最终 COLMAP 稀疏重建 | 优化，无训练 |
| 输出 | 全局 poses/intrinsics/points | COLMAP 格式 | 推理管线 |

### 1.2 关键机制 (Key Mechanism)

1. **局部星图而非全局注意力**：对每张图 $l$，取它和邻居 $N_l$ 组成 star graph $S_l$，用前馈网络一次推理局部几何。这样避免全局 attention 的 $O(N^2)$ 显存，能 batch 并行，也天然限制对称结构的错误传播。

2. **动态阈值 + Doppelgangers++ 过滤**：SALAD 检索候选对后，用 Doppelgangers++ 打分 $\alpha_{ij}$；从 $\delta_0=0.8$ 开始，按 0.1 递减，直到图连通或 $\delta<0.2$；保留最大连通分量。这样在保证连通的同时过滤对称/重复结构的错误边。

3. **运动平均（intrinsics / rotation / similarity）**：内参取每台物理相机焦距的中位数；旋转用 Huber 鲁棒的 rotation averaging；相机中心用 similarity averaging，**每个 star 只用一个尺度 $s_l$**（因为 star 内局部重建尺度一致），比逐边尺度更稳。

4. **增强 BA（A-BA）**：标准 BA 需要足够多、多视图重叠的 track；低重叠/低纹理时 track 不足。GLUEMAP 在 BA 里加入三类 track：SIFT tracks（准）、前馈 tracks（鲁棒）、虚拟 tracks（从中心图像深度反投影到邻居，提供额外约束）。虚拟 track 约 100 条，10% 条件于全局位姿。

5. **前馈 backbone 可替换**：π³、Pi3X、VGGT、MapAnything 都能接；论文实验里 π³ 最好。GLUEMAP 不训练这些网络，只把它们当局部几何引擎。

⚡ **Eureka Moment**：**前馈的强项是“局部难场景”，经典 SfM 的强项是“全局一致 + 大规模”。** 把前馈限制在 star 里做局部推理，再用运动平均和 BA 做全局，就能同时拿到两者的好处；前馈不需要处理全局，显存和一致性问题自然消失。

### 1.3 信息流/架构图 (Flow / Diagram)

```text
图像集合 I
   │
   ▼
SALAD 检索 ──► 候选对 ──► Doppelgangers++ 打分 ──► 动态阈值 ──► view graph G
   │
   ▼
每个视图 l 的 star：{l} ∪ N_l（最多 25 帧）
   │
   ▼
前馈 backbone（π³ / Pi3X / VGGT / MapAnything）
   │  局部 poses / depth / focal / tracks
   ▼
全局运动平均：intrinsics averaging → rotation averaging → similarity averaging
   │  全局 poses + 每 star 一个尺度
   ▼
增强 BA：SIFT tracks + 前馈 tracks + 虚拟 tracks
   │
   ▼
COLMAP 稀疏重建（poses / intrinsics / points）
```

## 2. 数学核心 (Math Core)

📌 **Napkin Formula**（一行抓住本质）：

```text
(Pl, Fl, Dl, Tl) = FF(I_{N_l})                  # 每个 star 局部前馈

min_R  Σ_(i,j) ρ(o_ij^l · d(R_ij^l, R_j R_i^T))  # rotation averaging
min_c,s Σ_(l,(i,j)) o_ij^l · || d(R_ij^l^T t_ij - s_l (c_i - c_j)) ||  # similarity averaging

min_{poses,points} Σ reproj(SIFT + FF tracks) + Σ reproj(virtual tracks)
```

**目标**：用前馈局部重建初始化全局 SfM，再用运动平均与增强 BA 得到一致、可扩展的 COLMAP 重建。

**变量说明**：

| 符号 | 含义 |
|------|------|
| $N_l$ | 以 $l$ 为中心的 star 邻居集合 |
| $P_l, F_l, D_l, T_l$ | star 内局部位姿、焦距、深度、track |
| $o_{ij}^l$ | star 内边 $(i,j)$ 的 overlap ratio（前向-后向深度一致性） |
| $R_{ij}^l, t_{ij}^l$ | star 内相对旋转/平移 |
| $s_l$ | 每个 star 的全局尺度（只有一个） |
| $\alpha_{ij}$ | Doppelgangers++ 分数 |
| $\delta_t$ | 动态过滤阈值 |

**直觉**：前馈给出的局部几何在 star 内是尺度一致的，所以全局只需要为每个 star 估一个尺度；这比传统“逐边尺度”稳定得多。增强 BA 则把前馈的稠密先验变成“虚拟观测”，补上低重叠时缺失的 track。

**补充：动态阈值**

$$
E_{t+1} = E_t \cup \{(i,j) \mid \alpha_{ij} > \delta_t,\ \mathrm{CC}(i)\neq \mathrm{CC}(j)\}
$$

从 $\delta_0=0.8$ 开始，每次减 0.1；图连通就停，否则降到 0.2 保最大连通分量。

## 3. 带数字走一遍：玩具例子 (Worked Example)

假设一个 LaMAR 级场景，约 7,553 张图（HGE）：

```text
Step 1: 检索
        每张图检索 c 个候选（论文用固定 c；具体值见配置）
        候选对经 Doppelgangers++ 打分 → 动态阈值 → 连通 view graph

Step 2: 星图
        每张图一个 star，最多 25 帧（按 DG 分数保留）
        7,553 个 star，可 batch 并行

Step 3: 前馈局部推理（Table 9，GH200）
        两视图批：中位 1.20 s
        star 批：中位 0.31 s（90 分位 0.77 s）
        tracking 批：中位 1.27 s（90 分位 1.81 s）

Step 4: 全局运动平均
        rotation + similarity averaging
        小场景秒级；LaMAR 级变量更多，但仍远小于 BA

Step 5: 增强 BA
        SIFT tracks + 前馈 tracks + 虚拟 tracks
        LaMAR 上为分钟级（Table 10；具体值按原表复核）
        输出 COLMAP 稀疏模型
```

**关键数字**：

```text
ETH3D：AUC@1/3/5 = 53.0 / 76.9 / 83.6（无 GT 标定）
ETH3D*：74.0 / 85.9 / 89.0（有 GT 标定）
SMERF minimal：10.1 / 54.9 / 82.0（AUC@1/5/20）
CO3Dv2 10 图：54.8 / 79.3 / 90.3（AUC@3/10/30）
批处理：two-view 1.20 s，star 0.31 s，tracking 1.27 s（中位）
硬件：GH200 96 GB；可放进 RTX 4090 24 GB
扩展性：论文称可到数万张图像
```

> 注意：ETH3D 的 `*` 表示使用 GT 标定；SMERF/CO3Dv2 的阈值不同，不能跨表直接比。

## 4. 工程视角 (Engineering View)

| 维度 | 数值/权衡 | 工程含义 |
|------|-----------|----------|
| 是否训练 | **不训练** | 只做推理 + 优化；依赖预训练 backbone 权重 |
| Backbone | π³ / Pi3X / VGGT / MapAnything | π³ 实验最好；可替换 |
| 依赖 | Ceres / Eigen / METIS / Boost / OpenMP / pybind11 | 安装较重；需要 C++ 工具链 |
| 硬件 | GH200 96 GB；可跑 RTX 4090 24 GB | 星图 batch 控显存；大场景靠并行 |
| 运行时 | two-view 1.20 s，star 0.31 s，tracking 1.27 s/批 | 检索/星图/跟踪随图像数线性增长 |
| 全局优化 | 运动平均秒级；A-BA 分钟级（LaMAR） | 大场景瓶颈在 BA 和 track 数量 |
| 输出 | COLMAP 稀疏重建 | 可直接接 COLMAP/MVS/3DGS 生态 |
| 许可 | new BSD（GLUEMAP 本身；第三方依赖单独许可） | 商用相对友好，但要逐个检查依赖 |

**部署约束**：
- 需要 GPU 跑前馈 backbone；CPU 侧需要 Ceres/METIS 等。
- 安装复杂：C++/pybind11 扩展，Ceres/Eigen/METIS/Boost/OpenMP 必须可用。
- 需要下载多个 checkpoint（Pi3、SALAD、VGGSfM tracker、Doppelgangers++），见 `INSTALL.md`。
- 大场景要 `torchrun --nproc_per_node=N` 多卡；全局 mapping/refinement 只在 rank 0。
- 鱼眼不支持：前馈 backbone 只训练了针孔。
- 纯旋转运动不行：A-BA 的公式处理不了。

**代码地图**（官方 repo 结构；行号未核，按文件定位）：

| 功能 | 文件 |
|------|------|
| 主编排器 | `gluemap/controllers/gluemap_impl.py` |
| 检索 / view graph | `gluemap/` 下 retrieval 相关模块（SALAD） |
| 前馈局部推理 | star inference 模块（π³/Pi3X/VGGT/MapAnything） |
| 运动平均 | global mapping 模块 |
| 增强 BA | refinement 模块 |
| CLI | `gluemap-demo` |
| 基准 | `gluemap-benchmark` |
| 安装 | `INSTALL.md` |

## 5. 数据与评测 (Data & Eval)

### 5.1 数据组成

GLUEMAP **不训练**，因此没有训练集；评测覆盖 5 个真实数据集：

| 数据集 | 特点 | 主要挑战 |
|--------|------|----------|
| ETH3D | 高分辨率室内/室外，毫米级 GT | 精度、低重叠 |
| IMC2021 | 互联网照片集合 | 极端光照/视角变化 |
| CO3Dv2 | 物体中心多视图 | 少视图、物体级 |
| SMERF | 稀疏室内序列 | 极低/无重叠、低纹理、对称房间 |
| LaMAR | 大规模室内外 | 数千图、对称、低重叠、手机序列 |

### 5.2 评测设置

- 指标：AUC@X（X = 1/3/5/10/20/30），基于所有图像对的旋转/平移误差最大值。
- 对比：GLOMAP + SIFT、GLOMAP + ALIKED + LightGlue、π³、π³ + BA、GLUEMAP†（仅运动平均）、GLUEMAP、GLUEMAP*（GT 标定）。
- 输入：各数据集按不同图像数/序列采样；LaMAR 只用手机图像。

### 5.3 关键结果

**ETH3D（Table 1）**

| 方法 | AUC@1 ↑ | AUC@3 ↑ | AUC@5 ↑ |
|------|--------:|--------:|--------:|
| GLOMAP + SIFT | 45.6 | 62.2 | 66.7 |
| GLOMAP + ALIKED + LightGlue | 42.9 | 62.1 | 67.4 |
| π³ | 13.2 | 36.1 | 48.9 |
| π³ + BA | 30.6 | 55.1 | 65.1 |
| GLUEMAP†（仅运动平均） | 20.3 | 49.0 | 61.9 |
| **GLUEMAP** | **53.0** | **76.9** | **83.6** |
| **GLUEMAP\***（GT 标定） | **74.0** | **85.9** | **89.0** |

**SMERF（Table 4，AUC@1/5/20）**

| 方法 | minimal | medium | high |
|------|--------:|-------:|-----:|
| GLOMAP + SIFT | 3.5 / 4.4 / 5.4 | 1.4 / 1.6 / 1.8 | 1.5 / 2.3 / 3.1 |
| π³ | 3.2 / 18.0 / 51.7 | 1.5 / 14.3 / 49.8 | 1.3 / 15.7 / 52.1 |
| π³ + BA | 3.1 / 18.5 / 54.1 | 1.5 / 14.3 / 53.4 | 1.2 / 14.7 / 52.2 |
| **GLUEMAP** | **10.1 / 54.9 / 82.0** | **14.6 / 71.4 / 92.4** | **27.7 / 79.1 / 94.6** |

**CO3Dv2（Table 3，AUC@3/10/30）**

| 图像数 | GLUEMAP | π³ + BA |
|--------|---------|---------|
| 10 | 54.8 / 79.3 / 90.3 | 55.3 / 78.8 / 90.1 |
| 20 | 56.7 / 79.8 / 90.3 | 59.4 / 80.9 / 90.9 |
| 40 | 58.7 / 80.7 / 90.7 | 60.5 / 81.3 / 91.2 |

> CO3Dv2 上 GLUEMAP 与 π³+BA 基本持平（π³+BA 在紧阈值略高）；GLUEMAP 的优势主要在 ETH3D、SMERF、LaMAR 这类难场景。

**LaMAR / IMC2021**：
- LaMAR：纯前馈方法（π³/VGGT/MapAnything）因数千图直接 **OOM**；经典 SIFT/AL+LG 在 HGE/CAB 上较差；GLUEMAP 明显更好（Table 5）。具体数字按原表复核。
- IMC2021：GLUEMAP 在不同图像数/集合上与经典方法互有胜负，整体有竞争力（Table 2）。

**运行时（Table 9/10）**

| 阶段 | 中位 |
|------|------|
| 两视图批 | 1.20 s |
| star 批 | 0.31 s（90 分位 0.77 s） |
| tracking 批 | 1.27 s（90 分位 1.81 s） |
| 运动平均 | 小场景秒级；大场景随变量增长 |
| 增强 BA | LaMAR 分钟级 |

**消融（Table 6/7/8）**

| 消融 | 结论 |
|------|------|
| A-BA 三类 track | ETH3D 上 SIFT 贡献最大；SMERF 上虚拟 track 关键；前馈 track 补外观变化 |
| Backbone | π³ 整体最好；GLUEMAP 对 backbone 泛化，运动平均/A-BA 都稳定增益 |
| Doppelgangers++ / overlap 过滤 | 对称场景必需；去掉后可能 collapse |
| 运动平均 vs 直接前馈 | GLUEMAP† 已优于纯前馈，A-BA 再提升 |

## 6. 能力与失败模式 (Capabilities & Failure Modes)

### 能做什么

| 能力 | 条件 | 证据 |
|------|------|------|
| 大规模 SfM（数万图） | GPU + 多卡；稀疏图 | LaMAR 数千图；论文称数万 |
| 低重叠/低纹理重建 | 前馈 backbone 能给出局部几何 | SMERF minimal 20° 82.0 |
| 对称结构 | Doppelgangers++ 过滤 + 动态阈值 | ETH3D 高对称场景 |
| COLMAP 兼容输出 | 标准稀疏模型 | README |
| 多 backbone | π³/Pi3X/VGGT/MapAnything | Table 7 |
| 与 MVS/3DGS 衔接 | 输出 COLMAP 格式 | 生态兼容 |

### 不能做什么

| 失败模式 | 原因 |
|----------|------|
| 鱼眼/全景 | 前馈 backbone 只训练针孔 |
| 纯旋转运动 | A-BA 公式处理不了（论文 Limitations） |
| 前馈局部失败 | 全局依赖局部重建质量；低质量 star 会拖累 |
| 极小重叠 + 前馈也失败 | 没有足够约束，BA 也救不回来 |
| 无 GPU | 前馈 backbone 需要 GPU |
| 安装/依赖 | Ceres/METIS/Boost 等较重 |
| 商用 | GLUEMAP 是 BSD，但第三方依赖/权重单独许可 |

### 6.1 隐含假设 (Hidden Assumptions)

1. **前馈 backbone 的局部几何足够好**：GLUEMAP 不修正局部大错，只做全局融合。
2. **针孔相机**：鱼眼不在内。
3. **view graph 连通**：动态阈值保最大连通分量，但断裂图仍然失败。
4. **star 内尺度一致**：similarity averaging 每个 star 一个尺度；如果 star 内尺度不一致，假设不成立。
5. **SIFT 在纹理足够时可用**：增强 BA 依赖 SIFT tracks；弱纹理时虚拟 track 补，但不是万能。
6. **Doppelgangers++ 能识别对称**：漏检会导致错误边。
7. **多卡/大显存可接受**：大规模场景需要并行和足够内存。

## 7. 与相关工作对比 (Comparison)

| 方法 | 核心 | 全局一致性 | 规模 | 需要相机 | 输出 |
|------|------|-----------|------|----------|------|
| COLMAP / GLOMAP | SIFT + 增量/全局 SfM + BA | 强 | 大 | 需要（或先估） | COLMAP |
| DUSt3R | 成对 pointmap + 3D 对齐 | 中 | 小-中 | 不需要 | 点云/深度 |
| MASt3R-SfM | 前馈匹配 + 稀疏全局对齐 | 中 | 中 | 不需要 | 稀疏/稠密 |
| VGGT | 多视图一次前向 | 强（前馈） | 中（显存限） | 不需要 | 相机/深度/点图 |
| **GLUEMAP** | **前馈局部 + 全局 SfM + A-BA** | **强** | **大（数万）** | **不需要** | **COLMAP** |

**面试 Tip**：当被问到“GLUEMAP 和前馈方法有什么区别”时，回答——前馈方法试图用一个网络解决全局重建，显存和全局一致性受限；GLUEMAP 让前馈只做 star 内的局部重建，把全局交给经典运动平均和 BA。它本质上是**用前馈补经典 SfM 的局部鲁棒性，用经典 SfM 补前馈的全局一致性和规模**。

## 8. 精读建议 (Reading Guide)

**值得精读原文的人**：
- 做大规模 SfM / 3D 重建系统、需要 COLMAP 兼容输出的人。
- 想把前馈模型产品化、但被显存/全局一致性卡住的人。
- 研究“学习 + 优化”混合管线的人。

**建议章节路径**：
- 先读 §3.1–3.2：view graph + star graph 局部推理。
- 再看 §3.3：intrinsics/rotation/similarity averaging。
- 再看 §3.4：增强 BA 的三类 track。
- 再看 §4.3：ETH3D/SMERF/LaMAR 的数字与协议。
- 可跳 §2（相关工作）——除非写综述。

**不值得精读的理由**：
- 你只做两视图/少量图——DUSt3R/VGGT 更直接。
- 你做在线 SLAM——GLUEMAP 是离线批处理。
- 你的场景是鱼眼/纯旋转——论文明确不适用。

## 9. 补充：面试高频 Q&A

**Q1：GLUEMAP 为什么不直接用一个前馈网络做全局？**
A：全局 attention 显存 $O(N^2)$，数千图就 OOM；而且前馈缺少全局优化和回环。GLUEMAP 让前馈只做局部 star，全局交给运动平均/BA。

**Q2：为什么每个 star 只用一个尺度？**
A：star 内局部重建是尺度一致的；逐边尺度会被噪声三角化影响。一个 star 一个尺度更稳。

**Q3：虚拟 track 是什么？**
A：从 star 中心图像的深度反投影到邻居图像，形成额外 2D-3D 观测；它补上低重叠/低纹理时 SIFT/前馈 track 不足的约束。

**Q4：Doppelgangers++ 为什么重要？**
A：对称/重复结构会产生错误匹配；DG 打分 + 动态阈值过滤掉不共视的边，避免全局 collapse。

**Q5：GLUEMAP 能替代 COLMAP 吗？**
A：它不是替代，而是在 COLMAP 生态里加前馈局部先验；输出仍是 COLMAP 格式。标准场景 GLOMAP 仍很强，难场景 GLUEMAP 更稳。

**Q6：支持哪些 backbone？**
A：π³、Pi3X、VGGT、MapAnything；论文实验 π³ 最好，但框架对 backbone 泛化。

**Q7：能跑多大？**
A：论文称数万张；LaMAR 数千张已验证。实际取决于 GPU/内存和 BA 规模。

**Q8：主要限制？**
A：鱼眼、纯旋转、前馈局部失败、依赖复杂、需要 GPU/多卡。

## 10. 补充：复现清单

**安装**：

```bash
# Python ≥3.10；Ceres / Eigen / METIS / Boost / OpenMP 可用
CMAKE_PREFIX_PATH=$CONDA_PREFIX pip install -e .
python -c "import gluemap; import pygluemap; print(pygluemap.__file__)"
```

**模型权重**：按 `INSTALL.md §4` 下载 Pi3、SALAD、VGGSfM tracker、Doppelgangers++。

**运行**：

```bash
# 单机
gluemap-demo --help

# 多卡
torchrun --nproc_per_node=N gluemap-demo ...

# 基准
gluemap-benchmark ...
```

**关键配置**：

| 参数 | 说明 |
|------|------|
| `skip_doppelgangers` | 无对称/重复结构时可跳过，加速 |
| `rerun_from` | 从 `retrieval` / `twoview` / `star` 续跑 |
| `backbone` | π³ / Pi3X / VGGT / MapAnything |
| `star` 邻居数 | 最多 25 帧（按 DG 分数） |
| 动态阈值 | 0.8 → 0.1 递减，最低 0.2 |

**常见坑**：
1. Ceres/METIS/Boost 缺失或 ABI 不匹配，编译失败。
2. 忘记下载 Doppelgangers++/SALAD/Pi3 权重。
3. 对称场景跳过 Doppelgangers，导致 collapse。
4. 纯旋转/鱼眼输入，结果不可用。
5. 大场景不用多卡，时间/内存爆。
6. 第三方依赖/权重许可与 GLUEMAP 的 BSD 不同，商用要逐个检查。

## 11. 补充：来源与核查

| 结论/数字 | 来源 | 核查方式 |
|-----------|------|----------|
| 四阶段 pipeline | 论文 §3 / README | PDF/README |
| 动态阈值 0.8→0.2 | 论文 §3.1, Eq. (2) | PDF 原文 |
| star 最多 25 帧 | 论文 §3.2 | PDF 原文 |
| 每个 star 一个尺度 | 论文 §3.3, Eq. (12)–(13) | PDF 原文 |
| 增强 BA 三类 track | 论文 §3.4 | PDF 原文 |
| 虚拟 track ≈100、10% 全局 | 论文 §3.4 | PDF 原文 |
| ETH3D 53.0/76.9/83.6；* 74.0/85.9/89.0 | 论文 Table 1 | PDF 原文 |
| SMERF 10.1/54.9/82.0 等 | 论文 Table 4 | PDF 原文 |
| CO3Dv2 54.8/79.3/90.3 等 | 论文 Table 3 | PDF 原文 |
| LaMAR 前馈 OOM | 论文 §4.3 / Table 5 | PDF 原文 |
| Runtime 1.20/0.31/1.27 s | 论文 Table 9 | PDF 原文 |
| 数万张图像 | 论文 Abstract | PDF 原文 |
| 鱼眼/纯旋转/依赖前馈 | 论文 §4.4 Limitations | PDF 原文 |
| 许可 new BSD | 官方 README | 2026-11-06 |

**未在本文中当作事实的**：LaMAR/IMC2021 的逐项 AUC（表格抽取不完整，按原表复核）、总运行时间、各阶段 GPU-hours、第三方依赖的具体许可。部署前请以论文表格和官方 `INSTALL.md` 为准。

---
[← Back to Theory](../README.md)

**关键引用**：
- 论文：https://arxiv.org/abs/2605.26103
- 代码：https://github.com/colmap/gluemap
- 项目页：https://lpanaf.github.io/cvpr26_gluemap/
- GLOMAP：https://github.com/colmap/glomap
