# VGGT: 视觉几何 grounded Transformer (VGGT: Visual Geometry Grounded Transformer)

> ⚙️ 本文由 3R Handbook 解析流程维护 | 2026-11-06
>
> **论文**: VGGT: Visual Geometry Grounded Transformer, CVPR 2025（arXiv 2503.11651v1）
> **链接**: https://arxiv.org/abs/2503.11651
> **代码**: https://github.com/facebookresearch/vggt
> **核心定位**: 用标准 Transformer 一次前向输出相机、深度、点图和跟踪特征，把多视图 3D 重建从前馈 + 后优化推进到纯前馈。

<!-- source: https://arxiv.org/abs/2503.11651 -->

## ⚡ 快速判断（30 秒读完这段就够了）

| 维度 | 判断 |
|------|------|
| 核心结论 | 一个约 **1.2B** 参数的 Transformer，输入 1–数百张图，**一次前向**输出每帧相机、深度、点图和跟踪特征。CO3Dv2/Re10K AUC@30 **88.2/85.3**（加 BA 91.8/93.5），DTU Overall **0.382 mm**，ETH3D 点图 Overall **0.677**，重建约 **0.2 s**；200 帧时 8.75 s / 40.63 GB（336×518, H100）。 |
| 适合精读 | 做多视图 3D 重建、SLAM/定位、3D 基础模型、点跟踪的人；想理解“DUSt3R 之后为什么可以不做 pairwise 对齐”的人。 |
| 可以跳过 | 只做两视图匹配/定位（MASt3R 更直接）；只做生成/渲染；只关心传统 SfM/BA 理论。 |
| 落地可行性 | 高。代码开源、有商业 checkpoint（需申请）、demo 成熟；但显存随帧数增长，200 帧要 40+ GB，长序列仍需分块/BA。 |
| 主要风险 | 鱼眼/全景不支持；极端旋转、大幅非刚性变形会失败；静态/小运动假设；无回环/在线机制；显存是硬约束。 |

💡 **X-Ray 开场**
DUSt3R/MASt3R 是“成对推理 + 后处理对齐”，VGGT 把这两步合成一个多视图 Transformer：所有帧的 token 一起做 frame-wise + global 交替注意力，一次前向直接输出相机、深度、点图和跟踪特征。它几乎没有 3D 归纳偏置，靠的是**大规模 3D 标注数据 + 标准 Transformer + 过完备预测**。结果是：在多个 3D 任务上，纯前馈就能超过需要后优化的方法，而且速度快一个数量级。

📍 **研究全景时间线**

```text
[2023.12] DUSt3R：成对 pointmap + 全局对齐
[2024.06] MASt3R：匹配头 + metric + 快速互惠匹配
[2025.03] VGGT ← 当前位置：多视图一次前向，相机/深度/点图/跟踪统一
[2025]    Fast3R / VGGT-SLAM / VGGT-Long / MV-DUSt3R / CUT3R
[2026]    VGGT-Ω / GLUEMAP / VidMap / MapAnything
← 局限：鱼眼、极端旋转、大幅非刚性、显存、无在线回环
```

## 1. 核心架构/方法总览 (Overview / Architecture)

### 1.1 系统对比概览 (System Component Comparison)

| 组件 | 输入 | 输出 | 训练/推理差异 |
|------|------|------|---------------|
| DINOv2 patchify | 每帧 RGB（最大边 518） | 每帧 image token | 预训练，后续端到端训练 |
| 24 层 Alternating-Attention | 所有帧 token + camera token + 4 个 register token | 更新后的 token | frame-wise 与 global 交替 |
| Camera head | camera token（+ 4 层 self-attn + linear） | $g\in\mathbb{R}^9$：四元数 4 + 平移 3 + FoV 2 | 监督 Huber loss |
| DPT head | image token → 稠密特征 | 深度 $D$、点图 $P$、跟踪特征 $T$、不确定性 $\Sigma$ | 多任务监督 |
| CoTracker2 tracking head | 跟踪特征 $T$ + query 点 | 所有帧的 2D 对应 | 跟踪损失 + 可见性 |
| 第一帧参考 | 第 1 帧 camera/register token 用特殊可学习 token | 相机/点图/深度都在第 1 帧坐标系 | 保持置换等变（除第 1 帧） |

