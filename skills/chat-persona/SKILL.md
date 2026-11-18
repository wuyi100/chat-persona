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

先问用户手上是哪一种，按对应路径走：

- **已有导出文件**（WhatsApp `.txt`、Telegram `.json`、CSV/TSV）：直接拿路径，跳到第 2 步。
- **微信/QQ 桌面端，靠复制**：这是最常见的路径。先开一个监听窗口：

  ```bash
  python scripts/grab.py --out <work>/raw.txt --watch
  ```

  然后让用户在聊天窗口里多选消息、Ctrl+C——每复制一段，脚本自动追加并去重；够了按 Ctrl+C 结束。
  不用每复制一次就跑一次命令，也不用手工粘进文件。

  如果用户不想开长驻窗口，也可以每复制一段跑一次 `python scripts/grab.py --out <work>/raw.txt`；`--peek` 抽查末尾，`--reset` 清空重来。

  注意：QQ 桌面版多选复制通常只带正文、不带发送者和时间戳；微信 4.x 视版本而定。若第 3 步发现 `has_timestamps=false`，明确告诉用户："这份记录没有时间戳，只能出语言与互动事实，行为维度会缺失。"并给出获得时间戳的办法：用 WhatsApp/Telegram 的导出文件，或在复制内容前手动补一行 `2024-01-01 12:00:00 昵称`。

**不要**尝试读取微信/QQ 的加密数据库（.bak/.db 是加密的，解不开）。

继续条件：`<work>/raw.txt`（或用户给的导出文件）存在且非空。停止条件：用户只有截图 → 说明截图丢失时间戳，请改用文本。

### 2. 一条命令出报告

先列发送者，确认"我"是谁：

```bash
python scripts/profile.py --in <work>
```

看到 `senders` 后重跑：

```bash
python scripts/profile.py --in <work> --me "<用户的名字或序号>"
```

`profile.py` 会依次跑解析 → 脱敏 → 特征 → 计分 → 证据 → 报告，任何一步失败就停在原地并打印原因。`--in` 给目录时会自动合并 `raw.txt` 与其他文本文件、按（时间, 发送者, 正文）去重。

成功时得到 `<work>/report.md` 和 5 个中间 JSON。

### 3. 检查点

报告生成后，必须核对这四项，再交付：

1. `<work>/parse_report.json`：`has_timestamps` 是否为 true；`unparsed_lines` 是否 ≤ 消息数的 5%（偏高就用 `--format wechat|qq|whatsapp|telegram|tsv|colon|plain` 重跑）；发送者是否恰好 2 个。
2. `<work>/features.json` 的 `meta.grade`：
   - `A/B`：正常出分（A ≥1500 条/30 天，B ≥300 条/10 天）。
   - `C`：只出事实，`score.json` 的 `dims` 为空，报告写"样本量不足，本次不形成结论"，照实交付。
   - `D`：`profile.py` 会停在计分并退出 3 → 告诉用户需要 ≥120 条、≥5 天，或再补一段记录。
3. `<work>/score.json`：某维 `score` 为 null → 报告已写"未评估"，不要补猜；`stability=low` → 降一档表述并注明"不稳定"。
4. `<work>/evidence.json`：`insufficient[]` 里的维度不写结论；`contrast` 为 null 时第 5 段会自动写说明，不要自己编。

停止条件：解析为 0 条、群聊（发送者 >2）、或用户不愿指认"我"。

### 4. 单步排查（可选）

哪一步的结果可疑，就单独重跑那一步，参数与 `profile.py` 相同：

| 步骤 | 命令 |
|---|---|
| 解析 | `python scripts/parse_chat.py --in <work> --out <work> --me "<名字>"` |
| 脱敏 | `python scripts/anonymize.py --in <work> --out <work>` |
| 特征 | `python scripts/features.py --in <work> --out <work>` |
| 计分 | `python scripts/score.py --in <work> --out <work>` |
| 证据 | `python scripts/evidence.py --in <work> --out <work>` |
| 报告 | `python scripts/render_report.py --in <work> --out <work>` |

### 5. 交付与自检

把 `report.md` 全文展示给用户，并告知：工作目录 `<work>` 可直接删除，技能不保留副本。

你可以润色措辞，但**不得**改数字、档位、E#，不得新增没有证据的结论。交付前逐条核对 `references/report-template.md` 的 9 条 rubric；任一不过就修。

## 不要做

- 不读 `messages.anon.jsonl` 全文，不把原始聊天内容贴进回答；引用只用 `evidence.json` 里的 `snippet`。
- 不把五维加总、不排名、不比较维度高低、不给百分位。
- 不给对方下人格判断；对方只作中性描述（"对方回复间隔较长"）。
- 不用"保证/一定/准确率/诊断/你就是/天生/性格类型/MBTI/心理测试"等词。
