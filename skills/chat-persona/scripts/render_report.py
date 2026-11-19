#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""render_report.py — 用 5 个 JSON 组装 report.md，保证模板与禁令。

输入：parse_report.json / anonymize_report.json / features.json / score.json / evidence.json
输出：report.md

用法：
  python render_report.py --in work --out work

退出码：
  0  成功
  2  输入错误
  4  生成的文本命中了禁止词（属实现缺陷，应修脚本而不是绕过）
"""

import argparse
import json
import os
import sys

BANNED = [
    "保证", "一定", "准确率", "诊断", "你就是", "天生", "大多数人都",
    "性格类型", "MBTI", "INFP", "INFJ", "ENFP", "INTJ", "ENTP", "ISFJ",
    "心理测试", "科学证明", "超过",
]
STABILITY = {"high": "高", "medium": "中", "low": "低（不稳定）"}
FORMAT_LABEL = {
    "wechat": "微信复制文本", "qq": "QQ 导出文本", "whatsapp": "WhatsApp 导出",
    "telegram": "Telegram JSON", "tsv": "表格（TSV/CSV）", "colon": "冒号行文本",
    "plain": "纯文本（无时间戳）", "csv": "表格（TSV/CSV）",
    "date_time_sender": "时间+昵称两行式", "sender_date_time": "昵称+时间两行式",
    "whatsapp_bracket": "WhatsApp 方括号式", "whatsapp_dash": "WhatsApp 行内式",
    "cn3": "中文日期三行式", "json": "JSON 导出",
    "sender_cn_date": "微信 4.x 多选复制（昵称+中文日期）",
    "cn_date_3line": "中文日期三行式", "mixed": "多文件混合格式",
}


def die(msg, code=2):
    sys.stderr.write("错误：%s\n" % msg)
    raise SystemExit(code)


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except OSError as exc:
        die("读不到 %s（%s）" % (path, exc))
    except json.JSONDecodeError as exc:
        die("%s 不是合法 JSON（%s）" % (path, exc))


def human_seconds(s):
    if s is None:
        return "未知"
    if s < 60:
        return "%d 秒" % int(round(s))
    if s < 3600:
        return "%d 分钟" % int(round(s / 60.0))
    return "%.1f 小时" % (s / 3600.0)


def pct(v):
    if v is None:
        return "—"
    return "%d%%" % int(round(v * 100))


def counts(item):
    ser = item.get("series") or {}
    return (sum(s.get("num", 0) for s in ser.values()),
            sum(s.get("den", 0) for s in ser.values()))


def facts_block(meta, l1, feats, has_ts):
    lines = []
    init = (feats.get("features") or {}).get("initiation_ratio")
    if init and has_ts:
        num, den = counts(init)
        lines.append("- 你说第一句的会话：%d / %d（%s）" % (num, den, pct(init.get("value"))))
    if l1.get("median_reply_s") is not None and has_ts:
        lines.append("- 你的中位回复间隔：%s" % human_seconds(l1["median_reply_s"]))
    if l1.get("median_burst_chars") is not None:
        lines.append("- 你的连发段中位长度：%d 字" % int(round(l1["median_burst_chars"])))
    if l1.get("night_ratio") is not None and has_ts:
        lines.append("- 23:00–06:00 的消息占 %s" % pct(l1["night_ratio"]))
    if l1.get("my_share") is not None:
        lines.append("- 你的消息占全部消息的 %s" % pct(l1["my_share"]))
    days = max(1, meta.get("span_days") or 1)
    lines.append("- 平均每天 %.1f 条消息，共覆盖 %d 天" % (meta.get("messages", 0) / days, days))
    if l1.get("media_share") is not None:
        lines.append("- 媒体消息（图片/语音/表情等）占 %s" % pct(l1["media_share"]))
    if not has_ts:
        lines.append("- 记录未含时间戳，行为类特征（回复间隔、深夜比例、发起会话）缺失")
    return "\n".join(lines[:8])


def dims_table(dims):
    rows = ["| 维度 | 分档 | 波动范围 | 覆盖度 | 稳定性 |", "|---|---|---|---|---|"]
    missing = []
    for key, d in dims.items():
        label = d.get("label") or key
        if d.get("score") is None:
            missing.append(label)
            rows.append("| %s | 未评估 | — | %s | — |" % (label, pct(d.get("coverage"))))
            continue
        rng = d.get("range")
        if rng and (rng[1] - rng[0]) >= 1:
            rng_s = "%d–%d" % (rng[0], rng[1])
        else:
            rng_s = "—（会话间无差异）" if rng else "—"
        rows.append("| %s | %s | %s | %s | %s |" % (
            label, d.get("band") or "—", rng_s, pct(d.get("coverage")),
            STABILITY.get(d.get("stability"), "—")))
    text = "\n".join(rows)
    if missing:
        text += "\n\n数据不足、未评估：%s。" % "、".join(missing)
    return text


def pick_conclusions(evidence, limit=3):
    picked = []
    picked_ids = set()
    seen_dims = set()
    for e in sorted(evidence, key=lambda x: -x.get("contribution", 0)):
        if e["dim"] not in seen_dims:
            picked.append(e)
            picked_ids.add(e["id"])
            seen_dims.add(e["dim"])
    for e in sorted(evidence, key=lambda x: -x.get("contribution", 0)):
        if len(picked) >= limit:
            break
        if e["id"] not in picked_ids:
            picked.append(e)
            picked_ids.add(e["id"])
    return picked[:limit]


def sentence(e):
    s = "**%s。** %s。" % (e.get("claim") or e.get("feature_label"), e.get("stat"))
    if e.get("snippet"):
        s += "例如你说过：\"%s\"。" % e["snippet"]
    return s + "（%s）" % e["id"]


def contrast_block(contrast, evidence, dims):
    if not contrast:
        return None
    by_id = {e["id"]: e for e in evidence}
    hi = by_id.get(contrast["ids"][0])
    lo = by_id.get(contrast["ids"][1])
    if not hi or not lo:
        return None
    return ("**%s偏高，%s偏低。** %s；%s。两段记录指向不同方向，说明这份样本里的说话方式并不单一。"
            % (contrast.get("high_label"), contrast.get("low_label"),
               hi.get("stat"), lo.get("stat")) + "（%s、%s）" % (hi["id"], lo["id"]))


def render(in_dir, out_dir):
    work = in_dir
    parse = load(os.path.join(work, "parse_report.json"))
    anon = load(os.path.join(work, "anonymize_report.json"))
    feats = load(os.path.join(work, "features.json"))
    score = load(os.path.join(work, "score.json"))
    ev = load(os.path.join(work, "evidence.json"))

    meta = feats.get("meta") or {}
    l1 = feats.get("l1") or {}
    grade = score.get("grade") or meta.get("grade") or "D"
    conf = {"A": "高", "B": "中", "C": "低"}.get(grade, "低")
    has_ts = bool(parse.get("has_timestamps"))
    fmt = FORMAT_LABEL.get(parse.get("format"), parse.get("format") or "未知")

    parts = ["# 聊天风格画像", ""]
    parts += [
        "## 1. 数据范围",
        "- 消息 %d 条（文本 %d / 媒体 %d / 系统 %d），会话 %d 段，覆盖 %d 天，对象 %d 位"
        % (parse.get("messages", 0), parse.get("text_messages", 0),
           parse.get("media_messages", 0), parse.get("system_messages", 0),
           parse.get("sessions", 0), parse.get("span_days", 0), meta.get("partners", 1)),
        "- 来源：%s；本地解析，原文未离开本机工作目录" % fmt,
        "- 已剔除敏感消息 %d 条；样本等级 %s（%s置信）" % (anon.get("dropped", 0), grade, conf),
        "",
        "## 2. 事实速览",
        facts_block(meta, l1, feats, has_ts),
        "",
        "## 3. 沟通风格分档",
    ]
    if grade == "C" or not score.get("dims"):
        parts.append("样本等级 C：只出事实，不出维度分。")
    else:
        parts.append(dims_table(score["dims"]))
    parts += ["", "## 4. 三条结论"]
    if grade == "C" or not ev.get("evidence"):
        parts.append("样本量不足，本次不形成结论。")
    else:
        for i, e in enumerate(pick_conclusions(ev["evidence"]), 1):
            parts.append("%d. %s" % (i, sentence(e)))
    cb = contrast_block(ev.get("contrast"), ev.get("evidence") or [], score.get("dims") or {})
    parts += ["", "## 5. 一个反差"]
    if cb:
        parts.append(cb)
    else:
        parts.append("本次没有找到证据足够、方向相反的一对线索：五条线索方向比较一致，"
                     "或其中一侧的样本太薄。")
    parts += [
        "",
        "## 6. 限制与删除",
        "- 本报告基于 %d 条消息的统计推断；规则加权路径的现实效度约 0.15–0.25，不等于人格测评。"
        % parse.get("messages", 0),
        "- 样本等级 %s；分档存在会话间波动，换一段时间的记录结果可能不同。" % grade,
        "- 不构成心理评估，不用于评价他人。",
        "- 删除：直接删除工作目录 `%s`；本技能不保留任何副本。" % work,
        "",
    ]
    text = "\n".join(parts)

    hits = [w for w in BANNED if w in text]
    if hits:
        die("生成文本命中禁止词 %s，请修 render_report.py 或上游文案。" % "、".join(hits), 4)

    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "report.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    sys.stdout.write("已写出 %s\n" % path)
    return path


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except AttributeError:
            pass
    ap = argparse.ArgumentParser(description="把 5 个 JSON 组装成固定 6 段的 report.md。")
    ap.add_argument("--in", dest="in_dir", required=True, help="流水线工作目录")
    ap.add_argument("--out", dest="out_dir", required=True, help="report.md 输出目录（通常同 --in）")
    args = ap.parse_args()
    render(args.in_dir, args.out_dir)


if __name__ == "__main__":
    main()