### 1.2 关键机制 (Key Mechanism)

1. **多视图 token 序列 + Alternating-Attention**：每帧 patchify 成 token，所有帧拼成一个序列；每层先做 frame-wise self-attention（帧内），再做 global self-attention（跨帧）。没有 cross-attention。这样既能跨视图推理，又能保持每帧 token 的归一化/稳定性。

2. **Camera token + register token**：每帧额外加 1 个 camera token 和 4 个 register token；第 1 帧使用不同的可学习 token，让网络知道“这是参考帧”。camera token 经过 4 层 self-attention + linear 输出 9 维相机参数。

3. **过完备预测（over-complete predictions）**：相机、深度、点图、跟踪特征不是独立的，理论上可以互相推导；但论文让网络**同时预测所有量**，并在训练中全部监督。消融显示这比只预测部分量更好，因为多个任务互相正则。

4. **不确定性加权**：深度和点图各预测一个 aleatoric uncertainty $\Sigma$；损失为 $\|\Sigma\odot(\hat D-D)\|+\|\Sigma\odot(\nabla\hat D-\nabla D)\|-\alpha\log\Sigma$。梯度项让深度/点图在局部更平滑。

5. **跟踪头**：用 CoTracker2 架构，把 VGGT 的稠密跟踪特征作为输入；query 一个点，输出它在所有帧的对应。跟踪头不假设时序顺序，因此可用于无序图像集合。

⚡ **Eureka Moment**：**不需要为多视图 3D 设计复杂的几何模块。** 只要把多视图 token 放进一个足够大的 Transformer，用交替注意力控制计算，再用海量 3D 标注数据 + 多任务监督，网络自己会学出跨视图三角化和相机推理。

### 1.3 信息流/架构图 (Flow / Diagram)

```text
训练时:
  {I_i}_{i=1..N} ──► DINOv2 patchify ──► {t_i}
        + camera token g_i + 4 register tokens R_i
                        │
                        ▼
       24 × [ frame-wise self-attn → global self-attn ]
                        │
        ┌───────────────┼────────────────┬────────────────┐
        ▼               ▼                ▼                ▼
   camera head      DPT head         DPT head         tracking head
   g_i (9D)        D_i, Σ_i         P_i, Σ_i         T_i + CoTracker2
        │               │                │                │
        └──────── L_camera + L_depth + L_pmap + 0.05 L_track ────────┘

推理时:
  1–数百张图 ──► 一次前向 ──► 相机 / 深度 / 点图 / 跟踪
  可选：用预测的相机+点图初始化 BA → 进一步提升精度
```

## 2. 数学核心 (Math Core)

📌 **Napkin Formula**（一行抓住本质）：

```text
f({I_i}_{i=1..N}) = {g_i, D_i, P_i, T_i}_{i=1..N}

L = L_camera + L_depth + L_pmap + 0.05 · L_track

g = [q(4), t(3), f(2)]        # 四元数 + 平移 + FoV
P_i, D_i 都在第 1 帧相机坐标系；GT 按平均点距归一化
```

**目标**：用一个前馈 Transformer 同时估计多视图的相机、深度、点图和跟踪，并让这些输出在训练中互相约束。

**变量说明**：

| 符号 | 含义 |
|------|------|
| $g_i$ | 第 $i$ 帧相机参数，9 维：四元数 4 + 平移 3 + FoV 2 |
| $D_i$ | 深度图 |
| $P_i$ | 点图（3×H×W） |
| $T_i$ | 跟踪特征图（C×H×W） |
| $\Sigma_i^D, \Sigma_i^P$ | 深度/点图的不确定性 |
| $\lambda$ | 跟踪损失权重，0.05 |

