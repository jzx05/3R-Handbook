# DUSt3R: 几何 3D 视觉变得简单 (DUSt3R: Geometric 3D Vision Made Easy)

> ⚙️ 本文由 3R Handbook 解析流程维护 | 2026-11-06
>
> **论文**: DUSt3R: Geometric 3D Vision Made Easy, CVPR 2024（arXiv 2312.14132v3）
> **链接**: https://arxiv.org/abs/2312.14132
> **代码**: https://github.com/naver/dust3r（CC BY-NC-SA 4.0，非商用）
> **核心定位**: 用一对图像直接回归同一坐标系下的两张 pointmap，再用 3D 空间全局对齐把多视图拼起来；不需要相机内参、位姿，也不需要 COLMAP 式多阶段链路。

<!-- source: https://arxiv.org/abs/2312.14132 -->

## ⚡ 快速判断（30 秒读完这段就够了）

| 维度 | 判断 |
|------|------|
| 核心结论 | 把成对 3D 重建从“深度 + 相机 + 三角化”改成“两张同一坐标系的 pointmap 回归”；多视图再用一个 3D 空间优化对齐。一个未微调模型同时做稠密重建、深度、像素匹配、内参和相对/绝对位姿。 |
| 适合精读 | 做 3R / 前馈几何重建 / SLAM / SfM 的研究者；想理解 MASt3R、VGGT、GLUEMAP、VidMap 这条线的源头；需要“无标定、无位姿”稠密重建的工程师。 |
| 可以跳过 | 只做 3DGS / NeRF 渲染；只关心传统 MVS / SfM 理论；已经用 VGGT 做多视图且不需要 pairwise 细节；不做几何、只做语义/生成。 |
| 落地可行性 | 中高。权重开源、demo 易跑；但无 metric scale、完整图 O(N²)、全局对齐吃显存、代码为非商用许可。适合做离线重建/研究原型，不适合直接上量产机器人。 |
| 主要风险 | 动态场景、透明/反光、弱纹理、低重叠会失败或“脑补”；尺度未知；大规模多视图显存/时间爆炸；不能替代完整 SLAM 的回环与在线定位。 |

💡 **X-Ray 开场**
DUSt3R 的核心突破不是“又训练了一个更强的深度网络”，而是**换了一个输出表示**：对每张图回归一张 pointmap（每像素一个 3D 点），并且让一对图的两张 pointmap 表达在**同一个坐标系**里。这个表示把“像素对应、深度、相机、点云”绑在一个张量上，于是像素匹配可以退化成 3D 最近邻，内参可以从 $x/z$、$y/z$ 估出来，相对位姿可以做 Procrustes。多视图时，它不跑传统 BA，而是在 3D 空间里做一次全局对齐。代价是：尺度未知、假设静态、完整图是 $O(N^2)$ 对。

📍 **研究全景时间线**

```text
[2006-2020] 经典 SfM/MVS: Bundler → COLMAP → MVSNet / PatchMatch MVS
[2021]      学习匹配: LoFTR / SuperGlue 等，但仍在经典 SfM 链路里
[2023.12]   DUSt3R ← 当前位置：把成对重建变成 pointmap 回归
[2024]      MASt3R（匹配头+metric）/ MonST3R（动态场景）
[2025]      VGGT（多视图一次前向）/ Fast3R / Spann3R / CUT3R / MASt3R-SfM
[2026]      GLUEMAP（全局 SfM+前馈）/ VidMap（视频 SfM）/ MapAnything / Pow3R / MUSt3R
← 局限：尺度、动态、O(N²)、在线长序列
```

## 1. 核心架构/方法总览 (Overview / Architecture)

### 1.1 系统对比概览 (System Component Comparison)

| 组件 | 输入 | 输出 | 训练/推理差异 |
|------|------|------|---------------|
| 共享 ViT-L 编码器 | 单张 RGB（512 长边，patch 16） | 每图 token $F_1, F_2$（512×384 时各 768 个 token） | 训练可调；初始化自 CroCo v2 预训练 |
| 解码器 1 / 解码器 2（ViT-B） | $F_1, F_2$ + 跨视图 cross-attention | 两路解码 token | 两个独立 decoder，初始化相同、之后各自训练 |
| 回归头 1 / 2 | 解码 token | pointmap $X$ + confidence $C$ | 224 阶段线性头；512 阶段可换 DPT 头 |
| 图像对构建 | 图像集合 | pairs | 训练用检索/匹配筛选；推理支持 complete / swin / logwin / oneref |
| 全局对齐器 | pairwise pointmaps + confidence | 全局 pointmaps、相机、深度、内参 | **仅推理时优化**，没有可训练参数 |

