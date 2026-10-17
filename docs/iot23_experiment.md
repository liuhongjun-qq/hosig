# IoT-23 单场景真实流量实验

## 实验范围

本实验于 2026-10-08 下载并处理 IoT-23 中的 `CTU-IoT-Malware-Capture-34-1`，场景说明为 Mirai。只下载**完整标注连接日志**和原始说明文件，没有下载整个 IoT-23、120 MB PCAP 或恶意程序。

官方数据集说明：

```text
https://www.stratosphereips.org/datasets-iot23
```

文件下载来源：

```text
https://mcfp.felk.cvut.cz/publicDatasets/IoT-23-Dataset/IndividualScenarios/CTU-IoT-Malware-Capture-34-1/bro/conn.log.labeled
https://mcfp.felk.cvut.cz/publicDatasets/IoT-23-Dataset/IndividualScenarios/CTU-IoT-Malware-Capture-34-1/README.md
```

保存位置：

```text
data/iot23/CTU-IoT-Malware-Capture-34-1/
  conn.log.labeled          原始标注日志，2,926,718 bytes
  README.source.md          原始场景说明
  download_manifest.json   URL、文件大小和本地 SHA256
  events.jsonl             转换后的标准事件
  events.metadata.json     转换来源、类别分布、时间含义和限制
```

原始日志 SHA256：

```text
d69e49b2aae8c1bd33286936531658202dec47d989f0439bad3f8be180467a6e
```

这是本次下载后计算的文件指纹，不是发布方签名或发布方校验值。源说明保留了使用授权提示；公开发布、商用或再分发前请核实数据集授权和署名要求。不要运行场景中的恶意程序。

## 实际数据

共 **23,145 条**连接记录，全部参与转换，无按标签抽样：

| 评估标签 | 条数 |
| --- | --- |
| Benign | 1,923 |
| C&C | 6,706 |
| DDoS | 14,394 |
| PartOfAHorizontalPortScan | 122 |

时间范围（UTC）：2018-12-21 14:50:16.870900 至 2018-12-22 14:50:13.942227，约 24 小时。

## 适配方法

- 时间：`ts`，真实连接首包时间；**不是告警到达时间**。
- IP：`id.orig_h` / `id.resp_h`。
- 标识：场景名 + `uid`。
- context 与 payload 代理：`proto`、`service`、`id.resp_p`、`conn_state`。
- 评估标签：优先详细标签（支持 `det_label`、`detailed-label`、`detailed_label`），缺失时退回粗标签。`--label-mode binary` 可切换为 Benign/Malicious。
- 不将标签、duration、ts、uid、字节数、包数输入内容编码。

原始日志有 **1,886 处相邻时间倒序**。默认采用稳定时间排序后离线回放，保留相同时间记录的源顺序，**并不是实际在线到达顺序重现**。可用 `--order source` 保留原日志顺序。转换的 `--limit` 在排序后应用，但本实验没有使用 limit。

payload 是结构字段组成的**内容代理**，不是真实应用 payload。因此本实验是“真实连接时间/IP + 日志内容代理”的方法适配，不是论文数据/原始 payload 的严格复现。

## 可重复执行的命令

在 `D:\encrypted_traffic\code` 的 PowerShell 中执行：

### 1. 下载

```powershell
.\scripts\download_iot23.ps1
```

已存在的日志不重复下载；按本次验证快照的 SHA256 检查。若 PowerShell 禁止执行本地脚本，可仅对当前进程使用 `Set-ExecutionPolicy -Scope Process Bypass`；这是可选的本地操作，不改变整机策略。首次下载需要网络权限。

### 2. 转换

```powershell
.\.venv\Scripts\python.exe -m hosig convert-iot23 --input data/iot23/CTU-IoT-Malware-Capture-34-1/conn.log.labeled --output data/iot23/CTU-IoT-Malware-Capture-34-1/events.jsonl --scenario CTU-IoT-Malware-Capture-34-1
```

转换器支持 Zeek 元数据头、标签列别名和部分 IoT-23 版本的空格合并标签尾列，检查列数/IP/有限时间，遇到损坏记录报错而不是悄悄丢弃。旁路 provenance 的 SHA256 会随输入写入 run/benchmark 报告；输入被改动而 metadata 未更新时拒绝实验。

### 3. 全量运行

```powershell
.\.venv\Scripts\python.exe -m hosig run --input data/iot23/CTU-IoT-Malware-Capture-34-1/events.jsonl --config configs/paper.json --site-id iot23_34_1 --output outputs/iot23_34_1/default
.\.venv\Scripts\python.exe -m hosig run --input data/iot23/CTU-IoT-Malware-Capture-34-1/events.jsonl --config configs/exploratory.json --site-id iot23_34_1 --output outputs/iot23_34_1/exploratory
```