**直觉**：相机、深度、点图本来可以互相推导（PnP、反投影），但让网络**显式预测所有量**并全部监督，相当于给每个任务提供额外的“辅助损失”，训练更稳、精度更高。推理时还可以选择用 depth + camera 反投影，或直接用 point head。

**补充：损失细节**

- 相机：Huber loss $\|g_i-\hat g_i\|_\epsilon$。
- 深度/点图：不确定性加权 L1 + 梯度一致性 + $-\alpha\log\Sigma$。
- 跟踪：L1 + 可见性 BCE；$\lambda=0.05$。
- 训练时对 GT 做尺度归一化（平均点距），但**不对预测做归一化**；网络直接学这个规范化输出。

## 3. 带数字走一遍：玩具例子 (Worked Example)

输入 10 帧 336×518 图像（VGGT 的常用评测分辨率）：

```text
Step 1: patchify
        DINOv2 patch = 14 → 518/14 = 37, 336/14 = 24
        每帧约 37×24 = 888 个 image token（不含 camera/register）

Step 2: 序列
        10 帧 × 888 ≈ 8,880 个 token + 每帧 1 camera + 4 register
        → 一次前向；frame-wise 与 global attention 交替 24 层

Step 3: 输出
        每帧：g_i (9D)、D_i (336×518)、P_i (3×336×518)、T_i、Σ
        10 帧合计：10 个相机 + 10 张深度 + 10 张点图 + 跟踪特征

Step 4: 运行时/显存（Table 9，H100，336×518）
        1 帧：0.04 s / 1.88 GB
        10 帧：0.14 s / 3.63 GB
        50 帧：1.04 s / 11.41 GB
        100 帧：3.12 s / 21.15 GB
        200 帧：8.75 s / 40.63 GB

Step 5: 训练
        160K iterations，2–24 帧/批，最大边 518
        64 × A100，9 天，bfloat16 + gradient checkpointing
```

**关键数字**：

```text
模型参数：约 1.2B
相机：CO3Dv2/Re10K AUC@30 88.2 / 85.3（feed-forward），91.8 / 93.5（+BA）
DTU：Acc 0.389 / Comp 0.374 / Overall 0.382 mm
ETH3D 点图（Depth+Cam）：Acc 0.873 / Comp 0.482 / Overall 0.677
重建延迟：约 0.2 s（论文，10 帧级别；H100）
```

> 注意：0.2 s 是论文多次实验中的量级；不同帧数/分辨率/硬件差异很大，以上表 Table 9 为准。

## 4. 工程视角 (Engineering View)

| 维度 | 数值/权衡 | 工程含义 |
|------|-----------|----------|
| 模型规模 | 约 1.2B 参数，24 层 alternating attention | 需要大显存 GPU；不适合边缘设备 |
| 输入分辨率 | 最大边 518，DINOv2 patch 14 | 分辨率越高 token 越多，显存/时间按平方增长 |
| 帧数 | 1–200 帧（论文演示） | 200 帧 40.63 GB；长序列要分块或换流式方案 |
| 延迟 | 10 帧 0.14 s；100 帧 3.12 s；200 帧 8.75 s（H100） | 前馈很快，但显存是主要瓶颈 |
| 训练成本 | 64 × A100 × 9 天，160K iters | 复现成本高；论文未报告总 GPU-hours |
| 许可 | 代码商业友好（排除军事用途）；原始 checkpoint 非商用；VGGT-1B-Commercial 需申请 | 商用要走商业 checkpoint 申请流程 |
| 尺度 | 训练时按平均点距归一化 | 输出尺度取决于训练数据；不是天然米制 |
| 后处理 | 可选 BA（约 1.8 s） | 前馈已很强，但 BA 仍能提升精度 |