### 1.2 关键机制 (Key Mechanism)

1. **Pointmap + 共享坐标系**：网络输出 $X^{1,1}$（图 1 的 pointmap，图 1 系）和 $X^{2,1}$（图 2 的 pointmap，图 1 系）。两张点云天然对齐，深度就是 $z$，像素匹配可以直接做 3D 最近邻。

2. **非对称双分支 + 交叉注意力**：共享 ViT-L 编码器提取两张图的 token；两个 ViT-B 解码器在每个 block 里做 self-attention（本视图）+ cross-attention（对方视图），持续交换信息。两个 decoder 初始化相同（`dec_blocks2 = deepcopy(dec_blocks)`），但之后独立训练；加载旧 checkpoint 时会自动复制缺失的 `dec_blocks2` 权重。

3. **尺度归一化的 3D 回归**：训练时把预测和 GT 的 pointmap 都按“所有有效点到原点的平均距离”归一化，再算逐像素欧氏距离。网络只需学形状和相对几何，不需要猜绝对尺度。

4. **置信度加权损失**：每个像素同时回归一个正置信度 $C=1+\exp(\hat C)$；损失为 $C\ell-\alpha\log C$。天空、透明、反光、遮挡等“本来就没有确定 3D 点”的区域会被降权，但 $-\alpha\log C$ 防止网络把所有像素都标成低置信度。

5. **3D 空间全局对齐**：多视图不跑传统 BA（最小化 2D 重投影误差），而是优化全局 pointmap 与每条边的 pairwise 位姿/尺度，使 3D 点之间的距离最小。先用最小生成树（MST）初始化，再 Adam 优化几百步。需要相机参数时，把全局点参数化成针孔模型即可。

⚡ **Eureka Moment**：网络只学“两张图的每个像素各自对应哪个 3D 点”，**不学相机**；相机、深度、内参、匹配都是从 pointmap 里“读”出来的。于是“几何估计”被改写成一个纯回归问题，经典链路里的特征匹配、本质矩阵、三角化、BA 都被绕开了。

### 1.3 信息流/架构图 (Flow / Diagram)

```text
训练时:
  I1 ──► ViT-L Encoder ──► F1 ──┐
  I2 ──► ViT-L Encoder ──► F2 ──┤   (共享权重)
                                 ▼
                    Decoder1 (ViT-B) ⇄ Decoder2 (ViT-B)
                       │  self-attn + cross-attn  │
                       ▼                           ▼
                    Head1                        Head2
                       │                           │
                 X1,1 + C1                    X2,1 + C2
                       │                           │
                       └──── L_regr + L_conf ─────┘
              (两张 pointmap 都在图 1 坐标系；GT 由深度+位姿反投影)

推理时:
  图像集合 ──► 图像对构建（complete / swin / logwin / oneref）
           ──► 每对过网络 ──► X^{n,e}, X^{m,e}, C
           ──► 全局对齐（MST 初始化 + 3D 误差优化）
           ──► 全局点云 / 深度 / 内参 / 相对位姿 / 绝对位姿 / 像素匹配
```

## 2. 数学核心 (Math Core)

📌 **Napkin Formula**（一行抓住本质）：

```text
X^{1,1}, X^{2,1}, C = F_θ(I1, I2)                  # 同一坐标系的两张 pointmap

ℓ_regr(v,i) = || X_i^{v,1}/z − X̄_i^{v,1}/z̄ ||₂     # 尺度归一化后的 3D 距离
L_conf = Σ_v Σ_i ( C_i^{v,1} · ℓ_regr(v,i) − α · log C_i^{v,1} )

χ* = argmin_{χ,P,σ} Σ_e Σ_v Σ_i C_i^{v,e} || χ_i^v − σ_e P_e X_i^{v,e} ||₂
                                                     # 多视图全局对齐（3D 误差）
```

**目标**：先让网络学会“一对图像的每个像素对应哪个 3D 点”，再让多视图的 pairwise 预测在 3D 空间里拼成一个一致的场景。

**变量说明**：

