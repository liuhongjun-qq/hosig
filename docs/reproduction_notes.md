# 复现决策、公式和已知偏差

## 1. 复现层次

本项目是对用户提供论文 Markdown 的独立实现，而非下载作者代码。目标是可执行、可审计的方法复现；不声称恢复作者未公开实现，也不声称获得相同实验分数。

论文描述的 24,842 条隐私处理告警流、真实组织划分、精确验证切片没有出现在当前代码目录中。邻近目录的 network CSV 缺少时间戳与原始 payload，不能当作等价数据集。合成数据仅用于运行与算法性质验证。

## 2. 参数来源

| 参数 | 默认值 | 来源 |
| --- | --- | --- |
| 编码维度 d | 256 | 式 (3) |
| payload 词表大小 | 2048 | 式 (2) |
| Top-k | 20 | 实验默认值 |
| alpha | 0.5 | 实验默认值 |
| RFF 维度 D | 512 | 实验默认值 |
| 时间桶 H | 64 | 实验默认值；签名描述另举 H=24，存在不同设置 |
| 对比窗口 | 64/64 | 实验默认值 |
| segmentation beta | 0.8 | 实验中 lambda_seg = beta log n |
| T / leaf_size | 64 / 16 | 未明确公开，复现假设 |
| lambda_0 | 0.05 | 未明确公开，复现假设 |
| eta | 1.0 | 未明确公开，复现假设 |
| 微批大小 | 512 | 未明确公开，复现假设，控制单批资源 |
| 最小块长 | 8 | 复现附加约束，避免无间隔地选择所有正收益边界 |
| RFF gamma | 1/d | 未公开 bandwidth 的显式约定，可配置 |
| CMS width/depth | 128/4 | 未公开，复现假设 |
| HLL precision | 8 | 未公开，复现假设 |
| 解释特征数 | 10 | 论文签名参数例子 |
| 随机种子 | 42 | 复现约定 |

`configs/paper.json` 和代码 Config 的默认值保持一致。配置可只写要覆盖的键，未知键拒绝加载。`configs/exploratory.json` 明确是探索配置，而非论文参数。

## 3. 内容表示：式 (1)–(3)

- IPv4 分别 hash 源/目的地址的 /24、/16 网段，归一化为四个 [0,1] 标量。
- 使用稳定 BLAKE2 hash 而非 Python 内建随机化 hash。
- payload 按固定正则分词，词频写入 2048 维固定 hash 词表。
- 投影 W 固定随机高斯、尺度 1/sqrt(2052)，b=0。
- GELU 为 x Phi(x)，LayerNorm 按每个样本的特征维标准化，epsilon=1e-5。
- 不学习标签，不把时间、context、duration、到达间隔等注入表示。

**hashed BOW 是对未披露词表/分词器的替代，存在碰撞，不等价于作者固定词典 BOW。** 投影分布、hash 数值尺度、b 和 LayerNorm epsilon 也未公开，以上均为透明假设。跨站点可比性还要求完全一致的这套编码。

## 4. 森林与稀疏图：式 (4)–(6)

森林在整个当前微批上建树，每次在有变化的维度中均匀选一个，再在 min/max 之间均匀选切分阈值，直到叶内 <= leaf_size。

若叶中样本完全相同，无维度可切分，则保留大叶；不能为了满足叶大小而人为分开相同样本。这保证共同叶语义，但最坏情况下候选枚举可能退化到平方时间。

相似度是真正的共同叶频率：

```text
s_ij = (1/T) * sum_t [leaf_t(i) == leaf_t(j)]
```

按点枚举同叶候选，避免构造完整 n×n 稠密相似度矩阵。每点只保留正权重 Top-k，平权按记录索引稳定打破；再取 directed graph 与其转置的 minimum，仅保留 mutual 边，不是 union kNN。

时间使用半衰期而非 e-folding 时间常数：

```text
g(dt) = lambda_0 + (1-lambda_0) *
        [alpha * 2^(-abs(dt)/tau_1) + (1-alpha) * 2^(-abs(dt)/tau_2)]
w_ij = s_ij * g(t_i-t_j)
tau_1 = median(positive arrival gaps)
tau_2 = max(tau_1, median + 3*MAD)
```

