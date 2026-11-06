# MASt3R: 用 3D 几何 grounding 图像匹配 (Grounding Image Matching in 3D with MASt3R)

> ⚙️ 本文由 3R Handbook 解析流程维护 | 2026-11-06
>
> **论文**: Grounding Image Matching in 3D with MASt3R, ECCV 2024（arXiv 2406.09756v1）
> **链接**: https://arxiv.org/abs/2406.09756
> **代码**: https://github.com/naver/mast3r（CC BY-NC-SA 4.0，非商用）
> **核心定位**: 在 DUSt3R 的 pointmap 上增加局部特征头与匹配损失，把匹配从 2D 提升到 3D，并用快速互惠匹配把稠密匹配做成可用。

<!-- source: https://arxiv.org/abs/2406.09756 -->

## ⚡ 快速判断（30 秒读完这段就够了）

| 维度 | 判断 |
|------|------|
| 核心结论 | 匹配不该只在 2D 描述子空间做；把 DUSt3R 的 3D 几何先验和一组 24 维局部描述子结合起来，用 InfoNCE 训练，再配快速互惠匹配。Map-free 测试 VCRE AUC **0.933**、中位平移 **0.36 m**，比当时最好方法绝对提升约 **30 个点**；CO3Dv2 RTA@15 **91.9**，DTU Overall **0.374 mm**。 |
| 适合精读 | 做图像匹配、visual localization、SfM、SLAM 前端的人；想理解 MASt3R-SfM / VGGT / GLUEMAP 这条线的人；需要“极端视角变化下还能匹配”的工程方案的人。 |
| 可以跳过 | 只做纯 3D 重建、不关心匹配；只做生成/渲染；只关心传统 SIFT/SuperGlue 链路且不需要 3D 先验。 |
| 落地可行性 | 中高。权重开源、demo 易跑；但代码非商用、稠密匹配吃显存/时间、512 分辨率、metric 尺度依赖训练数据。 |
| 主要风险 | 动态场景、透明/反光、弱纹理、鱼眼/强畸变；metric 模式依赖 metric GT；高分辨率需要 coarse-to-fine；许可限制商用。 |

💡 **X-Ray 开场**
DUSt3R 已经证明 pointmap 在极端视角变化下很鲁棒，但“在 3D 点空间做最近邻”得到的匹配不够精确——回归有噪声，而且它从没为匹配训练过。MASt3R 的洞见是：**保留 DUSt3R 的 3D 几何先验，再额外回归一组局部描述子，用匹配损失直接监督“像素级正确”**。这样既有 3D 的鲁棒性，又有描述子匹配的精度；再用快速互惠匹配把 $O(W^2H^2)$ 的稠密匹配降到 $O(kWH)$，让它在真实任务里可用。

📍 **研究全景时间线**

```text
[2018-2022] SuperPoint / SuperGlue / LoFTR：2D 匹配 + 鲁棒估计
[2023.12]   DUSt3R：pointmap 回归，3D 最近邻匹配，鲁棒但不精确
[2024.06]   MASt3R ← 当前位置：3D grounded matching + 描述子头 + 快速互惠匹配
[2024.09]   MASt3R-SfM：把 MASt3R 接成完整无约束 SfM
[2025]      VGGT：多视图一次前向，匹配/相机/深度/点图统一
[2026]      GLUEMAP / VidMap：把前馈放进全局 SfM / 视频 SfM
← 局限：动态、鱼眼、弱纹理、metric 尺度、非商用许可
```

## 1. 核心架构/方法总览 (Overview / Architecture)

### 1.1 系统对比概览 (System Component Comparison)