| 符号 | 含义 |
|------|------|
| $X^{v,1}$ | 视图 $v$ 的 pointmap，表达在图 1 的相机系 |
| $\bar X^{v,1}$ | 对应的 GT pointmap（由 GT 深度 + 位姿反投影） |
| $z, \bar z$ | 预测 / GT 的尺度归一化因子（所有有效点到原点平均距离） |
| $C_i^{v,1}$ | 像素 $i$ 的置信度，$=1+\exp(\hat C_i^{v,1})>1$ |
| $\alpha$ | 置信度正则权重；官方训练用 0.2 |
| $\chi_i^v$ | 全局对齐后，视图 $v$ 的像素 $i$ 在世界系的 3D 点 |
| $P_e, \sigma_e$ | 边 $e$ 的 pairwise 位姿与尺度 |

**直觉**：回归损失只关心“形状对不对”，不关心“绝对尺度是多少”；置信度损失让网络在没把握的地方“认怂”；全局对齐则把所有 pairwise 的“局部正确”拼成“全局一致”。

**补充：从 pointmap 导出几何量**

- 深度：$D_{i,j} = X_{i,j,2}$（pointmap 的 $z$ 分量）。
- 像素匹配：3D 最近邻 + 互为最近邻（reciprocal）。
- 焦距：假设主点居中、像素方形，最小化 $(i',j')$ 与 $f\cdot(X_x,X_y)/X_z$ 的加权误差；Weiszfeld 迭代求解。
- 相对位姿：对 $X^{1,1}$ 与 $X^{1,2}$ 做带尺度的 Procrustes。
- 绝对位姿：2D-2D 匹配 → 2D-3D 对应 → PnP-RANSAC。

## 3. 带数字走一遍：玩具例子 (Worked Example)

假设输入 3 张图，分辨率 512×384，patch size 16：

```text
Step 1: 图像尺寸 → token 数
        512/16 = 32, 384/16 = 24  →  每张图 768 个 token

Step 2: 图像对
        complete graph：C(3,2) = 3 对
        symmetrize=True：3 × 2 = 6 次前向
        编码器对称化优化：只编码 3 次（每张图一次）

Step 3: 网络输出
        每张图：pointmap 512×384×3 + confidence 512×384
        3 张图共 3 份 pointmap / confidence

Step 4: 全局对齐变量
        每张图：log depth 196,608 + pose 7 + focal 1 + pp 2 ≈ 196,618
        3 张图 ≈ 589,854 个标量
        每条边：quaternion(4) + translation(3) + log scale(1) + adaptor(2) = 10
        3 条边共 30 个标量
        优化：Adam，lr=0.01，默认 300 步，cosine/linear 衰减

Step 5: 导出结果
        scene.get_pts3d() → 3 张 H×W×3 点云
        scene.get_im_poses() → 3 个 cam-to-world
        scene.get_focals() → 3 个焦距
        scene.get_masks() → confidence > min_conf_thr 的掩码
```

**显存/存储估算**（按 fp32 张量大小，不含激活和优化器状态）：

```text
单张 pointmap：512×384×3×4 B = 2,359,296 B ≈ 2.25 MiB
单张 confidence：512×384×4 B ≈ 0.75 MiB
单张图合计 ≈ 3.0 MiB；3 张图 ≈ 9 MiB

每条边的两张 pointmap + 两张 confidence ≈ 6 MiB
3 条边 ≈ 18 MiB

20 张图的 complete graph：C(20,2)=190 条边
190 × 6 MiB ≈ 1.14 GiB（仅 pairwise 预测缓存）
再加 20 张图的全局 pointmap ≈ 60 MiB
再加 Adam 的一阶/二阶状态与反向图（如果训练）会显著更大
```

**关键数字**：

```text
推理速度（论文，H100）：≈ 40 ms / 对
全局对齐：几百步 Adam，论文称“秒级”（standard GPU）
512 DPT checkpoint：≈ 2,179 MB（约 2.1 GiB）
512 Linear checkpoint：≈ 2,031 MB
输入：512 长边，patch 16；token 数 = (W/16)×(H/16)
```

> 注意：上面的显存是**按张量大小估算**，不是实测峰值。实际峰值还取决于 batch、autograd、帧数、是否缓存 pairwise 输出。部署前务必用自己的分辨率/N 实测。

## 4. 工程视角 (Engineering View)

