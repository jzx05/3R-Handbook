# 3R Handbook · 电子书大纲

> 状态：v0.1 大纲。正文优先写在 `notes/`，本文件维护阅读顺序、章节目标和待办。
> 论文入口见 [papers/](../papers/README.md)；自动统计见 [README](../README.md)。

## 阅读路线

```text
问题定义
  → 3R 家族（DUSt3R → MASt3R → VGGT → π³ → MapAnything）
    → 与全局 SfM 融合（MASt3R-SfM / GLUEMAP / VidMap）
      → 在线 SLAM（MASt3R-SLAM / VGGT-SLAM / SLAM3R）
        → 评测、部署与失败模式
```

## 第 1 章 问题定义：从图像集合到几何

- 输入输出：图像 / 视频 → 相机参数、深度、点图（pointmap）、稠密几何
- 与经典 SfM / MVS 的边界：什么是“前馈”，什么仍然需要优化
- 核心术语：pointmap、Sim(3)、尺度歧义、star graph
- 写作入口：[glossary](../cheat-sheet/glossary.md)

## 第 2 章 3R 家族

- DUSt3R：成对 pointmap 回归与全局对齐 —— **已有一篇完整解析：[theory/3r/dust3r_dissection.md](../theory/3r/dust3r_dissection.md)**
- MASt3R：匹配头与稠密对应
- VGGT：多视图 transformer 与一次性前馈
- π³ / MapAnything / Fast3R / Spann3R / CUT3R：规模化、流式、度量尺度
- 待办：每个方法补一篇 `notes/` 深度笔记，统一比较输入、输出、显存与延迟

## 第 3 章 前馈 + 全局 SfM

- MASt3R-SfM：把成对匹配接回增量式 SfM
- GLUEMAP：全局 SfM 的运动平均 + 前馈星图 + 增强 BA
- VidMap：视频时序结构 + 全局 SfM + 深度先验
- 待办：写清“前馈负责什么、全局优化负责什么”的分工与失败边界

## 第 4 章 在线 SLAM

- 从离线重建到在线定位：关键帧、回环、尺度一致性
- MASt3R-SLAM / VGGT-SLAM / SLAM3R / VGGT-Long / EC3R-SLAM
- 与经典 VIO（VINS-Mono / ORB-SLAM3）的取舍
- 待办：整理一张“传感器 / 尺度 / 延迟 / 回环”对照表

## 第 5 章 评测与基准

- ETH3D、DTU、Tanks and Temples、ScanNet++、LaMAR、TUM RGB-D、7-Scenes
- 指标：AUC@5、AbsRel、δ<1.25、ATE、RPE
- 待办：明确每个数字的协议；预印本与会议版分开记录

## 第 6 章 部署与失败模式

- 显存、吞吐、长序列、动态场景、弱纹理、重复结构
- 尺度与 IMU/GNSS 融合、标定误差、回环误匹配
- 待办：从 GitHub Issues 和真实部署中提炼可复现的坑

## 写作约定

- 每个数字必须能在论文原文找到，并写清数据集、指标和对照。
- 作者声称与你的判断分开写。
- 预印本、会议版、代码版的结果不要混用。
- 模板见 [notes/_template.md](../notes/_template.md)。