**部署约束**：
- 显存随帧数增长很快：200 帧 40.63 GB（仅 feature backbone，336×518）。
- 长序列需要分块/滑窗，或使用 VGGT-Long / VGGT-SLAM 这类系统。
- 不支持鱼眼/全景；极端旋转、大幅非刚性变形会失败。
- 没有回环/在线跟踪机制；SLAM 需要外挂。
- 商用只能用 VGGT-1B-Commercial checkpoint（需申请），代码许可排除军事用途。

**代码地图**（官方 repo 结构；行号未核，按文件定位）：

| 功能 | 文件 |
|------|------|
| 模型入口 | `vggt/models/vggt.py` |
| 主干 / alternating attention | `vggt/models/aggregator.py` |
| 相机头 | `vggt/heads/camera_head.py` |
| DPT / 深度 / 点图头 | `vggt/heads/dpt_head.py` |
| 跟踪头 | `vggt/heads/track_head.py` |
| 相机参数编码/解码 | `vggt/utils/pose_enc.py` |
| 反投影点图 | `vggt/utils/geometry.py` |
| COLMAP demo | `demo_colmap.py` |
| Gradio demo | `demo_gradio.py` |

## 5. 数据与评测 (Data & Eval)

### 5.1 数据组成

训练使用 **17 个数据集**（论文 3.4）：

| 类型 | 数据集 |
|------|--------|
| 物体/视频 | Co3Dv2, WildRGB, PointOdyssey |
| 室内/室外 | ScanNet, Replica, Habitat, Mapillary, MegaDepth |
| 合成 | Kubric, HyperSim, MVS-Synth, Virtual KITTI, Aria Synthetic Environments, Aria Digital Twin, 合成艺术家资产 |
| 其他 | BlendMVS, DL3DV |

> 论文称数据规模与多样性与 MASt3R 大致相当。3D 标注来自传感器、合成引擎或 SfM。

### 5.2 评测设置

- **相机位姿**：CO3Dv2 / RealEstate10K，10 帧，AUC@30（RRA/RTA 的组合）。
- **多视图深度**：DTU，Acc/Comp/Overall（Chamfer）。
- **点图**：ETH3D，10 帧，Umeyama 对齐后算 Acc/Comp/Overall。
- **匹配**：ScanNet-1500，AUC@10/@20。
- **跟踪**：TAP-Vid（DAVIS / RGB-S / Kinetics），δavg / AJ / OA。
- **运行时/显存**：H100，336×518，1–200 帧。

### 5.3 关键结果

**相机位姿（Table 1）**

| 方法 | Re10K AUC@30 ↑ | CO3Dv2 AUC@30 ↑ | 时间 |
|------|---------------:|----------------:|------|
| DUSt3R | 67.7 | 76.7 | ~7 s |
| MASt3R | 76.4 | 81.8 | ~9 s |
| VGGSfM v2 | 78.9 | 83.4 | ~10 s |
| **VGGT（feed-forward）** | **85.3** | **88.2** | **~0.2 s** |
| VGGT（+BA） | 93.5 | 91.8 | ~1.8 s |

**DTU（Table 2）**

| 方法 | Acc ↓ | Comp ↓ | Overall ↓ |
|------|------:|-------:|----------:|
| DUSt3R | 2.677 | 0.805 | 1.741 |
| **VGGT** | **0.389** | **0.374** | **0.382** |

**ETH3D 点图（Table 3）**

| 方法 | Acc ↓ | Comp ↓ | Overall ↓ | 时间 |
|------|------:|-------:|----------:|------|
| DUSt3R | 1.167 | 0.842 | 1.005 | ~7 s |
| MASt3R | 0.968 | 0.684 | 0.826 | ~9 s |
| VGGT（Point） | 0.901 | 0.518 | 0.709 | ~0.2 s |
| **VGGT（Depth+Cam）** | **0.873** | **0.482** | **0.677** | **~0.2 s** |