| 组件 | 输入 | 输出 | 训练/推理差异 |
|------|------|------|---------------|
| 共享 ViT-L 编码器 | 单张 RGB（512 长边，patch 16） | 每图 token（512×384 时 768 个） | 初始化自 DUSt3R，继续训练 |
| 两个 ViT-B 解码器 | 两图 token + cross-attention | 两路解码 token | 与 DUSt3R 相同 |
| `Head3D` | 解码 token（拼 encoder skip） | pointmap $X$ + confidence $C$ | 3D 回归 + 置信度损失 |
| `Headdesc` | 解码 token（拼 encoder skip） | 24 维局部描述子 $D$ | 两层 MLP + GELU + L2 归一化 |
| 快速互惠匹配器 | 3D 点或描述子 | 互相最近邻匹配 | 3D 点用 KD-tree；24 维描述子用 FAISS |
| coarse-to-fine | 高分辨率图像 | 更精细的匹配 | 先降采样匹配，再在局部窗口细化 |
| MASt3R-SfM（下游） | 图像集合 | 稀疏/稠密重建 | 检索 + 成对匹配 + 稀疏全局对齐 |

### 1.2 关键机制 (Key Mechanism)

1. **3D grounded matching**：网络仍回归 DUSt3R 的 pointmap 和 confidence，但额外输出每像素 24 维描述子。匹配既可以在 3D 点空间做（鲁棒），也可以在描述子空间做（精确）。

2. **InfoNCE 匹配损失**：对 GT 对应像素 $(i,j)$，把描述子相似度 $s(i,j)=\exp(-\tau D_i^\top D_j)$ 当分类 logits，做双向 cross-entropy。它只奖励“命中正确像素”，不奖励“附近像素”，因此比 3D 回归更精确。

3. **Metric pointmaps**：DUSt3R 默认做尺度归一化；MASt3R 在 GT 是 metric 的数据上令 $z=\bar z$，直接回归 metric 点图。Map-free 这种需要米制定位的任务因此受益。

4. **快速互惠匹配**：不把所有像素两两比较。从 $k$ 个种子像素出发，迭代做“图 1 → 图 2 → 图 1”的最近邻，保留形成闭环的互惠匹配；复杂度从 $O(W^2H^2)$ 降到 $O(kWH)$。论文默认 $k=3000$，匹配加速约 **64×**，精度还略好。

5. **Coarse-to-fine**：512 分辨率下直接匹配高分辨率图会丢细节。先在降采样图上得到粗匹配，再在原图局部窗口里细化，兼顾速度与精度。

⚡ **Eureka Moment**：**匹配本质上是 3D 问题，但精度要靠 2D 描述子来补。** DUSt3R 的 3D 先验解决“视角变化大时还能不能匹配”，描述子 + InfoNCE 解决“匹配得准不准”；两者不是替代关系，而是互补。

### 1.3 信息流/架构图 (Flow / Diagram)

```text
训练时:
  I1, I2 ──► 共享 ViT-L ──► F1, F2
                 │
                 ▼
       Decoder1 ⇄ Decoder2（cross-attention）
          │            │
          ├─ Head3D ───┼─► X1,1, C1；X2,1, C2
          └─ Headdesc ─┴─► D1, D2（24 维，单位范数）
                 │
                 ▼
   L_total = L_conf(3D 回归 + 置信度) + β · L_match(InfoNCE)

推理时:
  I1, I2 ──► 网络 ──► X, C, D
           ├─ 3D 点 → KD-tree → 快速互惠匹配
           └─ 描述子 → FAISS → 快速互惠匹配
           ──► 匹配 → 本质矩阵 / PnP / 三角化 / SfM
```

## 2. 数学核心 (Math Core)

📌 **Napkin Formula**（一行抓住本质）：

```text
L_total = L_conf + β · L_match

L_match = − Σ_(i,j)∈M̂ [ log( s(i,j) / Σ_k s(k,j) ) + log( s(i,j) / Σ_k s(i,k) ) ]
s(i,j) = exp(−τ · D_i^T D_j)

# 快速互惠匹配：U_t → NN2(U_t) → NN1(·) = U_{t+1}，保留 U_t = U_{t+1} 的闭环
```

**目标**：在保持 DUSt3R 3D 几何鲁棒性的同时，让每个像素的描述子“只匹配正确的那个像素”，并把稠密匹配的复杂度降到可用。

