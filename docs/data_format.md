# 数据接口

## 标准 JSONL / CSV

| 字段 | 必须 | 含义 | 用途 |
| --- | --- | --- | --- |
| `timestamp` | 是 | Unix 秒或带时区 ISO 8601 | 图衰减、时间 trace，不参与内容编码 |
| `src_ip` | 是 | 合法 IPv4 / IPv6 | 网段 hash |
| `dst_ip` | 是 | 合法 IPv4 / IPv6 | 网段 hash |
| `payload` | 否 | 字符串，缺省为空 | 非时间内容 BOW |
| `context` | 否 | JSON 对象 | 签名上下文 sketch 和解释 |
| `label` | 否 | 评估标签 | 仅事后 ARI/NMI |
| `event_id` | 否 | 稳定本地 ID，缺省用序号 | 本地归属表 |

CSV `context` 为合法 JSON 字符串，遵守 CSV 引号转义。采用 `utf-8-sig`，允许 UTF-8 BOM。缺少 timestamp 或 ISO 字符串不带时区时拒绝运行。

```csv
timestamp,src_ip,dst_ip,payload,context,label,event_id
1736121600,192.168.1.10,10.1.2.20,GET /admin,"{""service"":""http""}",probe,e0
1736121672,192.168.1.11,10.1.2.20,GET /admin,"{""service"":""http""}",probe,e1
```

按预期到达顺序准备输入；不根据攻击标签重排。半衰期在当前微批时间值排序后用正间隔校准，编码器仍不读取时间。

## 防止时间/标签泄漏

只有 src_ip、dst_ip、payload 进入编码器。不要在上游把事件时间、duration、间隔或 ground truth 注入 payload，否则你自己的预处理已破坏语义/时间解耦。

签名 context 提取过滤名为 `label`、`ground_truth`、`target`、`timestamp`、`event_id` 的键；无法识别所有自定义泄漏字段，仍需自行检查。

IPv4 用 /24 与 /16；IPv6 /64 与 /48 是实现扩展，不是论文原实验定义。非合法匿名 IP 需在本地稳定映射成合法地址，不能每微批重新随机映射。

## `network-csv` 代理模式

用于当前缺少 timestamp/原始 payload 的本地文件。payload 列白名单：

```text
proto, service, conn_state, dns_query, dns_qtype, ssl_version, ssl_cipher,
http_method, http_uri, http_status_code, http_user_agent, weird_name
```

context：`proto`、`service`、`dst_port`、`conn_state`。评估标签优先取 `type`，其次 `label`，二者不进入内容或 context。空值、`-` 和选定零值忽略。

必须显式传 `--proxy-interval`；时间为行号乘间隔。本模式不复现真实到达时间/payload/告警上下文，必须披露这一偏差。

## 输出隔离

1. `signatures.jsonl`：数值签名、hash 特征、block ID，不含原始事件。
2. `local/`：事件 ID、评估标签、局部分组，只能留在本地。
3. `report.json`：包含完整配置、本地文件路径与协作盐，不应共享。

hash 不等于合规匿名化或差分隐私，多站点需要协调 feature_space_id 对应的编码参数和保密策略。

## IoT-23 标注 Zeek 日志

先用 `python -m hosig convert-iot23` 转换为标准 JSONL，再调用 `run` 或 `benchmark`。映射 `ts` 为真实连接开始时间，源/目的 IP 来自 `id.orig_h/id.resp_h`；payload 为 `proto/service/id.resp_p/conn_state` 代理，不含标签、duration、字节数或包数。

默认稳定按时间排序做离线回放；`--order source` 保留日志顺序。`--label-mode detailed` 使用详细行为标签并在缺失时回退粗标签；`--label-mode binary` 使用 Benign/Malicious。`--limit` 在排序后应用。

转换旁路文件 `events.metadata.json` 标明真实时间但非真实 payload，携带源/输出 SHA256。run/benchmark 验证文件指纹并将 provenance 写入报告。详细命令见 `docs/iot23_experiment.md`。