论文只给 median/MAD 或分位数的校准思想，没有唯一乘数；3*MAD 为复现约定。全等时间或单点批使用 1 秒回退。显式 half-life 参数可覆盖自动校准。图度数不保证达到论文报告的平均 8–12。

## 5. 谱排序

采用 L = I - D^(-1/2) W D^(-1/2) 的归一化图 Laplacian。<=64 节点的小连通分量用 dense eigh，较大分量用 sparse Lanczos `eigsh`，取第二小特征值的特征向量。

断连图没有唯一的全局 Fiedler 向量，因此：按连通分量分别排序，分量按最小输入索引拼接，并强制分量边界为 block 边界。孤立点成为单点块；这种结构边界不受 min_block_size 限制。它是为使未规定的退化情形确定化而加入的规则。

以最大绝对值分量的符号固定特征向量方向。重特征值的基底仍可随数值库版本变化，不能承诺跨所有平台 bitwise 相同。Lanczos 不收敛时记录警告并退回该分量的索引顺序，不隐瞒降级。

## 6. 对比成本与分段：式 (7)–(8)

依据 Markdown 可恢复的式 (7)，采用：

```text
C(b) = ||mean_RFF(L_b) - mean_RFF(R_b)||^2
     + eta * [sum(W_LL)/|L|^2 + sum(W_RR)/|R|^2
              - 2*sum(W_LR)/(|L|*|R|)]
lambda_seg = beta * log(n)
maximize sum_selected_b [C(b) - lambda_seg]
```

W 的对角为零；内块求和包括两个方向，跨块只取 L×R，再乘 2。窗口在序列两端缩短。分段发生于谱序，不是原始时间序；边界图的横轴明确标注这一点。

该目标仅是边界收益的可加和，并不包含区间拟合项。无额外约束时，最优解就是选择所有 C(b)>lambda 的位置。为避免密集邻近切点，加入最小块长约束，用带间隔的 weighted scheduling DP 求精确最优解。由于收益只依赖 b，此 DP 是线性状态递推，不需要一般区间分段的 O(n^2) DP。测试用枚举对照验证了目标最优性。

### 默认 BIC 惩罚问题

在 n=512 时，0.8 log(n) 约为 4.99；常规归一化 RFF 的 MMD 对比通常远小于这个值。当前合成输入的所有候选均无正收益，因此默认退化成单一连通块。这不能单凭代码判断是论文错误：作者可能有未披露的成本缩放、不同 eta/bandwidth 或窗口定义。

实现**不自动缩放 C(b)、不暗调 beta、不固定真实簇数**。提供探索配置显式改变 beta 和窗口等，用于展示机制，不声称恢复论文结果。

## 7. 签名：式 (9)

- 原型：共享 RFF 空间的块内均值。
- 时间 trace：块内 min/max 区间均分 H 桶、保留计数。单时间点用 1 秒宽度。未采用固定时刻/跨站点公共日历桶，属于未公开 binning 的复现约定。
- context：对 name=value token 建 Count-Min Sketch 和 HyperLogLog；不输出明文 token。
- 解释：二元 token 出现与“属于当前块”之间的互信息，按信息增益取 top-m，只保存 token hash。它不是对连续 z 的作者未定义 IG 算法。
- 时间和 context 不反向进入 z。

### 边界强度定义的矛盾

论文给 beta_B = mean_cross / mean_inside，却说越高越清晰。依照这个比值公式，跨连接越弱，值越小才是清晰。本实现保留公式，字段命名 `boundary_ratio`，并标注 `lower_is_clearer`。内部平均权重为零时输出 null，不加 epsilon 伪造值。

主要数组的字节数为：

```text
prototype: 512*4 = 2048
time_hist: 64*4  = 256
CMS: 128*4*4    = 2048
HLL: 2^8*1     = 256
合计            = 4608 bytes
```