| 维度 | 数值/权衡 | 工程含义 |
|------|-----------|----------|
| 模型规模 | ViT-L 编码器（24 层、16 头、1024 维）+ ViT-B 解码器（12 层、12 头、768 维）+ DPT 头 | 权重文件约 2.1 GB（512 DPT）；需要 GPU，不适合边缘小设备 |
| 输入分辨率 | 512 长边，patch 16；支持 512×384 / 336 / 288 / 256 / 160 | 分辨率越高，pointmap 越细，但 token 和全局对齐显存按平方增长 |
| Pair 复杂度 | 完整图 $O(N^2)$；20 张图 190 对，对称化 380 次前向 | 长序列必须用 swin/logwin/oneref 稀疏化，或换 Fast3R/VGGT |
| 全局对齐 | 300 步 Adam，lr=0.01，MST 初始化 | 论文称秒级；实际随边数和分辨率增长；显存是主要瓶颈 |
| 推理延迟 | 论文：约 40 ms/对（H100） | 消费级 GPU 会慢数倍；多对推理要乘 pair 数 |
| 训练数据 | 8 个数据集，约 8.5M 对；三阶段 50/100/90 epochs | 论文未报告 GPU 数量与总 GPU-hours；复现成本高 |
| 尺度 | up-to-scale | 需要米制尺度时必须外部标定/IMU/GNSS/已知尺寸 |
| 许可 | CC BY-NC-SA 4.0 | 非商用；商用需换许可或换实现 |
| 输出 | 点云、深度、内参、相对/绝对位姿、像素匹配 | 一个模型覆盖多个任务，但每个任务都有各自的误差边界 |

**部署约束**：

- 必须有 GPU；512 DPT 权重约 2.1 GB，加上 pointmap/优化器状态，显存需求随图像数增长。
- 完整图只适合少量图；长序列要用稀疏图或后来的流式/多视图模型。
- 输出没有绝对尺度；机器人/测量场景必须引入外部尺度源。
- 代码是非商用许可；商用产品需要评估替代方案（MASt3R、VGGT 等也要逐个看许可）。
- 全局对齐是离线优化；在线 SLAM 需要额外的跟踪/回环/增量机制（见 MASt3R-SLAM、VGGT-SLAM）。

**代码地图**：

| 功能 | 文件 |
|------|------|
| 模型主类 | `dust3r/model.py:46` `AsymmetricCroCo3DStereo` |
| 对称化编码 | `dust3r/model.py:153` `_encode_symmetrized` |
| 双解码器 + 交叉注意力 | `dust3r/model.py:172` `_decoder` |
| 前向与输出命名 | `dust3r/model.py:199` `forward` |
| 回归/置信度损失 | `dust3r/losses.py:142` `Regr3D`, `:197` `ConfLoss` |
| 全局对齐优化器 | `dust3r/cloud_opt/optimizer.py:16` `PointCloudOptimizer` |
| 对齐循环 | `dust3r/cloud_opt/base_opt.py:326` `global_alignment_loop` |
| MST / Procrustes / PnP | `dust3r/cloud_opt/init_im_poses.py:67,123,220,247` |
| 图像对构建 | `dust3r/image_pairs.py:11` `make_pairs` |
| 批量推理 | `dust3r/inference.py:56` `inference` |

## 5. 数据与评测 (Data & Eval)

### 5.1 数据组成

论文用 8 个数据集混合，共约 **8.5M 图像对**：

| 数据集 | 场景类型（论文描述） | 在训练中的角色 |
|--------|----------------------|----------------|
| Habitat | 合成室内 / embodied AI | 提供合成室内几何与多视图 |
| ARKitScenes | 真实室内 RGB-D | 真实室内深度/位姿 |
| MegaDepth | 互联网照片 + SfM 深度 | 室外/地标、多样视角 |
| Static Scenes 3D | 静态场景 | 静态物体/场景几何 |
| BlendedMVS | 合成 + 真实 MVS | 多视图立体 |
| ScanNet++ | 真实室内 RGB-D | 室内高精度几何 |
| CO3Dv2 | 物体中心视频 | 物体级多视图 |
| Waymo | 自动驾驶 | 室外大场景/运动 |

> 每个 epoch 从每个数据集**等量采样**，避免大数据集淹没小数据集；图像对由现成检索 + 匹配筛选，论文共提取 8.5M 对。

### 5.2 评测设置

