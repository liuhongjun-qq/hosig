# HoSig-Align I 独立方法复现

依据用户提供的 **Yao 等，2026，HoSig-Align I: Edge-Native Threat Attribution using Homology Blocks in IoT-Pervasive Networks** 论文 Markdown 实现。

**不是作者官方代码，不声称已复现论文表格数值。** 当前完成：算法主流程、流式微批接口、三种基线、指标、跨块对齐与超图、可追溯参数和自动测试。原论文真实告警数据未提供；参数未公开、公式解释不一致等问题见 `docs/reproduction_notes.md`。

## 1. 快速运行

当前目录已创建 `.venv` 并安装依赖。Windows PowerShell 下无需激活环境：

```powershell
.\.venv\Scripts\python.exe -m hosig demo --output outputs/demo
.\.venv\Scripts\python.exe -m pytest -q
```

新机器建议使用本次验证的 Python 3.13，安装锁定版本：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.\.venv\Scripts\python.exe -m hosig demo --output outputs/demo
```

`pyproject.toml` 定义依赖范围，`requirements-lock.txt` 记录实际运行版本。使用 CPU，无需 PyTorch/CUDA/GPU。本实现为 Python/NumPy/SciPy 参考版本，未实现作者的 C++ 和多线程森林优化。

### 默认参数的实际表现

`configs/paper.json` 保留论文明确给出的实验默认值，未公开的值使用显式复现假设。它不是作者发布的原始配置。

在当前 768 条合成遥测上，默认 `segmentation_beta=0.8` 惩罚较大，两个微批均没有正收益边界，得到单一块。这是当前公式与参数的实际输出，不会为展示效果隐式改变公式。请检查 `report.json` 的 `positive_gain_candidates`、`n_components` 和 `segmentation_penalty`。

观察边界检测可使用**非论文参数的探索配置**：

```powershell
.\.venv\Scripts\python.exe -m hosig demo --config configs/exploratory.json --output outputs/exploratory
```

它改变时间衰减下限、检测窗口、最小块长度和分段惩罚，仅用于参数敏感性探索，不能标为论文默认结果。最终应在独立验证数据上选参。

## 2. 算法对应

| 论文步骤 | 实现文件 | 内容 |
| --- | --- | --- |
| 式 (1)–(3) | `hosig/encoding.py` | IP 网段 hash、2048 维 hashed BOW、随机投影、GELU、LayerNorm；时间和标签不参与编码 |
| 式 (4) | `hosig/forest.py` | 随机划分森林、共同叶频率；不是 IsolationForest 异常分数 |
| 式 (5)–(6) | `hosig/graph.py` | 双半衰期衰减、median/MAD 校准、mutual Top-k、CSR 稀疏图 |
| 谱排序 | `hosig/graph.py` | 归一化 Laplacian、Fiedler 向量；断连图按分量处理 |
| 式 (7)–(8) | `hosig/segmentation.py` | RFF 分布对比 + 图连接对比，带最小间隔的精确动态规划 |
| 式 (9) | `hosig/signatures.py`、`hosig/sketches.py` | RFF 均值、时间直方图、CMS、HLL、边界比率、信息增益特征 |
| 式 (10) | `hosig/alignment.py` | 原型 L2、时间 DTW、CMS bucket 分布的 JS 距离 |
| 式 (11)–(13) | `hosig/alignment.py` | 初始层次超图、代表块、增量合并、低凝聚性拆分 |
| 实验 | `hosig/baselines.py`、`hosig/experiments.py` | HDBSCAN、Spectral、Louvain；验证前缀调参后评估 |
| 指标 | `hosig/metrics.py` | CH、标准 silhouette、modularity、IIR_k、IIR_norm；额外 ARI/NMI |

参数/偏差见 `docs/reproduction_notes.md`，数据接口见 `docs/data_format.md`。

## 3. 自己的遥测数据

推荐 JSONL，每行一个事件，或包含同名列的 CSV：

```json
{"event_id":"e001","timestamp":"2025-01-06T08:00:00+08:00","src_ip":"192.168.1.10","dst_ip":"10.1.2.20","payload":"GET /device/admin exploit probe","context":{"service":"http","sensor":"soc-a"},"label":"optional_evaluation_only"}
```

```powershell
.\.venv\Scripts\python.exe -m hosig run --input data/events.jsonl --output outputs/my_stream --site-id soc_a --save-arrays
```

时间可为 Unix 秒或带时区 ISO 8601。`label` 仅供事后评估，不参与聚类或参数选择。按输入顺序截取微批，不按标签分组或打乱原始流。跨批关系通过签名/超图表达，不做事件级跨批合并。

## 4. 本地 CSV 代理实验

本地文件 `../dataset/archive/train_test_network.csv` 包含 IP、协议/DNS/HTTP/TLS 等结构字段和 `label/type`，但**没有事件时间戳和原始 payload**。不能把 duration 当到达时间，不能把标签当 payload。

```powershell
.\.venv\Scripts\python.exe -m hosig run --input ../dataset/archive/train_test_network.csv --format network-csv --proxy-interval 72 --limit 512 --output outputs/local_csv_smoke
```

- 时间：第 i 行为 `i × 72` 秒，是人为代理时间。
- 内容：选定协议、服务、连接状态及 DNS/HTTP/TLS 等非标签列构造代理文本。
- `type/label` 只供评估，duration/时间间隔/字节统计不进入代理文本。
- 无 `--proxy-interval` 时拒绝运行，避免悄悄制造时间。
- `--limit` 只取文件前缀，可能仅有一种标签，不为提高分数重排文件。
- 此模式仅用于适配和流程验证，**不能验证论文真实时间衰减、突发性或跨组织结论**。

## 5. 基线与指标图

```powershell
.\.venv\Scripts\python.exe -m hosig generate --output data/synthetic.jsonl --events 768
.\.venv\Scripts\python.exe -m hosig benchmark --input data/synthetic.jsonl --top-k-grid 5 10 20 40 --clients 2 4 8 --output outputs/benchmark
```

每个模拟站点的前 20% 为验证前缀，后 80% 用于评估。基线以 silhouette + modularity − noise_rate 选参，不读取标签。站点是 round-robin 人工划分，不是论文真实组织。HoSig 使用传入固定配置，不自动调整成优于基线。

默认实体协议：HoSig 使用 RFF block prototype，基线使用内容空间 centroid；不同空间本身影响 IIR，不能过度解释。附加公平性检查让所有方法用 RFF 均值：

```powershell
.\.venv\Scripts\python.exe -m hosig benchmark --input data/synthetic.jsonl --entity-protocol common-rff --top-k-grid 5 10 20 40 --clients 2 4 8 --output outputs/benchmark_common_rff
```

输出 `metrics.csv`、`benchmark.json`、`ch_comparison.png` 和 `boundary_clarity.png`。包含每方法/Top-k/站点/微批指标、验证网格、警告和实体级 IIR 分布。CH 图是有效微批的非加权均值，不是整体重聚类分数，不是原论文 3D 图。

CH/silhouette 排除 HDBSCAN 噪声，ARI/NMI 包含噪声标签。无足够有效簇、实体重合等输出 `null`，不伪造为零。标准 silhouette 是对论文未给公式的 silhouette-like 指标的显式替代。

`--fit-budget-seconds` 只约束验证阶段 baseline fit 候选，并报告测试 fit 是否超限，不是硬实时/超时中断。端到端估计另记 `pipeline_seconds`。

## 6. 对齐与超图

```powershell
.\.venv\Scripts\python.exe -m hosig align --signatures outputs/demo/signatures.jsonl --output outputs/demo/hypergraph.json
.\.venv\Scripts\python.exe -m hosig align --signatures outputs/demo/signatures.jsonl --incremental --output outputs/demo/hypergraph_incremental.json
```

多站点各次 `run` 指定不同 `--site-id`，然后向 `--signatures` 传多个文件。各站点共享编码/RFF/CMS/HLL 参数和盐；不兼容 `feature_space_id` 或重复 block ID 拒绝比较。`--weights` 接受三个距离权重；缺省等权，未声称获得原论文 AUC 调优权重。

`align` 参考实现保存全部签名并做成对距离，成本随签名数增长，不是长期严格受预算限制的生产超图服务。

## 7. 产物和隐私

```text
outputs/demo/
  report.json                      参数、环境、指标、六阶段耗时
  signatures.jsonl                 用于对齐的签名
  first_batch_boundaries.png       谱排序位置上的成本与分块
  local/batch_0000/assignments.json 事件归属、谱序、边界、评估标签
  local/batch_0000/graph.npz        --save-arrays 时保存
  local/batch_0000/representations.npz