**变量说明**：

| 符号 | 含义 |
|------|------|
| $D_i$ | 像素 $i$ 的 24 维局部描述子（单位范数） |
| $\hat M$ | GT 对应集合，由 GT pointmap 的互惠最近邻得到 |
| $\tau$ | InfoNCE 温度 |
| $\beta$ | 匹配损失权重，官方训练用 1 |
| $L_{conf}$ | DUSt3R 的置信度加权 3D 回归损失 |
| $k$ | 快速匹配的种子像素数，默认 3000 |

**直觉**：3D 回归损失是“L2 距离”，匹配对了但偏几个像素也能拿低 loss；InfoNCE 是“分类”，只有命中正确像素才被奖励。两者叠加，网络既学几何又学精确对应。

**补充：metric 模式**

当 GT pointmap 是 metric 时，令 $z=\bar z$，回归损失变成：

$$
\ell_{\text{regr}}(v,i) = \frac{\|X_i^{v,1} - \bar X_i^{v,1}\|}{\bar z}
$$

这样网络直接学米制尺度；否则仍用平均距离归一化，输出 up-to-scale。

## 3. 带数字走一遍：玩具例子 (Worked Example)

输入两张 512×384 图像，patch 16：

```text
Step 1: token 数
        512/16 = 32, 384/16 = 24 → 每图 768 个 token

Step 2: 输出张量
        pointmap: 512×384×3  (fp32 ≈ 2.25 MiB)
        confidence: 512×384  (fp32 ≈ 0.75 MiB)
        descriptor: 512×384×24 (fp32 ≈ 18.0 MiB)
        两张图描述子 ≈ 36 MiB

Step 3: 朴素稠密匹配
        196,608 × 196,608 ≈ 3.87e10 个像素对 → 不可接受

Step 4: 快速互惠匹配（k=3000）
        每轮 O(k·W·H) ≈ 3000 × 196,608 ≈ 5.9e8 次距离计算
        迭代几轮；论文报告 k=3000 时约 64× 加速

Step 5: 训练配置
        650k pairs/epoch × 35 epochs，batch 64
        descriptor dim = 24，β = 1，lr = 1e-4
        14 个数据集混合，其中 10 个有 metric GT
```

**关键数字**：

```text
Map-free test：VCRE AUC 0.933，中位平移 0.36 m，中位旋转 2.2°
CO3Dv2 10 帧：RRA@15 94.6 / RTA@15 91.9 / mAA(30) 81.8
RealEstate10K：mAA(30) 76.4
DTU：Acc 0.403 / Comp 0.344 / Overall 0.374 mm
checkpoint：MASt3R_ViTLarge_BaseDecoder_512_catmlpdpt_metric ≈ 2,627 MB
```

> 注意：Map-free 的 AUC 和误差来自论文 Table 2；不同深度来源（DPT-KITTI vs MASt3R metric）对应不同行，引用时要写清。

## 4. 工程视角 (Engineering View)

| 维度 | 数值/权衡 | 工程含义 |
|------|-----------|----------|
| 模型规模 | ViT-L 编码器 + ViT-B 解码器 + 3D 头 + 24 维描述子头 | checkpoint 约 2.6 GB；需要 GPU |
| 输入分辨率 | 512 长边，patch 16 | 高分辨率靠 coarse-to-fine，不是直接喂大图 |
| 描述子维度 | 24 | 低维，适合 FAISS；比高维描述子省内存 |
| 匹配复杂度 | 朴素 $O(W^2H^2)$；快速 $O(kWH)$ | k=3000 时约 64× 加速 |
| 推理延迟 | 论文未报告端到端每对延迟 | 不能拿“匹配加速 64×”当端到端延迟 |
| 训练成本 | 650k pairs/epoch × 35 epochs，batch 64 | 论文未报告 GPU 数量/总 GPU-hours |
| 许可 | CC BY-NC-SA 4.0 | 非商用；商用需评估替代 |
| 尺度 | metric 模式依赖 metric GT | 没有 metric 训练数据时仍 up-to-scale |