**任务 1：多视图相对位姿（CO3Dv2 / RealEstate10K）**
- CO3Dv2：41 个类别；RealEstate10K：1.8K 测试视频。
- 每个序列随机选 10 帧，所有 45 对送网络。
- 指标：RRA@15、RTA@15、mAA(30)。

**任务 2：多视图深度（DTU / ETH3D / Tanks and Temples / ScanNet）**
- 不使用 GT 相机/位姿/深度范围；按中位数对齐尺度后计算。
- 指标：AbsRel（rel ↓）、$\tau=1.03$ 的 inlier ratio（↑）。

**任务 3：DTU 稠密重建**
- zero-shot，不在 DTU 训练集上微调。
- 指标：Chamfer Accuracy / Completeness / Overall（mm）。

**任务 4：绝对位姿 / visual localization**
- 7Scenes、Cambridge-Landmarks；中位平移/旋转误差（cm/°）。

**任务 5：单目深度**
- DDAD、KITTI、NYUD-v2、BONN、TUM；AbsRel、$\delta_{1.25}$。

### 5.3 关键结果

**多视图相对位姿（10 帧；数字来自 Table 2）**

| 方法 | CO3Dv2 RRA@15 ↑ | CO3Dv2 RTA@15 ↑ | CO3Dv2 mAA(30) ↑ | RealEstate10K mAA(30) ↑ |
|------|----------------:|----------------:|-----------------:|------------------------:|
| PoseDiffusion | 80.5 | 79.8 | 66.5 | 48.0 |
| DUSt3R 512 + PnP | 94.3 | 88.4 | 77.2 | 61.2 |
| **DUSt3R 512 + 全局对齐** | **96.2** | 86.8 | 76.7 | **67.7** |

**多视图深度（DUSt3R 512；数字来自 Table 3）**

| 数据集 | rel ↓ | $\tau$ ↑ |
|--------|------:|------------:|
| ScanNet | (4.93) | (60.20) |
| ETH3D | **2.91** | **76.91** |
| DTU | 3.52 | 69.33 |
| Tanks and Temples | 3.17 | 76.68 |
| 平均 | 4.73 | 64.52 |

**DTU 稠密重建（Table 4）**

| 指标 | DUSt3R 512 |
|------|-----------:|
| Accuracy ↓ | 2.677 mm |
| Completeness ↓ | 0.805 mm |
| Overall ↓ | 1.741 mm |

**消融（Table 1/2/3 汇总）**

| 消融 | 结论 |
|------|------|
| CroCo 预训练 | 去掉后 7Scenes 误差明显变大（如 Chess 3/0.96 → 5/1.76），单目深度也变差 |
| 224 → 512 | 分辨率提升带来一致改善；512 是默认 |
| 全局对齐 vs PnP | GA 在多视图一致性（RealEstate mAA 67.7 vs 61.2）更好；PnP 在单对 RTA（88.4 vs 86.8）更好 |
| 置信度 | 论文没有单独的大表消融，但损失和全局对齐都依赖它；定性上压低天空/难区域 |

**口径提醒**：

- ScanNet 数字带括号：其训练集与 Habitat 有重叠（论文 4.4 节），不能当作完全零样本。
- 多视图深度按中位数对齐尺度后再算指标；不是米制精度。
- CO3Dv2/RealEstate10K 是 10 帧协议；少视图（3–10）结果在附录。
- 不同论文的 RRA/RTA/mAA 可能用不同阈值/协议，不要直接跨表比较。

## 6. 能力与失败模式 (Capabilities & Failure Modes)

### 能做什么

| 能力 | 条件 | 证据 |
|------|------|------|
| 无标定、无位姿的成对稠密重建 | 两张有重叠的图像 | 论文主实验、demo |
| 多视图点云/相机/深度 | 少量图像 + 可接受的显存 | CO3Dv2/RealEstate10K 位姿、DTU/ETH3D 深度 |
| 单目深度 | 同一张图喂两次 $F(I,I)$ | 论文单目深度实验 |
| 像素匹配 | 3D 最近邻 + reciprocal | 论文 Sec. 3.3 |
| 内参/相对位姿/绝对位姿 | 从 pointmap 导出 | 论文 Sec. 3.3/3.4、visual localization |
| Zero-shot 跨数据集 | 训练分布内/接近 | DTU zero-shot、7Scenes/Cambridge |

### 不能做什么

