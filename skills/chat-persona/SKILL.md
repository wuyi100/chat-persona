---
name: chat-persona
description: 分析用户自己提供的聊天记录（微信/QQ 复制的文本、WhatsApp/Telegram 导出、CSV/TSV），生成"聊天风格画像"：本地脚本先算行为与语言特征，再输出带证据的五维沟通风格分档与限制声明。当用户说"分析我的聊天记录""看看我的聊天风格""聊天人格""微信聊天分析""QQ 聊天记录分析""我说话是什么风格""聊天画像""沟通风格分析"时使用。Profile chat style from a user-supplied log; local, rule-based, evidence-cited.
license: MIT
compatibility: Python 3.9+，仅标准库；输入须为用户本人拥有或已获授权的记录
---

# 聊天风格画像

把用户**自己**提供的聊天记录，跑成一份带证据的五维沟通风格画像。规则加权、本地运行，只描述"这段记录里的说话方式"，不判定"你是什么人"。

## 适用与不适用

适用：一对一聊天记录，≥200 条；用户本人参与；用户主动要求分析自己的说话方式。

先确认三件事，任一不满足就停下来说清楚：

1. 记录是用户本人的，或用户已获得对方同意。
2. 是**一对一**对话。群聊请直接说："v1 只支持一对一，群聊里的话轮和对象无法归属。"
3. 用户要的是"我的说话方式"，不是"对方是什么人"。

以下请求**拒绝**，不要开始流水线：

- 分析他人的聊天记录、判断对方性格/是否喜欢用户、预测关系走向。
- 给第三方贴负面标签、用于招聘/相亲筛选/信贷等评价场景。
- 记录里出现自伤自杀、家暴、跟踪骚扰、私密要挟、未成年性诱导：停止分析，先给安全提示（见 `references/privacy.md`）。

## 流程

所有命令在工作目录 `<work>` 下执行；`scripts/` 指本技能目录。Python 用用户环境里的 `python`，只需标准库。

### 1. 收集

让用户把聊天记录**复制粘贴**进 `<work>/input.txt`，或给出已经导出的文件路径（.txt/.json/.tsv/.csv）。

微信/QQ 没有可直接解析的导出格式，正确做法是：选中消息 → 复制 → 粘贴进文本文件；或用微信"聊天记录迁移"之外的工具导出为 txt。**不要**尝试读取微信/QQ 的加密数据库。

继续条件：`<work>/input.txt` 存在且非空。停止条件：用户只有截图 → 说明截图丢失时间戳，行为特征无法计算，请改用文本。

### 2. 解析

```bash
python scripts/parse_chat.py --in <work>/input.txt --out <work> --list-senders
```

读 `<work>/parse_report.json`：

- `format` 是否识别正确；`unparsed_lines` 是否 ≤ 消息数的 5%。
- `unparsed_lines` 偏高 → 用 `--format wechat|qq|whatsapp|telegram|tsv|colon` 指定重跑；仍失败就请用户换一种复制方式（见 `references/privacy.md` 末尾的格式说明）。
- `has_timestamps` 为 false → 只能出文本特征，行为维度会缺失，先告知用户。

继续条件：至少解析出 200 条且有发送者。停止条件：解析为 0 条，或群聊（发送者 >2）。

### 3. 指认"我是谁"

把 `senders` 列表给用户看，问哪一个是本人，然后重跑：

```bash
python scripts/parse_chat.py --in <work>/input.txt --out <work> --me "<用户的名字>"
```

`--me` 也接受序号。继续条件：`parse_report.json` 的 `me` 非空且 `senders` 恰好 2 个。停止条件：用户不愿指认 → 停止，画像必须知道"我"是谁。

### 4. 匿名化

```bash
python scripts/anonymize.py --in <work> --out <work>
```

读 `<work>/anonymize_report.json`：

- `masked` 各类计数是否合理；`sender_map` 是否已把我/对方分开。
- `safety_notice` 非空 → 原文转述给用户，问是否继续；涉及危机内容 → 停止。
- `dropped` > 0 只会在显式加了 `--drop-sensitive` 时出现；默认保留并打标、不引用。用户想彻底删除时再加该参数重跑。

继续条件：`messages.anon.jsonl` 存在。停止条件：用户要求保留原始姓名电话 → 说明报告会引用 snippet，必须先脱敏。

### 5. 特征与分级

```bash
python scripts/features.py --in <work> --out <work>
```

读 `<work>/features.json` 的 `meta.grade`：

- `A/B`：继续出分。
- `C`：只出事实速览与定性描述，不出分（第 6 步会输出 note）。
- `D`：停止，告诉用户需要 ≥200 条、≥7 天，或再提供一段时间的记录。

同时看 `meta.partners`：>1 说明不是一对一，回到第 3 步。

### 6. 计分

```bash
python scripts/score.py --in <work> --out <work>
```

读 `<work>/score.json`：

- 每维 `score` 可能为 null（覆盖不足 <0.6）→ 报告写"数据不足，未评估"，不要猜。
- `stability=low` → 该维降一档表述，并注明"不稳定"。
- `band` 已处理跨档波动，不要自己改写档位。
- C 级：`dims` 为空，继续跑第 7、8 步；`render_report.py` 会写"样本量不足，本次不形成结论"。

### 7. 证据

```bash
python scripts/evidence.py --in <work> --out <work>
```

读 `<work>/evidence.json`：`evidence[]` 每条带 `id`、`stat`、`claim`、可选 `snippet`；`insufficient[]` 的维度不写结论；`contrast` 为 null 时第 5 段会自动写"没有找到证据足够的反差"，不要自己编一对。

### 8. 生成报告

```bash
python scripts/render_report.py --in <work> --out <work>
```

得到 `<work>/report.md`。它已保证：6 段齐全、每条结论带 E#、snippet ≤3、无禁止词、无总分/排名、含删除指引。

你可以润色措辞，但**不得**改数字、档位、E#，不得新增没有证据的结论。禁止词与写法见 `references/report-template.md`。

### 9. 交付与自检

把 `report.md` 全文展示给用户，并告知：工作目录 `<work>` 可直接删除，技能不保留副本。

交付前逐条核对 `references/report-template.md` 的 9 条 rubric；任一不过就修。

## 不要做

- 不读 `messages.anon.jsonl` 全文，不把原始聊天内容贴进回答；引用只用 `evidence.json` 里的 `snippet`。
- 不把五维加总、不排名、不比较维度高低、不给百分位。
- 不给对方下人格判断；对方只作中性描述（"对方回复间隔较长"）。
- 不用"保证/一定/准确率/诊断/你就是/天生/性格类型/MBTI/心理测试"等词。