**部署约束**：
- 必须 GPU；2.6 GB 权重 + 描述子/点图缓存，显存随图像对数和分辨率增长。
- 高分辨率图像需要 coarse-to-fine；直接降采样会丢小目标匹配。
- 稠密匹配的数量很大，下游 PnP/SfM 需要 RANSAC 或几何验证。
- 代码非商用；Map-free 数据集许可更严格（README 有提示）。
- 动态/透明/鱼眼不在模型假设内。

**代码地图**（官方 repo 结构；行号未核，按文件定位）：

| 功能 | 文件 |
|------|------|
| 网络与双头 | `mast3r/model.py` |
| 回归/匹配损失 | `mast3r/losses.py` |
| 快速互惠匹配 | `mast3r/fast_nn.py` |
| 稀疏全局对齐（MASt3R-SfM） | `mast3r/cloud_opt/sparse_global_alignment.py` |
| demo / 检索 + SfM | `mast3r/demo.py`（README 指向 `demo.py#L142`） |
| 可视化定位 | `visloc.py` |

## 5. 数据与评测 (Data & Eval)

### 5.1 数据组成

训练使用 **14 个数据集**（论文 4.1），其中 10 个有 metric GT：

| 数据集 | 场景类型 | 角色 |
|--------|----------|------|
| Habitat | 合成室内 | 合成多视图 |
| ARKitScenes | 真实室内 RGB-D | 室内深度/位姿 |
| Blended MVS | 合成 + 真实 MVS | 多视图立体 |
| MegaDepth | 互联网照片 + SfM | 室外/地标 |
| Static Scenes 3D | 静态场景 | 静态几何 |
| ScanNet++ | 真实室内 RGB-D | 室内高精度 |
| CO3D-v2 | 物体中心视频 | 物体级多视图 |
| Waymo | 自动驾驶 | 室外大场景 |
| Map-free | 单参考图定位 | metric 定位 |
| WildRgb | 真实物体视频 | 物体级 |
| VirtualKitti | 合成驾驶 | 合成室外 |
| Unreal4K | 合成 | 高分辨率合成 |
| TartanAir | 合成 | 多样场景 |
| internal | 内部数据 | 补充 |

### 5.2 评测设置

- **Map-free localization**：单参考图、metric pose；VCRE AUC、中位平移/旋转、pose accuracy。
- **相对位姿**：CO3Dv2 / RealEstate10K，10 帧，45 对；RRA@15 / RTA@15 / mAA(30)。
- **Visual localization**：Aachen Day-Night（Day/Night）、InLoc（DUC1/DUC2）；top1/top20/top40 检索图。
- **DTU MVS**：zero-shot，Chamfer Acc/Comp/Overall。
- **匹配消融**：Map-free validation，比较 3D 点匹配 vs 描述子匹配、单损失 vs 双损失、DPT 深度 vs MASt3R metric 深度。

### 5.3 关键结果

**Map-free test（Table 2）**

| 配置 | VCRE AUC ↑ | 中位平移 ↓ | 中位旋转 ↓ | Pose AUC ↑ |
|------|-----------:|-----------:|-----------:|-----------:|
| LoFTR+KBR（当时最好） | 0.634 | 2.23 m | 37.8° | 0.295 |
| MASt3R（DPT 深度） | 0.726 | 0.80 m | 2.2° | 0.456 |
| **MASt3R（auto）** | **0.933** | **0.36 m** | **2.2°** | **0.740** |
| MASt3R（direct reg.） | 0.941 | 0.42 m | 3.1° | 0.777 |

**多视图相对位姿（CO3Dv2 / RealEstate10K，10 帧；Table 3）**

