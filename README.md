# chat-persona · 聊天风格画像

把你**自己**的聊天记录，变成一份带证据、带限制说明的「聊天风格画像」。

- 输入：微信/QQ 复制或导出的文本、WhatsApp/Telegram 导出、CSV/TSV
- 处理：本地 Python 脚本，纯标准库，零网络请求
- 输出：`report.md`（6 段报告）+ 5 个中间 JSON

它描述的是**这段记录里的说话方式**，不是人格测评，也不评价聊天对象。

## 能做什么

- 统计事实：消息量、会话数、发起率、回复时延、连发段、深夜占比
- 五维分档：社交主动性 / 探索开放度 / 回应亲和度 / 条理规划度 / 情绪外显度
- 每条结论挂可核验证据（`E1`…），最多 3 条原话片段（已脱敏、≤40 字）
- 标注样本等级（A/B/C/D）、波动带、覆盖度与稳定性
- C/D 级样本拒绝出分，只给事实或直接停下

## 不能做什么

- 不分析他人的记录、不做群聊多人画像
- 不做 MBTI/四字母类型判定，不排名、不给总分、不给百分位
- 不用于招聘、相亲、信贷等评价场景
- 不预测关系走向，不生成聊天建议（计划中的 v0.2 独立技能）
- 不做心理诊断或心理评估

## 安装

把 `skills/chat-persona/` 整个目录复制到 DSH 的用户技能目录：

```powershell
Copy-Item -Recurse -Force .\skills\chat-persona "$env:USERPROFILE\.dsh\skills\chat-persona"
```

要求 Python 3.9+，无需安装任何第三方包。

## 快速开始

```powershell
$py = "python"          # 或你的 python.exe 路径
$work = "$env:TEMP\cp-demo"
New-Item -ItemType Directory -Force $work | Out-Null

# 1) 开监听窗口：在微信/QQ 里多选消息复制，复制一段自动追加一段；Ctrl+C 结束
& $py scripts\grab.py --out "$work\raw.txt" --watch
& $py scripts\grab.py --out "$work\raw.txt" --peek   # 可选：抽查已收集内容的末尾

# 2) 先列发送者，再一条命令出报告
& $py scripts\profile.py --in $work
& $py scripts\profile.py --in $work --me "我的昵称"
```

报告在 `$work\report.md`。已有导出文件（WhatsApp/Telegram/CSV）时跳过第 1 步，把导入文件放进 `$work` 即可。

要单步调试，六个脚本也可以分别运行：

```powershell
& $py scripts\parse_chat.py --in $work --out $work --me "我的昵称"
& $py scripts\anonymize.py --in $work --out $work
& $py scripts\features.py  --in $work --out $work
& $py scripts\score.py     --in $work --out $work
& $py scripts\evidence.py  --in $work --out $work
& $py scripts\render_report.py --in $work --out $work
```

报告在 `$work\report.md`。看完直接删掉整个 `$work` 即可。

每个脚本都支持 `--help`。解析失败时先看 `parse_report.json` 里的 `unparsed_samples`，
再按需换 `--format wechat|qq|whatsapp|tsv|colon|plain`。

## 支持的输入

| 来源 | 形态 | 说明 |
|---|---|---|
| 微信 | 多选消息复制出的「昵称 / 2026年11月19日 16:27 / 内容」三行式（4.x 实测），或「昵称：内容」 | 4.x 复制自带时间戳，可直接出全量画像；3.x 视版本而定 |
| QQ | 消息管理器 → 导出消息记录 → 文本/Word（`.doc`/`.docx`，实测「昵称: 月-日 时:分:秒 内容」），或多选复制（通常只有正文，无时间戳） | `.doc` 需要本机装了 Word；`.docx` 零依赖；加密 .bak 不解析 |
| Word | `.doc` / `.docx` 直接作为 `--in` | 先转文本再识别格式 |
| WhatsApp | `[日期, 时间] 昵称: 内容` | 直接导出 txt |
| Telegram | Desktop 导出 JSON | 读 `messages[]` |
| 表格 | CSV/TSV，含时间/发送者/内容三列 | 列名支持中英文 |
| 纯文本 | 只有「昵称：内容」 | 无时间戳，只能出语言类特征 |

批量收集用 `scripts/grab.py`：复制一段、追加一段，自动去重；`--in` 给目录时 parse 会合并目录内的 `raw.txt` 等文件。
没有时间戳时，行为类特征（回复时延、发起率、深夜占比）会缺失，报告会说明。

## 输出文件

| 文件 | 内容 |
|---|---|
| `parse_report.json` | 格式、消息数、会话数、发送者、未识别行 |
| `messages.anon.jsonl` | 脱敏后的逐条消息（只在本地） |
| `features.json` | 14 项特征值 + 每会话分量（供 bootstrap 重采样） |
| `score.json` | 五维分数、分档、波动带、覆盖度、稳定性 |
| `evidence.json` | 证据条目、反差、数据不足的维度 |
| `report.md` | 最终 6 段报告 |

## 测试

```powershell
python tests\run_all.py
```

当前 31 个用例：解析 10、匿名化 5、特征 4、计分 7、证据 3、端到端 2。

## 目录

```
chat-persona/
├── docs/            DESIGN.md（设计与流程）、REVIEW.md（对原始五份文档的评审）
├── skills/chat-persona/   技能本体（SKILL.md、scripts、assets、references）
├── tests/           fixtures、单元测试、触发语句清单
└── README.md
```

## 隐私

- 原文只在你本机的工作目录里，脚本不发网络请求
- 发送者姓名在特征计算前已替换为「我 / 对方A」
- 报告里最多 3 条片段，单条 ≤40 字，命中敏感词的消息不取样
- Agent 只读 5 个聚合 JSON，不读消息全文

## 许可

MIT。详见 [LICENSE](LICENSE)。
