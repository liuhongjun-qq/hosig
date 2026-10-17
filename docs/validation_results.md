# 本地验证结果

验证日期：2026-10-08。以下全部是当前实现的运行结果，**不是论文实验表格的重现**。

## 自动验证

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m compileall -q hosig tests
```

结果：**39 passed**，无测试警告；Python 编译检查通过。关键检查包括：

- 修改 timestamp、context、label 不会改变内容向量；修改评估标签不改变 block/signature。
- 稀疏共同叶候选和 mutual Top-k 与逐对暴力计算一致。
- 式 (7) 与手算值一致；带最小间隔的 DP 与枚举最优目标一致。
- 人工植入的 connected graph 分布边界可被检测。
- CMS、HLL、序列化、单点批、资源上限、时间解析、基线和 CLI 均覆盖。
- 默认 JSON 配置与 Config 完全一致。

## 默认参数演示

```powershell
.\.venv\Scripts\python.exe -m hosig demo --output outputs/demo --events 768 --save-arrays
```

| 微批 | 事件 | block | 平均度数 | 正收益候选 | ARI |
| --- | --- | --- | --- | --- | --- |
| 0 | 512 | 1 | 17.14 | 0 | 0.000 |
| 1 | 256 | 1 | 17.10 | 0 | 0.000 |

默认公式/参数未成功识别合成输入中的三种活动。lambda_seg 约 4.991 / 4.436，高于全部边界成本。报告中保留这一结果，而不是添加隐式成本缩放来提高指标。方法未达到论文报告的优于基线结论。

## 探索配置演示

```powershell
.\.venv\Scripts\python.exe -m hosig demo --config configs/exploratory.json --output outputs/exploratory --events 768
```

| 微批 | 事件 | block | 正收益候选 | ARI |
| --- | --- | --- | --- | --- |
| 0 | 512 | 9 | 107 | 0.488 |
| 1 | 256 | 10 | 133 | 0.436 |

探索参数说明边界机制能工作，但仍有过分割，**不是原论文参数，不用于证明达到论文效果**。探索配置未通过独立验证集选参，不报告成泛化结果。

## 三基线完整网格

```powershell
.\.venv\Scripts\python.exe -m hosig benchmark --input outputs/demo/synthetic.jsonl --top-k-grid 5 10 20 40 --clients 2 4 8 --output outputs/benchmark
```

得到 **224 条测试记录**，即 4 方法 × 4 Top-k × (2+4+8) 站点。基线有 168 次参数选择，均在验证前缀上进行。报告的输入 SHA256 已核对与当前 synthetic.jsonl 一致。

| 方法 | 全网格平均 ARI | CH 未定义记录数 |
| --- | --- | --- |
| HoSig 默认配置 | 0.013 | 45 |
| HDBSCAN | 1.000 | 0 |
| Spectral | 0.620 | 0 |
| Louvain | 0.706 | 0 |

ARI 是额外的合成标签检查，不是论文要求指标。这个易分辨合成数据下 HDBSCAN 优于当前 HoSig 默认设置，不能用它支持论文的优越性结论。11 条 Spectral 记录包含稀疏图断连警告，已保存而非忽略。

CH、silhouette、modularity 和两种 IIR 的逐项原始结果在 `outputs/benchmark/metrics.csv`，全部实体级分布和基线选择在 `outputs/benchmark/benchmark.json`。

还运行了 `--entity-protocol common-rff --top-k-grid 20 --clients 2` 的附加检查，结果位于 `outputs/benchmark_common_rff/`。该附加检查只覆盖单个 Top-k 和 Cn，不是另一个完整网格。

## 本地 network CSV smoke test

```powershell
.\.venv\Scripts\python.exe -m hosig run --input ../dataset/archive/train_test_network.csv --format network-csv --proxy-interval 72 --limit 512 --output outputs/local_csv_smoke
```

读入 512 条，生成 19 块，平均度数 16.18。19 块来源于图连通分量，不是正收益对比切点；正收益候选为 0。该文件前缀只有单一评估类别，ARI=0 不宜解读为完整数据集上的效果。人为时间/代理 payload 的限制已写入报告。

## 超图

探索配置的 19 个签名已分别完成批量层次构图和增量合并/拆分流程，结果在：

- `outputs/exploratory/hypergraph.json`
- `outputs/exploratory/hypergraph_incremental.json`

这仅验证对齐/超图实现可运行，不验证真实跨组织归因正确性；后者需要未提供的配对真值和权重调优数据。

## 判定

完成的是**可审计的方法实现和本地验证**。尚不能判定为论文数值/性能复现成功。尤其需要作者澄清边界成本尺度与 BIC penalty，并提供原始实验数据/配置。