```

签名不含原始 IP、payload、上下文值、评估标签，解释特征仅含 token hash。**hash/CMS/RFF 不自动提供密码学或差分隐私保证**，仍可能泄露频率、时间形态。默认公开盐仅供演示。`local/` 和 `report.json` 仅供本地分析，不能作为共享接口。

`numeric_bytes` 只计算主要数值数组，默认每块 **4608 bytes**，不是论文声称的 2.5 KB；实际 JSON 更大。表示/图内存也是静态数组大小，不是峰值 RSS。

## 8. 复现状态

- 自动测试覆盖时间/标签隔离、共同叶频率、mutual Top-k 暴力解、式 (7)、分段 DP 枚举解、人工边界、sketch、序列化、基线和 CLI。
- 已运行完整合成演示、本地 CSV smoke test、Top-k × Cn 全网格比较、批量和增量超图。
- 不保证优于基线，不报告论文原始数值重现，不包含作者未公开参数；未实现 C++、差分隐私或 PCAP/TLS 解密。
- 下一阶段需要作者原始告警流、组织/验证划分、精确编码与参数、分段成本缩放和评估脚本，才能推进到实验结果复现。

本次实际验证结果、默认配置退化和基线对照汇总见 `docs/validation_results.md`。

## 9. IoT-23 真实流量实验

已下载并运行 `CTU-IoT-Malware-Capture-34-1` 的完整标注连接日志（23,145 条）。新增 `convert-iot23` 命令保留真实时间/IP，并显式构造不含时间或标签的日志内容代理。未下载全部 IoT-23 或 PCAP，也不把代理内容当成原始 payload。

```powershell
.\.venv\Scripts\python.exe -m hosig run --input data/iot23/CTU-IoT-Malware-Capture-34-1/events.jsonl --config configs/paper.json --site-id iot23_34_1 --output outputs/iot23_34_1/default
```

下载、转换、全量运行、四种方法的基线实验、汇总命令和实际结果见 `docs/iot23_experiment.md`。结果位于 `outputs/iot23_34_1/`；本次完整测试为 52 项通过。