不含 ID、解释特征、估计值、JSON 开销，不能当作论文 2.5 KB 的复现。未实现量化、压缩二进制协议或差分隐私。

## 8. 多视图对齐与超图：式 (10)–(13)

原型距离为 L2；时间距离为累计平方代价的 DTW 最优路径再开平方，不默认归一化事件计数。context 距离把同 hash 布局 CMS bucket 计数展平后归一化，求自然对数基的 JS divergence 平方根。

CMS 不是可逆字典；不能不带 key universe 就恢复真实上下文概率分布。本项目用 bucket 分布作明确近似，有碰撞偏差。双方 context 均空时距离为 0，一方为空时用 sqrt(log 2) 最大差异约定。

默认三视图等权；论文的 alignment AUC 选权重需要未提供的验证 block-pair 真值，所以没有声称做了相同调优。命令行可显式指定权重。三个视图量纲不同，权重/阈值必须在真实验证数据上选择，不能将默认阈值看成通用值。

初始超图用 complete-linkage 并按距离阈值切树，代表块为 medoid。所有成员成对距离 <= threshold，是比论文“存在中心、成员到中心 <= threshold”更强的条件，是未指定 linkage 的实现约定。

增量时，新块到现有 medoid 的最小距离 <= merge_threshold 则加入，否则新建超边。凝聚性定义为不同成员无序对的平均 exp(-distance)，单点为 1；避免歧义分母和自连接导致不同超边大小的量纲问题。低于 split_threshold 时 complete-linkage 拆分，拆分距离不超过 -log(split_threshold)，保证每个保留对的相似度下限。

为防止“不同随机坐标仍强行对齐”，签名包括配置指纹 feature_space_id。指纹涵盖随机 seed、编码/RFF/sketch 维度和 salt。不同指纹拒绝比较；同指纹不自动保证任意软件实现的字节级兼容。

## 9. 实验与指标的限制

1. baseline Spectral / Louvain 用与 HoSig 完全相同的 graph；HDBSCAN 用相同内容表示。
2. 每个模拟站点验证前缀与测试后缀分离，baseline 网格选择不看标签。HoSig 参数不自动调优。
3. 选择分数是 silhouette + modularity - noise_rate，属于对论文模糊多指标选参规则的显式约定。
4. 标准 sklearn HDBSCAN 替代论文未明确指定包版本的 HDBSCAN；Spectral 用 ARPACK/kmeans，未实现 Nyström。Louvain 不等于 Leiden。
5. 常规 silhouette 替代未公开公式的 silhouette-like。
6. 标准化实体后，k=ceil(0.05*M)，排除 self，IIR_k=1/d_k，IIR_norm=median(d_k)/d_k。只有一实体或重复实体距离为零时返回 null。
7. paper 实体协议让方法的 prototype 与 baseline centroid 位于不同维度/空间，可能影响比较；另提供 common-rff 作为敏感性检查。
8. 时间报告不是在论文相同硬件上获得的性能复现；共享 graph 的 preprocessing 用实测阶段时间归入各相应 baseline，但不强制中断超时方法。
9. 只报告静态数值数组大小，不报告进程峰值、网络实测流量或完整线上吞吐。
10. 未生成 Mann–Whitney 显著性星号；人工站点、同批实体和重复参数实验未必满足独立性，不能将 smoke test 当正式显著性实验。

## 10. 后续严格复现所需材料

- 原始/脱敏告警内容、到达时间与 context schema，以及组织划分。
- 原始词表/分词器、IP hash/数值尺度、随机 W/b、种子。
- T、leaf_size、lambda_0、eta、RFF bandwidth、半衰期乘数、批/滑窗参数。
- 原始边界成本缩放、BIC penalty 定义与 min block / 非连通图处理。
- 时间桶规则、CMS/HLL 参数、context 分布估计、IG 定义、对齐验证 block-pair 标签。
- CH/silhouette-like 实体定义、评估切片和基线 grid、原始结果脚本。

获取以上材料后，可以保持现有分模块接口，只替换差异定义，避免把未经验证的实现假设混入最终论文结果。
