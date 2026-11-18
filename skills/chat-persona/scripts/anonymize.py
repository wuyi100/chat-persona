#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""anonymize.py — 在特征计算之前，把 messages.jsonl 里的身份与敏感信息脱敏。

做三件事：
  1. 发送者标签 → 我 / 对方A / 对方B …
  2. 结构化隐私（手机、证件、邮箱、链接、卡号、@提及、自定义姓名）→ 占位符
  3. 敏感内容打标（可选整条剔除）

用法：
  python anonymize.py --in work/messages.jsonl --out work
  python anonymize.py --in work/messages.jsonl --out work --drop-sensitive
  python anonymize.py --in work/messages.jsonl --out work --name-list names.txt

输出：
  <out>/messages.anon.jsonl
  <out>/anonymize_report.json

退出码：0 成功；2 参数错误；3 输入不可读。
"""

import argparse
import json
import os
import re
import sys

SENSITIVE_WORDS = [
    "自杀", "自残", "轻生", "割腕", "跳楼",
    "抑郁", "确诊", "病历", "住院", "手术", "流产",
    "家暴", "殴打", "性侵", "强奸", "猥亵", "裸照",
    "身份证", "银行卡", "密码", "转账", "借钱", "欠款", "高利贷",
    "未成年", "14岁", "16岁", "初中的",
]

CRISIS_WORDS = ["自杀", "自残", "轻生", "割腕", "跳楼", "性侵", "强奸", "家暴", "未成年"]

CRISIS_NOTICE = (
    "检测到可能涉及自伤、暴力或未成年人的内容。本工具不提供危机干预，"
    "如果你或他人正处于危险中，请联系当地紧急服务或专业机构。"
)

PATTERNS = [
    ("链接", re.compile(r"https?://[^\s，。；、）)】]+")),
    ("邮箱", re.compile(r"[\w.+\-]+@[\w\-]+\.[\w.\-]+")),
    ("证件", re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")),
    ("卡号", re.compile(r"(?<!\d)[456]\d{15,18}(?!\d)")),
    ("手机", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")),
    ("提及", re.compile(r"@[^\s@，。]{1,20}")),
]


def mask_text(text, names):
    counts = {}
    for label, pat in PATTERNS:
        text, n = pat.subn("[%s]" % label, text)
        if n:
            counts[label] = counts.get(label, 0) + n
    for name in names:
        if len(name) < 2:
            continue
        if name in text:
            n = text.count(name)
            text = text.replace(name, "[姓名]")
            counts["姓名"] = counts.get("姓名", 0) + n
    return text, counts


def build_sender_map(rows):
    order = []
    me = None
    for r in rows:
        s = r.get("sender", "")
        if s not in order:
            order.append(s)
        if r.get("is_me") and me is None:
            me = s
    mapping = {}
    idx = 0
    if me is not None:
        mapping[me] = "我"
    for s in order:
        if s == me:
            continue
        mapping[s] = "对方" + chr(ord("A") + idx)
        idx += 1
    return mapping, me


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="聊天记录脱敏（本地、零依赖）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n  python anonymize.py --in work/messages.jsonl --out work --drop-sensitive\n",
    )
    ap.add_argument("--in", dest="inp", required=True, help="messages.jsonl 路径")
    ap.add_argument("--out", required=True, help="输出目录")
    ap.add_argument("--name-list", help="自定义姓名清单，每行一个")
    ap.add_argument("--drop-sensitive", action="store_true", help="整条剔除命中敏感词的消息")
    args = ap.parse_args(argv)

    inp = args.inp
    if os.path.isdir(inp):
        inp = os.path.join(inp, "messages.jsonl")
    if not os.path.isfile(inp):
        print("错误：输入不存在：%s" % inp, file=sys.stderr)
        return 3

    rows = []
    with open(inp, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except ValueError:
                print("错误：messages.jsonl 第 %d 行不是合法 JSON" % (len(rows) + 1), file=sys.stderr)
                return 3

    names = []
    if args.name_list:
        if not os.path.isfile(args.name_list):
            print("错误：姓名清单不存在：%s" % args.name_list, file=sys.stderr)
            return 2
        with open(args.name_list, encoding="utf-8") as f:
            names = [ln.strip() for ln in f if ln.strip()]

    mapping, me = build_sender_map(rows)
    masked = {}
    sensitive = 0
    dropped = 0
    crisis = False
    out_rows = []

    for r in rows:
        text = r.get("text") or ""
        new_text, c = mask_text(text, names)
        for k, v in c.items():
            masked[k] = masked.get(k, 0) + v

        hit = [w for w in SENSITIVE_WORDS if w in text]
        if hit:
            sensitive += 1
            r["sensitive"] = True
            if any(w in CRISIS_WORDS for w in hit):
                crisis = True
        if hit and args.drop_sensitive:
            dropped += 1
            continue

        r["text"] = new_text
        r["sender"] = mapping.get(r.get("sender", ""), r.get("sender", ""))
        out_rows.append(r)

    # 重排 i，保持连续
    for i, r in enumerate(out_rows):
        r["i"] = i

    os.makedirs(args.out, exist_ok=True)
    opath = os.path.join(args.out, "messages.anon.jsonl")
    with open(opath, "w", encoding="utf-8", newline="\n") as f:
        for r in out_rows:
            f.write(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n")

    report = {
        "messages_in": len(rows),
        "messages_out": len(out_rows),
        "sender_map": mapping,
        "me_found": me is not None,
        "masked": masked,
        "sensitive_messages": sensitive,
        "dropped": dropped,
        "safety_notice": CRISIS_NOTICE if crisis else None,
        "warnings": [] if me is not None else ["未指认'我'：全部对象按 对方A/对方B 处理"],
    }
    rpath = os.path.join(args.out, "anonymize_report.json")
    with open(rpath, "w", encoding="utf-8", newline="\n") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print("脱敏完成：%d → %d 条" % (len(rows), len(out_rows)))
    if mapping:
        print("  身份映射：%s" % "，".join("%s→%s" % (k, v) for k, v in mapping.items()))
    if masked:
        print("  替换：%s" % "，".join("%s %d 处" % (k, v) for k, v in masked.items()))
    if sensitive:
        print("  敏感消息：%d 条%s" % (sensitive, "（已剔除）" if args.drop_sensitive else "（保留但不引用）"))
    if crisis:
        print("  ! " + CRISIS_NOTICE)
    print("  输出：%s" % opath)
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.exit(main())