**运行时/显存（Table 9，H100，336×518）**

| 帧数 | 1 | 10 | 50 | 100 | 200 |
|------|---:|---:|---:|---:|---:|
| 时间 (s) | 0.04 | 0.14 | 1.04 | 3.12 | 8.75 |
| 显存 (GB) | 1.88 | 3.63 | 11.41 | 21.15 | 40.63 |

**消融（Table 5/6）**

| 消融 | 结论 |
|------|------|
| Cross-attention vs global-only vs alternating | alternating 最好（ETH3D Overall 0.709 vs 0.827/1.061） |
| 多任务学习 | 同时监督相机/深度/点图/跟踪比只监督部分更好 |
| 点图 vs depth+camera | 推理时 depth+camera 反投影更准（0.677 vs 0.709） |
| DINOv2 vs 卷积 patchify | DINOv2 更稳、更好 |

**口径提醒**：
- VGGT 在 CO3Dv2 上训练过，Re10K 未见；CO3Dv2 数字不是零样本。
- ScanNet-1500 评测排除了训练中的 ScanNet 场景。
- DTU 的 VGGT 不需要 GT 相机；MASt3R 用 GT 相机三角化，不能直接横比。
- 0.2 s 是 10 帧级前馈；200 帧是 8.75 s，且显存 40.63 GB。

## 6. 能力与失败模式 (Capabilities & Failure Modes)

### 能做什么

| 能力 | 条件 | 证据 |
|------|------|------|
| 多视图相机/深度/点图 | 1–数百帧，静态/小运动 | Table 1/2/3 |
| 单视图重建 | 单图输入 | 论文 Appendix / demo |
| 前馈 + 可选 BA | 有 GPU；需要更高精度 | Table 1 的 +BA |
| 点跟踪 | 静态或小运动；query 点 | TAP-Vid 实验 |
| 作为下游 backbone | NVS / 动态跟踪微调 | 论文 4.6 / 附录 |
| 无序图像集合 | 不要求时序 | 架构设计 |

### 不能做什么

| 失败模式 | 原因 |
|----------|------|
| 鱼眼/全景 | 训练/相机模型是针孔；论文明确列为限制 |
| 极端输入旋转 | 论文明确列为限制 |
| 大幅非刚性变形 | 论文明确列为限制；小运动可以 |
| 超长序列 | 显存随帧数增长；200 帧已 40.63 GB |
| 在线 SLAM | 没有跟踪/回环/增量机制 |
| 米制尺度 | 训练按平均点距归一化；不是天然米制 |
| 透明/反光/天空 | 不确定性只能缓解；可用 mask 置 0/1 |
| 商用 | 原始 checkpoint 非商用；商业 checkpoint 需申请 |

### 6.1 隐含假设 (Hidden Assumptions)

1. **针孔相机 + 主点居中**：相机参数只有 FoV，没有主点/畸变。
2. **第 1 帧是参考帧**：相机/点图/深度都在第 1 帧坐标系；第 1 帧特殊 token 承担这个角色。
3. **静态或小运动**：大幅非刚性变形会失败。
4. **训练分布覆盖测试域**：极端视角、特殊传感器、鱼眼不在内。
5. **显存足够**：全局注意力是 $O(N^2)$ token 交互；长序列需要分块。
6. **不确定性可当置信度**：它是 aleatoric 估计，不是严格校准概率。
7. **前馈精度足够**：需要更高精度时仍需 BA，但 BA 会引入额外时间。

## 7. 与相关工作对比 (Comparison)