| 失败模式 | 原因 |
|----------|------|
| 米制尺度 | 单目/双目本质；输出 up-to-scale |
| 动态场景 | 假设静态、每像素单点；运动物体会拖影/重影 |
| 透明/反光/天空 | 每条射线可能没有唯一 3D 点；置信度只能缓解 |
| 强畸变/鱼眼 | 假设针孔、主点居中、像素方形 |
| 低重叠/无重叠 | 网络会“脑补”看似合理的几何，但不可信 |
| 重复/对称结构 | 全局对齐只优化 3D 距离，可能对齐到错误实例 |
| 长序列/大规模 | 完整图 O(N²)，全局对齐变量多、显存大、易漂移 |
| 在线实时 SLAM | 没有跟踪/回环/增量机制；需要后续工作 |
| 非商用 | 代码 CC BY-NC-SA 4.0 |

### 6.1 隐含假设 (Hidden Assumptions)

1. **静态场景 + 单层几何**：每个像素只对应一个 3D 点，忽略半透明、玻璃、运动物体。
2. **针孔相机 + 主点居中 + 像素方形**：内参估计尤其是这样；鱼眼/强畸变不在模型内。
3. **尺度可被平均距离归一化**：训练时消除尺度，但推理时也丢掉了 metric scale。
4. **置信度可当权重**：它不是校准概率；高置信度不等于几何一定正确。
5. **图是连通的**：全局对齐依赖图像对图；断裂图/错误边会导致失败。
6. **训练分布覆盖测试域**：室内/室外/物体/驾驶混合，但特殊传感器（事件、热成像、医学）未覆盖。
7. **评测协议可对齐尺度**：多视图深度的中位数对齐是评测妥协，不代表部署精度。

## 7. 与相关工作对比 (Comparison)

| 方法 | 表示 / 核心 | 多视图融合 | 需要相机 | 规模 | 适用场景 |
|------|-------------|-----------|----------|------|----------|
| COLMAP | 稀疏特征 + BA + MVS | 增量/全局 SfM | 需要（或先估） | 大 | 经典 SfM/MVS、离线 |
| **DUSt3R** | **pointmap 回归** | **3D 全局对齐** | **不需要** | 小-中 | 无标定稠密重建、研究 baseline |
| MASt3R | pointmap + 匹配头 + metric | 更可扩展的全局对齐 | 不需要 | 中 | 匹配、SfM、定位 |
| VGGT | 多视图 transformer | 一次前向 | 不需要 | 中-大 | 多视图相机/深度/点图 |
| Fast3R | 多视图一次前向 | 无 pairwise 对齐 | 不需要 | 大（1000+ 图） | 大规模前馈重建 |
| GLUEMAP | 前馈星图 + 全局 SfM + BA | 运动平均 + 增强 BA | 不需要 | 大 | 大规模、COLMAP 兼容 |
| VidMap | 视频 SfM + 时序结构 | 全局 SfM 优化 | 不需要 | 大（视频） | 视频重建、长序列 |

**面试 Tip**：当被问到“DUSt3R 和 COLMAP 的区别”时，回答——COLMAP 是“显式求解每个几何子问题再 BA”，DUSt3R 是“用学习先验直接回归 3D 点，再用 3D 误差做全局对齐”；DUSt3R 更简单、更快、无需标定，但尺度未知、动态/透明会失败、大规模仍需要稀疏图或后续模型。它不是替代 COLMAP，而是把“无约束稠密重建”的入口变简单了。

## 8. 精读建议 (Reading Guide)

**值得精读原文的人**：
- 做 3R / 前馈几何重建 / 无标定 SfM 的研究者——pointmap 表示和 3D 全局对齐是这条线的源头。
- 想理解 MASt3R / VGGT / GLUEMAP / VidMap 设计动机的工程师——先读懂 DUSt3R 的“损失了什么”，才能理解后续工作“补了什么”。
- 需要快速搭一个无标定稠密重建原型的团队——demo 和权重都现成，但要注意许可和尺度。

**建议章节路径**：
- 先读 §3（Method）的 3.1–3.2：pointmap、非对称双分支、回归 + 置信度损失。
- 再看 §3.3–3.4：匹配/内参/位姿怎么从 pointmap 导出，全局对齐的优化问题。
- 再看 §4：多视图位姿、深度、DTU 的数字与协议。
- 可跳 §2（相关工作）——除非写文献综述。
- 可跳 Appendix F 的训练细节——除非要复现训练。