| 方法 | CO3Dv2 RRA@15 ↑ | CO3Dv2 RTA@15 ↑ | CO3Dv2 mAA(30) ↑ | RealEstate mAA(30) ↑ |
|------|----------------:|----------------:|-----------------:|---------------------:|
| DUSt3R | 94.3 | 88.4 | 77.2 | 61.2 |
| **MASt3R** | **94.6** | **91.9** | **81.8** | **76.4** |

**DTU（Table 3 右）**

| 方法 | Acc ↓ | Comp ↓ | Overall ↓ |
|------|------:|-------:|----------:|
| DUSt3R | 2.677 | 0.805 | 1.741 |
| **MASt3R** | **0.403** | **0.344** | **0.374** |

**Visual localization（Table 4）**

| 数据集 | 配置 | 0.25m/2° | 0.5m/5° | 5m/10° |
|--------|------|---------:|--------:|-------:|
| Aachen Day | top20 | 83.4 | 95.3 | 99.4 |
| Aachen Night | top20 | 76.4 | 91.6 | 100 |
| InLoc DUC1 | top20 | 55.1 | 77.8 | 90.4 |
| InLoc DUC2 | top20 | 71.0 | 84.7 | 89.3 |

> InLoc 的阈值是 0.25m/10°、0.5m/10°、1m/10°；上表列的是 DUC1/DUC2 的对应三档。

**消融（Table 1 / 正文）**

| 消融 | 结论 |
|------|------|
| 3D 点匹配 vs 描述子匹配 | 描述子明显更准（II vs IV） |
| 只用匹配损失 vs 3D + 匹配 | 只用匹配损失时旋转误差变差（10.8° vs 3.0°），3D grounding 关键 |
| DPT 深度 vs MASt3R metric 深度 | metric 深度大幅提升定位/尺度 |
| 快速匹配 k 值 | k=3000 约 64× 加速，精度反而略好 |

**口径提醒**：
- Map-free 的 “auto” 用 MASt3R 自己的 metric 深度；“direct reg.” 不用匹配，直接用 pointmap + PnP。
- DTU 是 zero-shot，但 MASt3R 用 GT 相机三角化匹配（与 DUSt3R 的设定不同），不能直接说“全面碾压”。
- Aachen/InLoc 的数字依赖检索 top-k；top1 与 top20 差距很大。

## 6. 能力与失败模式 (Capabilities & Failure Modes)

### 能做什么

| 能力 | 条件 | 证据 |
|------|------|------|
| 极端视角变化下的稠密匹配 | 有重叠、静态场景 | Map-free、InLoc 定性/定量 |
| Metric 单参考图定位 | 训练含 metric 数据 | Map-free AUC 0.933、0.36 m |
| 相对位姿 | 成对图像 | CO3Dv2 RTA 91.9 |
| 无标定 SfM / MVS | 图像集合 + 下游对齐 | MASt3R-SfM、DTU 0.374 mm |
| 相机标定 | 从 pointmap 估焦距 | 论文 Sec. 3 / 实验 |
| 高分辨率匹配 | coarse-to-fine | 论文 Sec. 3.4 |

### 不能做什么

| 失败模式 | 原因 |
|----------|------|
| 动态场景 | 假设静态、每像素单点 |
| 透明/反光/天空 | 没有唯一 3D 点；描述子也可能匹配到错误层 |
| 鱼眼/强畸变 | 假设针孔、主点居中 |
| 弱纹理/重复结构 | 描述子区分度不足；InfoNCE 也会被重复结构欺骗 |
| 无 metric 尺度 | metric 模式依赖 metric GT；否则仍 up-to-scale |
| 高分辨率直接匹配 | 512 分辨率限制；需要 coarse-to-fine |
| 大规模图像集合 | 成对匹配 $O(N^2)$，需要检索/稀疏图 |
| 商用 | CC BY-NC-SA 4.0 |

### 6.1 隐含假设 (Hidden Assumptions)