| 方法 | 表示/核心 | 多视图融合 | 需要相机 | 规模 | 适用场景 |
|------|-----------|-----------|----------|------|----------|
| COLMAP | 稀疏特征 + BA + MVS | 增量/全局 SfM | 需要（或先估） | 大 | 经典 SfM/MVS |
| DUSt3R | pointmap | 3D 全局对齐 | 不需要 | 小-中 | 无标定稠密重建 |
| MASt3R | pointmap + 匹配头 | 稀疏全局对齐 | 不需要 | 中 | 匹配、定位、SfM |
| **VGGT** | **多视图 Transformer** | **一次前向** | **不需要** | **中（1–200 帧）** | **多视图重建、跟踪、backbone** |
| Fast3R | 多视图一次前向 | 无 pairwise 对齐 | 不需要 | 大（1000+ 图） | 大规模前馈 |
| GLUEMAP | 前馈星图 + 全局 SfM | 运动平均 + BA | 不需要 | 大（万级） | 大规模、COLMAP 兼容 |

**面试 Tip**：当被问到“VGGT 和 DUSt3R/MASt3R 的区别”时，回答——DUSt3R/MASt3R 是**成对**推理 + 后处理对齐，VGGT 是**多视图**一次前向，直接把相机、深度、点图、跟踪一起输出；它用 alternating attention 控制多视图计算，用海量 3D 数据替代显式几何优化，速度快一个数量级，但显存随帧数增长，长序列仍需分块/BA。

## 8. 精读建议 (Reading Guide)

**值得精读原文的人**：
- 做多视图 3D 重建、SLAM/定位、3D 基础模型的人。
- 想把 VGGT 当 backbone 做 NVS / 跟踪 / 下游任务的人。
- 想理解“前馈多视图”与“经典 SfM/BA”边界的人。

**建议章节路径**：
- 先读 §3.2：alternating attention 和 token 设计。
- 再看 §3.3：相机头 / DPT 头 / 跟踪头。
- 再看 §3.4：多任务损失、数据、训练配置。
- 再看 §4.1–4.3：相机/深度/点图的数字与协议。
- 可跳 §2（相关工作）——除非写综述。

**不值得精读的理由**：
- 你只做两视图匹配/定位——MASt3R 更直接。
- 你需要在 Jetson/边缘部署——1.2B + 全局注意力太重。
- 你做鱼眼/全景/大幅非刚性——论文明确不支持。

## 9. 补充：面试高频 Q&A

**Q1：VGGT 为什么不需要 pairwise 全局对齐？**
A：它把所有帧的 token 放进同一个 Transformer，global attention 直接跨帧交换信息；相机/点图/深度一次输出，不再需要“成对预测再拼”。

**Q2：Alternating-Attention 解决什么问题？**
A：纯 global attention 计算/显存大且难优化；纯 frame-wise 不跨视图。交替做帧内和全局，兼顾跨视图推理与稳定性；消融显示比 cross-attention/global-only 好。

**Q3：为什么同时预测相机、深度、点图？它们不是冗余吗？**
A：是过完备的，但多任务监督提供额外梯度/正则；消融显示比只预测部分量更好。推理时还可以选 depth+camera 反投影，精度更高。

**Q4：VGGT 的输出是米制吗？**
A：训练时按平均点距归一化，输出尺度取决于训练数据；不是天然米制。需要米制时要用带 metric 标注的数据/后处理。

**Q5：VGGT 能处理多少帧？**
A：论文演示到 200 帧；显存 40.63 GB（336×518, H100）。更长序列要分块或换 VGGT-Long/VGGT-SLAM/Fast3R。

**Q6：VGGT 能替代 COLMAP 吗？**
A：在标准/中等规模、前馈精度足够的场景可以；大规模 SfM、需要稀疏 landmark/回环/BA 的场景，COLMAP/GLUEMAP 仍更成熟。VGGT+BA 是折中。

**Q7：VGGT 的跟踪头有什么用？**
A：输出任意 query 点在所有帧的对应，可用于点跟踪、动态场景微调、下游 NVS；它不假设时序顺序。

