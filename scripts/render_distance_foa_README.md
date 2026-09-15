# 固定麦克风、多距离 FOA 渲染

## 直接运行

项目专用环境为 `repo/.venv`，提示名称为 `spatial-audio-distance`，使用 Python 3.13.5。在项目根目录激活并运行：

```bash
source repo/.venv/bin/activate
python3 repo/scripts/render_distance_foa.py
```

运行后会逐场景显示当前数据支持的最长水平直线距离，以及可生成的距离，并询问：

```text
Longest horizontal straight-line distance supported by the data: 3.000 m (not the geometric maximum length of the room)
Available distances (m): 1.000, 2.000, 3.000
Which distances should be rendered? Enter e.g. 1 3 or 1,2,3; press Enter for all; q to quit:
```

输入 `1 3` 只生成 1 米和 3 米，支持空格、英文或中文逗号分隔。回车或 `all` 选择全部。只能选择已有 RIR 的距离，不插值生成任意距离；无效输入会重新询问。所有场景选择完成后才创建输出目录，输入 `q` 或按 Ctrl+C 可在选择阶段取消。

批量运行可用 `--distances 1 3` 指定距离，或 `--all-distances` 选择全部以跳过询问；这两个参数不能同时使用。指定距离会应用到每个选中的场景。`--plan-only` 同样支持上述交互和参数，仅保存选点结果。

依赖：numpy、scipy、networkx，已安装版本固定在根目录 `requirements.txt`。重建环境时使用 Python 3.13：

```bash
python3.13 -m venv --prompt spatial-audio-distance repo/.venv
source repo/.venv/bin/activate
python -m pip install -r requirements.txt
```

使用 `deactivate` 退出环境。
脚本直接加载仓库里的 SpatialScaper `spatialize.py` 并调用 `spatialize()` 的静态单 RIR 卷积分支，无需安装完整的 SOFA/DCASE 依赖。

- 声源默认：`dataset/source-test-0915`，递归读取 WAV。
- RIR/坐标默认：`dataset/soundspaces_1_0`。
- 输出默认：项目内的 `outputs/run-MMDD-N`，例如 `outputs/run-0915-1`。日期使用本机当天日期，序号在当天已有最大序号上加 1。程序会打印完整输出路径；`--output` 可指定自定义目录，已有目录仍拒绝覆盖。
- 每个声源的每个距离输出一份 4 通道、16 kHz、float32 WAV，附总表 `manifest.json`。
- 立体声素材先对左右声道取平均，作为一个点声源；整段重采样到 RIR 采样率。

再次运行会自动创建当天的新序号目录，也可指定自定义目录：

```bash
python3 repo/scripts/render_distance_foa.py --output outputs/my_foa_run
```

只查看选点，不渲染：

```bash
python3 repo/scripts/render_distance_foa.py --plan-only
```

选择场景、麦克风节点或声源文件夹：

```bash
python3 repo/scripts/render_distance_foa.py --scene GdvgFV5R1Z5 --receiver 4 --sources dataset/source-test-0915 --output outputs/my_foa
```

## 本次选点

GdvgFV5R1Z5：固定接收节点 4；沿同一个方向取节点 6、9、15，水平距离依次为 1、2、3 米。精确三维距离、坐标和每份音频的原始 RIR 路径见 manifest。

HxpKQynjfin：连通图为空，按用户要求跳过，不生成未经连通图支持的路线。

算法遍历所有接收点和水平射线，要求点到直线和高度偏差不超过 2 cm，相邻采样点之间必须有图边，且每个接收点/声源组合都有 RIR。选择最长的连续采样链。距离用真实坐标计算，不把最近点强行标成整数距离。

**“最长”限定为现有连通图和 RIR 支持的水平直线采样链。** 没有场景网格的射线检测，无法证明几何上绝对最长的无遮挡直线；导航图边也不是声学视线的严格证明。场景可能包含多个实际房间。

## FOA、音量和时间约定

原始文件有 9 通道。取前四个球谐分量，并将一阶通道除以 sqrt(3)，按 ACN/N3D → ACN/SN3D 输出（W,Y,Z,X）。

**输入约定依据是本地 RIR 的数值检查，不是 WAV 内的声明：** 轴向点对 `0_2`、`2_0`、`2_3`、`3_2` 的直达分量呈现约 ±sqrt(3) 的一阶/W 比值，垂直分量位于索引 2，符合 ACN/N3D。保留数据原有方向坐标和符号，没有额外旋转到面向声源。若后续权威数据说明确认输入是 SN3D，可用 `--rir-normalization sn3d` 关闭缩放。普通 WAV 不含完整 Ambisonic 声道标签，导入音频软件时按上述约定配置；四通道 FOA 并非耳机双耳预览。

不使用 Scaper 高层接口的 RIR 能量归一化或事件 SNR 重设。先原样卷积，再对同一场景全部素材、全部距离施加同一个防削波衰减（只衰减，不放大；峰值最多 0.95），记录在 manifest。这保留了原始素材/RIR 中已有的相对电平差异，不等于绝对声压校准，也不保证反射房间内响度严格随距离单调下降。

补零保留完整混响尾音，输出样本数为重采样后声源长度 + RIR 长度 − 1。保留原始 RIR 时间起点；本地部分 RIR 直达成分位于开头，因此不宣称保留了真实传播延时，也不额外添加 distance / c 延时。

官方数据目录说明（接收点/声源命名）：https://github.com/facebookresearch/sound-spaces/blob/main/soundspaces/README.md