1. **静态场景 + 单层几何**：运动物体会破坏 pointmap 和匹配。
2. **针孔相机**：鱼眼/全景不适用。
3. **GT 对应可从 3D pointmap 得到**：训练依赖 GT 3D，标注质量影响匹配监督。
4. **metric 数据足够**：metric 模式只在有 metric GT 的数据上有效。
5. **检索能给出好的候选对**：Aachen/InLoc 的 top-k 直接影响结果。
6. **描述子 24 维足够**：低维省内存，但可能限制极端外观变化下的区分度。
7. **匹配数量可控**：快速匹配只保留互惠子集，召回率不是 100%。

## 7. 与相关工作对比 (Comparison)

| 方法 | 表示/核心 | 匹配方式 | 需要相机 | 尺度 | 适用场景 |
|------|-----------|----------|----------|------|----------|
| SuperGlue / LoFTR | 2D 关键点/稠密描述子 | 2D 描述子 + 注意力 | 不需要 | up-to-scale | 传统匹配、定位前端 |
| DUSt3R | pointmap | 3D 最近邻 | 不需要 | up-to-scale | 稠密重建，匹配不够精确 |
| **MASt3R** | **pointmap + 24 维描述子** | **3D/描述子 + 快速互惠** | **不需要** | **可 metric** | **匹配、定位、SfM、MVS** |
| MASt3R-SfM | MASt3R + 稀疏全局对齐 | 成对匹配 + 全局优化 | 不需要 | 可 metric | 无约束 SfM |
| VGGT | 多视图 Transformer | 一次前向 + 跟踪头 | 不需要 | 可 metric（训练数据） | 多视图重建、跟踪 |

**面试 Tip**：当被问到“MASt3R 和 DUSt3R 的区别”时，回答——DUSt3R 用 3D 点做最近邻匹配，鲁棒但精度受回归噪声限制；MASt3R 额外回归 24 维描述子，用 InfoNCE 直接监督像素级正确性，并加快速互惠匹配解决稠密匹配的复杂度。一句话：**DUSt3R 让匹配“能用”，MASt3R 让匹配“好用且快”**。

## 8. 精读建议 (Reading Guide)

**值得精读原文的人**：
- 做 visual localization / SfM / SLAM 前端、需要极端视角匹配的人。
- 想理解“3D 几何 + 2D 描述子”如何互补的人。
- 要复现 MASt3R-SfM 或以此为 baseline 的人。

**建议章节路径**：
- 先读 §3.2：匹配头 + InfoNCE 损失。
- 再看 §3.3：快速互惠匹配的迭代与复杂度。
- 再看 §3.4：coarse-to-fine。
- 再看 §4.2–4.4：Map-free / 相对位姿 / 定位的实验口径。
- 可跳 §2（相关工作）——除非写综述。

**不值得精读的理由**：
- 你只做稠密重建、不做匹配——DUSt3R/VGGT 更直接。
- 你已经用 VGGT 做多视图——MASt3R 的价值主要在成对匹配/定位。
- 你需要商用——许可会挡住。

## 9. 补充：面试高频 Q&A

**Q1：MASt3R 为什么还要保留 DUSt3R 的 3D 回归？**
A：3D 回归提供跨视图几何先验和鲁棒性；只用描述子匹配在极端视角/弱纹理下会崩。两者互补。

**Q2：InfoNCE 和普通描述子对比损失有什么区别？**
A：InfoNCE 把匹配当“像素分类”，双向 softmax 归一化，只有正确像素被奖励；普通对比损失可能只要求“相对更近”，精度不够。

**Q3：快速互惠匹配为什么能加速？**
A：不是所有像素两两比较，而是从 $k$ 个种子出发迭代 NN，只保留闭环互惠匹配；复杂度 $O(kWH)$，k=3000 时约 64×。

**Q4：metric 模式怎么工作？**
A：当 GT pointmap 是 metric 时，不做尺度归一化（$z=\bar z$），直接回归米制点图；否则用平均距离归一化，输出 up-to-scale。

**Q5：coarse-to-fine 解决什么问题？**
A：512 分辨率无法直接处理高分辨率图；先降采样得到粗匹配，再在原图局部窗口细化，保留小目标/细节。