**Q8：VGGT 的主要限制？**
A：鱼眼/全景、极端旋转、大幅非刚性、显存、长序列、无在线回环；论文明确列了前三条。

## 10. 补充：复现清单

**最小命令**：

```bash
git clone https://github.com/facebookresearch/vggt.git
cd vggt
pip install -r requirements.txt

# Python 推理（README 示例）
python - <<'PY'
from vggt.models.vggt import VGGT
from vggt.utils.load_fn import load_and_preprocess_images
# model = VGGT.from_pretrained("facebook/VGGT-1B").to("cuda")
# images = load_and_preprocess_images([...]).to("cuda")
# predictions = model(images)
PY

# COLMAP demo（可选 BA）
python demo_colmap.py --scene_dir=/YOUR/SCENE_DIR/
python demo_colmap.py --scene_dir=/YOUR/SCENE_DIR/ --use_ba
```

**默认值/关键点**：

| 参数 | 默认/说明 |
|------|-----------|
| 输入分辨率 | 最大边 518（训练）；推理可调但显存/精度权衡 |
| 帧数 | 训练 2–24；推理 1–200（论文演示） |
| 模型 | VGGT-1B；商用用 VGGT-1B-Commercial |
| BA | 默认关；`--use_ba` 打开，精度更高但更慢 |
| 相机参数 | 9D：四元数 + 平移 + FoV；主点居中 |
| 反投影 | `unproject_depth_map_to_point_map`；相机解码 `pose_encoding_to_extri_intri` |
| 天空/反光 | 可把像素置 0/1 做简单 mask（README 建议） |

**常见坑**：
1. 帧数太多导致 OOM：200 帧 40.63 GB；先降分辨率/分块。
2. 把 0.2 s 当成所有帧数的延迟；实际随帧数增长。
3. 需要米制尺度却直接用 VGGT 输出。
4. 鱼眼/全景直接喂，结果不可用。
5. 商用误用原始 checkpoint（非商用）；要用 VGGT-1B-Commercial。
6. 大幅非刚性/极端旋转场景，论文明确会失败。

## 11. 补充：来源与核查

| 结论/数字 | 来源 | 核查方式 |
|-----------|------|----------|
| 1.2B 参数、24 层、DINOv2、518 | 论文 §3.2/§3.3 | PDF 原文 |
| 9D 相机参数 | 论文 §3.1 | PDF 原文 |
| 多任务损失、λ=0.05 | 论文 §3.4, Eq. (2) | PDF 原文 |
| 17 个数据集 | 论文 §3.4 | PDF 原文 |
| 160K iters、64×A100×9 天 | 论文 §3.3 Implementation Details | PDF 原文 |
| CO3Dv2/Re10K 85.3/88.2、+BA 93.5/91.8 | 论文 Table 1 | PDF 原文 |
| DTU 0.389/0.374/0.382 | 论文 Table 2 | PDF 原文 |
| ETH3D 0.873/0.482/0.677 | 论文 Table 3 | PDF 原文 |
| 运行时/显存 1–200 帧 | 论文 Table 9 | PDF 原文 |
| 消融 alternating attention | 论文 Table 5 | PDF 原文 |
| 跟踪 δavg 78.9→84.0 | 论文 Table 8 / 正文 | PDF 原文 |
| 限制（鱼眼/旋转/非刚性） | 论文 Limitations | PDF 原文 |
| 许可（商业 checkpoint） | 官方 README | 2026-11-06 |

**未在本文中当作事实的**：checkpoint 文件大小、不同硬件上的实际延迟、训练总 GPU-hours、商业 checkpoint 的具体条款。部署前请以官方 README/许可证为准。

---
[← Back to Theory](../README.md)

**关键引用**：
- 论文：https://arxiv.org/abs/2503.11651
- 代码：https://github.com/facebookresearch/vggt
- 项目页：https://vgg-t.github.io/
- VGGT-Ω：https://vggt-omega.github.io/