**不值得精读的理由**：
- 如果你只做 3DGS/NeRF 渲染——pointmap 不是你的表示。
- 如果你已经用 VGGT 做多视图、且不需要 pairwise 推理——DUSt3R 的全局对齐会被 VGGT 的一次前向替代。
- 如果你要的是在线 SLAM——DUSt3R 是离线/批处理，应该看 MASt3R-SLAM / VGGT-SLAM / VidMap。

## 9. 补充：面试高频 Q&A

**Q1：为什么用 pointmap，不直接预测深度 + 相机？**
深度是每张图独立的，跨视图关系需要相机；相机本身又要优化。pointmap 把“像素↔3D”和“跨视图同 frame”绑在一起，匹配/内参/位姿都可以从它导出。代价是尺度未知、相机模型不显式。

**Q2：为什么两张图的 pointmap 都在图 1 的坐标系？**
两张点云天然对齐，可以直接做 3D 最近邻匹配和 Procrustes 相对位姿；深度就是 $z$；全局对齐只需要学 pairwise 变换。如果各自在自己的相机系，网络还得额外回归相对位姿。

**Q3：为什么要两个 decoder，不能共享吗？**
共享 encoder 已经足够提取特征；两个 decoder 让每个视图有独立表达，同时通过 cross-attention 交换信息，输出同一坐标系的两张 pointmap。代码里两个 decoder 初始化相同、之后独立训练。

**Q4：全局对齐为什么优化 3D 误差而不是重投影误差？**
3D 误差不需要显式相机模型，直接对齐 pointmap；优化更简单、收敛更快。需要相机参数时，再把全局点参数化成针孔模型，等价于在 3D 空间做 BA。缺点是 pointmap 不一定对应物理相机，可解释性弱。

**Q5：怎么从 pointmap 得到内参和位姿？**
内参：假设主点居中、像素方形，用 $x/z$、$y/z$ 与像素坐标的线性关系做 Weiszfeld 求焦距。相对位姿：两组 pointmap 做带尺度的 Procrustes。绝对位姿：2D-2D 匹配 → 2D-3D → PnP-RANSAC。

**Q6：尺度怎么处理？**
训练时用平均距离归一化，消除尺度；推理输出 up-to-scale。要 metric scale，必须引入外部信息（基线、IMU/GNSS、已知尺寸、度量深度先验）。MASt3R 的 metric 版本和 Pow3R 就是干这个的。

**Q7：DUSt3R 能替代 COLMAP 吗？**
在“少量图、要稠密几何、没有标定”的场景，它更简单、更快，精度也很有竞争力；在大规模 SfM、需要稀疏 landmark/回环/BA 的场景，COLMAP 仍然更成熟。GLUEMAP 这类工作正是在把两者结合，而不是简单替代。

**Q8：为什么完整图是 O(N²)？怎么扩到多图？**
每对图像都要过网络；N 张图有 N(N-1)/2 对。扩法：滑动窗口/对数窗口/单参考图（`swin-*`/`logwin-*`/`oneref-*`）、检索筛选、Fast3R 的一次多视图前向、VGGT 的多视图 transformer。

**Q9：confidence 是概率吗？**
不是严格校准的概率，是训练出来的逐像素不确定性权重。它用于损失加权、全局对齐权重和点云过滤。高置信度不等于“几何一定对”，只是“网络认为这里更确定”。

**Q10：DUSt3R 最大的失败模式是什么？**
动态场景、低重叠、重复结构、透明/反光、强畸变、长序列漂移，以及尺度未知。工程上要配合 confidence、多视图一致性、外部传感器和回环验证。

## 10. 补充：复现清单

**最小命令**：

```bash
git clone --recursive https://github.com/naver/dust3r
cd dust3r
# 按 README 创建 conda 环境并安装依赖
python3 demo.py --model_name DUSt3R_ViTLarge_BaseDecoder_512_dpt
```

**Python 最小推理**：