**Q6：MASt3R 的匹配一定比 SuperGlue/LoFTR 好吗？**
A：在极端视角、弱纹理、低重叠上通常更好；在标准短基线、纹理丰富场景，传统方法可能更快更准。要看场景和延迟预算。

**Q7：为什么 Map-free 提升这么大？**
A：一是 metric depth，二是 3D grounded matching 在极端视角下仍能匹配；两者叠加，中位平移从 ~2m 降到 0.36m。

**Q8：能直接拿 MASt3R 做 SLAM 吗？**
A：它能做前端匹配/定位，但没有跟踪、回环、后端优化；需要 MASt3R-SLAM / VGGT-SLAM 这类系统。

## 10. 补充：复现清单

**最小命令**：

```bash
git clone --recursive https://github.com/naver/mast3r
cd mast3r
# 按 README 创建环境并安装依赖
mkdir -p checkpoints/
wget https://download.europe.naverlabs.com/ComputerVision/MASt3R/MASt3R_ViTLarge_BaseDecoder_512_catmlpdpt_metric.pth -P checkpoints/
python3 demo.py --model_name MASt3R_ViTLarge_BaseDecoder_512_catmlpdpt_metric
```

**默认值**：

| 参数 | 默认 | 说明 |
|------|------|------|
| `model_name` | `MASt3R_ViTLarge_BaseDecoder_512_catmlpdpt_metric` | 512 分辨率 metric 模型 |
| `image_size` | 512 | 与 checkpoint 匹配 |
| `device` | `cuda` | 需要 GPU |
| `descriptor dim` | 24 | 模型内部 |
| 快速匹配 $k$ | 3000 | 论文默认 |
| 匹配损失 $\beta$ | 1 | 训练 |
| coarse-to-fine | 可选 | 高分辨率定位时开 |

**常见坑**：
1. 忘记 `--retrieval_model` 或检索文件，demo 的配对策略退化成穷举/顺序。
2. 高分辨率图不跑 coarse-to-fine，匹配点变少。
3. 把 “64× 匹配加速” 当成端到端 64×。
4. 用非 metric 模型做米制定位，尺度不对。
5. 忽略 Map-free 数据集许可。
6. 代码 CC BY-NC-SA 4.0，商用需注意。

## 11. 补充：来源与核查

| 结论/数字 | 来源 | 核查方式 |
|-----------|------|----------|
| 匹配头 + InfoNCE | 论文 §3.2, Eq. (8)–(12) | PDF 原文 |
| 快速互惠匹配 + 复杂度 | 论文 §3.3 | PDF 原文 |
| coarse-to-fine | 论文 §3.4 | PDF 原文 |
| 14 个数据集 | 论文 §4.1 | PDF 原文 |
| 650k pairs/epoch, 35 epochs, batch 64 | 论文 Appendix Table 6 | PDF 原文 |
| Map-free AUC 0.933 / 0.36m / 2.2° | 论文 Table 2 | PDF 原文 |
| CO3Dv2 94.6/91.9/81.8；RealEstate 76.4 | 论文 Table 3 | PDF 原文 |
| DTU 0.403/0.344/0.374 | 论文 Table 3 | PDF 原文 |
| Aachen/InLoc 数字 | 论文 Table 4 | PDF 原文 |
| checkpoint 2,627 MB | 官方下载链接 Content-Length | 2026-11-06 实测 |
| 许可 CC BY-NC-SA 4.0 | 官方 README | 2026-11-06 |

**未在本文中当作事实的**：端到端每对推理延迟、训练总 GPU-hours、描述子头参数量、不同硬件上的实际速度。这些论文未报告或本文未核实，部署前请自测。

---
[← Back to Theory](../README.md)

**关键引用**：
- 论文：https://arxiv.org/abs/2406.09756
- 代码：https://github.com/naver/mast3r
- MASt3R-SfM：https://arxiv.org/abs/2409.19152
- DUSt3R：https://arxiv.org/abs/2312.14132