两次均处理全量记录，batch_size=512，得到 46 个微批。第二条是预先存在的探索配置，没有在本次真实测试标签上重新调参，不应标为论文默认值。

### 4. 基线对照

```powershell
.\.venv\Scripts\python.exe -m hosig benchmark --input data/iot23/CTU-IoT-Malware-Capture-34-1/events.jsonl --config configs/paper.json --top-k-grid 5 10 20 40 --clients 1 --entity-protocol common-rff --output outputs/iot23_34_1/benchmark
```

- 单个真实采集场景，不用 round-robin 构造多个组织。
- 前 20%（4,629 条）作为验证前缀、后 80%（18,516 条）作为测试后缀。
- 当前 baseline 调参只使用验证前缀的首个微批 **512 条**；剩余验证前缀仍不参与测试。这是参考实验的资源限制，不是所有 4,629 条都参与了选参。
- baseline 参数选择不看标签；选择分数为 silhouette + modularity - noise_rate。
- Top-k = 5/10/20/40；4 方法 × 4 Top-k × 37 测试微批，**592 条评估记录**。
- 全部方法使用 common-rff 实体协议；不是论文默认的混合表示实体协议。

### 5. 汇总

```powershell
.\.venv\Scripts\python.exe scripts/summarize_iot23.py --events data/iot23/CTU-IoT-Malware-Capture-34-1/events.jsonl --results-root outputs/iot23_34_1
```

生成 `summary.json`、`summary.csv` 和 `stream_overview.png`，核对所有报告与输入 SHA256 一致。汇总平均值均为非加权微批均值，不是整体重聚类分数。

## 实验结果

### 全量流运行

| 配置 | 微批 | 总块数 | 图连通分量总数 | 正收益候选总数 | 多标签微批平均 ARI |
| --- | --- | --- | --- | --- | --- |
| 默认 | 46 | 1,762 | 1,762 | 0 | 0.0960 |
| 探索 | 46 | 2,017 | 1,767 | 22,761 | 0.0366 |

多标签微批共 21 个。其余微批类别单一，不能把这些微批的 ARI 平均值当作分类效果。总块数是各微批的块数之和，**不是全局攻击战役数**。

默认配置所有块均由连通分量边界产生，C(b) 未超过惩罚，对比边界检测没有触发。探索配置产生更多切点，但在这一场景上过分割更严重，不优于默认设置。

### 时间后缀测试的基线比较

下表只汇总每个设置的 **12 个多标签测试微批**；每个设置的总测试微批是 37 个。ARI 以 IoT-23 行为标签为参照，不是同源战役归因真值。

| Top-k | HoSig | HDBSCAN | Spectral | Louvain |
| --- | --- | --- | --- | --- |
| 5 | 0.0219 | 0.1234 | 0.0919 | 0.0181 |
| 10 | 0.0492 | 0.1234 | 0.0599 | 0.0298 |
| 20 | 0.0909 | 0.1234 | 0.0312 | 0.0448 |
| 40 | 0.1098 | 0.1234 | 0.0480 | 0.0639 |

HDBSCAN 不使用 kNN 图，因此当前设置下重复 Top-k 的结果相同。Spectral 的全部测试批都有断连图警告，已保存在 benchmark.json；不隐藏这一数值/结构限制。当前结果不支持 HoSig 优于全部基线。

完整 CH、silhouette、modularity、IIR 和噪声率在原始 CSV/JSON 中。全量流表与测试后缀表的数据范围和微批边界不同，不能直接交叉比较。

## 输出目录

```text
outputs/iot23_34_1/
  default/report.json
  default/signatures.jsonl
  default/local/...
  exploratory/report.json
  exploratory/signatures.jsonl
  benchmark/metrics.csv
  benchmark/benchmark.json
  benchmark/ch_comparison.png
  benchmark/boundary_clarity.png
  summary.json
  summary.csv
  stream_overview.png
```

## 验证和边界

- 52 项自动测试通过，包含 12 项 IoT-23 适配/汇总测试和一个真实大 epoch 的近时间分桶回归测试。
- 修复了大 Unix 时间戳与极小块时间跨度导致 histogram 无法建立 64 个有限桶的问题：使用块内相对时间分桶，不更改原始间隔。
- 单场景只有一台主要感染设备，类别分布不均，不足以证明跨组织迁移或归因正确性。
- 行为标签不是 campaign ground truth；原始 payload 和在线告警到达顺序未恢复。
- 没有在测试标签上调整 beta/eta 等参数，没有将标签或时间写入内容向量。
- 下一步可加入 PCAP/应用日志内容、多个独立场景和更完整验证集，再分析成本尺度及断连图过分割问题。
