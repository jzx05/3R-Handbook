# 术语表

> 人工维护。定义尽量给出来源或论文入口；有争议的术语保留不同用法。

## 核心概念

| 术语 | 含义 | 备注 |
|---|---|---|
| **3R** | 本手册指 **3D Geometric Foundation Models**（3D 几何基础模型），即从图像直接回归相机/几何的基础模型 | 不是经典的 “reconstruction / recognition / rendering” 三分法 |
| **Pointmap** | 每个像素对应一个 3D 点，通常表示在同一参考坐标系下 | DUSt3R 的核心输出；与 depth map 的区别是带跨视图坐标系 |
| **Feed-forward** | 一次前向推理直接输出几何，不需要针对每个场景做迭代优化 | 有些方法仍含 test-time training / 后处理 |
| **Star graph** | 一个参考视图连接多个目标视图的推理图 | GLUEMAP 用星图做局部前馈推理，避免 O(n²) |
| **Sim(3)** | 相似变换：旋转 + 平移 + 尺度 | 多视图对齐、SLAM 尺度校正常用 |
| **Scale ambiguity** | 单目重建只能恢复到未知尺度 | 与 IMU / GNSS / 度量深度融合时需显式处理 |
| **Bundle adjustment (BA)** | 联合优化相机位姿与 3D 结构 | 经典后端；GLUEMAP 把前馈“虚拟 track”并入 BA |
| **Motion averaging** | 从相对位姿恢复全局位姿的优化步骤 | 全局 SfM 的核心阶段之一 |

## 任务与系统

| 术语 | 含义 |
|---|---|
| **SfM** | Structure-from-Motion，从图像恢复相机与稀疏/稠密结构 |
| **Global SfM** | 先做全局运动平均，再做 BA；对大规模更稳 |
| **Incremental SfM** | 逐张加入图像、反复三角化与 BA；COLMAP 经典路线 |
| **MVS** | Multi-View Stereo，多视图立体匹配，输出稠密点云/深度 |
| **SLAM** | Simultaneous Localization and Mapping，在线定位与建图 |
| **VIO** | Visual-Inertial Odometry，视觉 + IMU 里程计 |
| **Loop closure** | 回环检测，消除长序列漂移 |
| **Place recognition** | 场景识别，回环检测的检索前端 |
| **NVS** | Novel View Synthesis，新视角合成 |
| **3DGS** | 3D Gaussian Splatting，显式高斯表示与可微光栅化 |

## 代表性系统

| 名称 | 一句话 |
|---|---|
| **DUSt3R** | 成对图像回归 pointmap，再全局对齐；把 3D 重建变成前馈问题 |
| **MASt3R** | 在 DUSt3R 上加入匹配头，输出稠密对应，服务 SfM / 定位 |
| **MASt3R-SfM** | 用 MASt3R 的匹配与点图初始化，接回无约束 SfM |
| **VGGT** | 多视图 transformer，一次前向输出相机、深度、点图 |
| **GLUEMAP** | 全局 SfM 框架，把前馈星图推理、运动平均与增强 BA 组合起来 |
| **VidMap** | 视频 SfM，把 SLAM 式时序结构与全局 SfM 优化结合 |
| **MASt3R-SLAM** | 基于 MASt3R 先验的实时稠密单目 SLAM |
| **VGGT-SLAM** | 在 SL(4) 流形上优化 VGGT 输出的稠密 RGB SLAM |

## 常用基准

| 基准 | 主要用途 |
|---|---|
| **ETH3D** | 多视图重建 / 位姿精度，AUC@5 常用 |
| **DTU** | 多视图立体稠密重建 |
| **Tanks and Temples** | 大规模场景重建 |
| **ScanNet++** | 室内 RGB-D / 语义 / 重建 |
| **LaMAR** | 室内外定位与建图 |
| **TUM RGB-D** | RGB-D SLAM 轨迹精度（ATE/RPE） |
| **7-Scenes** | 室内重定位与位姿估计 |