```python
from dust3r.inference import inference
from dust3r.model import AsymmetricCroCo3DStereo
from dust3r.image_pairs import make_pairs
from dust3r.cloud_opt import global_aligner, GlobalAlignerMode
from dust3r.utils.image import load_images

model = AsymmetricCroCo3DStereo.from_pretrained(
    "naver/DUSt3R_ViTLarge_BaseDecoder_512_dpt"
).to("cuda")
imgs = load_images(["a.jpg", "b.jpg", "c.jpg"], size=512, patch_size=model.patch_size)
pairs = make_pairs(imgs, scene_graph="complete", prefilter=None, symmetrize=True)
output = inference(pairs, model, "cuda", batch_size=1)

scene = global_aligner(output, device="cuda", mode=GlobalAlignerMode.PointCloudOptimizer)
scene.compute_global_alignment(init="mst", niter=300, schedule="linear", lr=0.01)
pts3d, masks, poses, focals = scene.get_pts3d(), scene.get_masks(), scene.get_im_poses(), scene.get_focals()
```

**默认值**：

| 参数 | 默认 | 说明 |
|------|------|------|
| `image_size` | 512 | 必须与 checkpoint 匹配（224 模型用 224） |
| `patch_size` | 16 | 图像尺寸需整除 |
| `scene_graph` | `complete` | 长序列用 `swin-3` / `logwin-3` / `oneref-0` |
| `symmetrize` | `True` | 同时推理两个方向 |
| `mode` | `PointCloudOptimizer`（>2 图） | 2 图用 `PairViewer` |
| `init` | `mst` | 最小生成树初始化 |
| `niter` | 300 | 全局对齐步数 |
| `schedule` | `linear`（demo）/ `cosine`（函数默认） | 学习率衰减 |
| `lr` | 0.01 | Adam |
| `min_conf_thr` | 3 | 点云/掩码阈值 |

**常见坑**：
1. checkpoint 与分辨率不匹配（224 vs 512）。
2. 图像尺寸不是 patch 的整数倍。
3. 完整图 O(N²)，20 张图就是 190 对（对称化 380 次前向）。
4. 512 分辨率 + 多图全局对齐容易 OOM。
5. 输出不是米制；需要外部尺度。
6. 点云有漂浮物，用 confidence + 天空 mask + 深度一致性清洗。
7. 许可证 CC BY-NC-SA 4.0，商用需注意。

## 11. 补充：来源与核查

| 结论/数字 | 来源 | 核查方式 |
|-----------|------|----------|
| pointmap 定义、Eq. 1–3 | 论文 Sec. 3, Eq. (1)–(3) | PDF 原文 |
| confidence loss, Eq. 4 | 论文 Sec. 3.2, Eq. (4) | PDF 原文 |
| 8 个数据集、8.5M pairs | 论文 Sec. 4 / Appendix F.1 | PDF 原文 |
| 三阶段训练超参 | 论文 Appendix F.2, Table 7 | PDF 原文 |
| CO3Dv2 / RealEstate10K 位姿数字 | 论文 Table 2 | ar5iv 表格核对 |
| 多视图深度数字 | 论文 Table 3 | ar5iv 表格核对 |
| DTU Chamfer 数字 | 论文 Table 4 | ar5iv 表格核对 |
| 架构（ViT-L / ViT-B / DPT） | 论文 Sec. 4 + README 训练命令 | 代码/README |
| 全局对齐默认 300 步、lr 0.01、Adam | `dust3r/cloud_opt/base_opt.py:326-349` | 代码 |
| MST 初始化、Procrustes、PnP | `dust3r/cloud_opt/init_im_poses.py` | 代码 |
| 训练 criterion `alpha=0.2` | README 训练命令 | README |
| 推理 ~40ms/pair（H100） | 论文 Sec. 3.4 | PDF 原文 |
| checkpoint 大小 2,179 MB / 2,031 MB | 官方下载链接 Content-Length | 2026-11-06 实测 |
| token 数 768（512×384, patch 16） | 计算：32×24 | 算术 |

**未在本文中当作事实的**：DUSt3R 的具体参数量、真实部署延迟（因硬件/分辨率而异）、后续工作的具体指标（本文只做定位，不做跨论文数字比较）。如果你要把这些写进正式材料，请回到对应论文的表格和代码 commit 再核一遍。

---
[← Back to Theory](../README.md)

**关键引用**：
- 论文: https://arxiv.org/abs/2312.14132
- 项目页: https://dust3r.europe.naverlabs.com/
- 代码: https://github.com/naver/dust3r
- CroCo: https://github.com/naver/croco
- MASt3R: https://github.com/naver/mast3r
- VGGT: https://github.com/facebookresearch/vggt
- GLUEMAP: https://github.com/colmap/gluemap
- VidMap: https://github.com/cvg/vidmap
