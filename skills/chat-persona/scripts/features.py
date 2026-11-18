#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""features.py — 从脱敏后的 messages.anon.jsonl 计算 14 项确定性特征。

原则：只做统计，不调用模型，不猜缺失值。算不出的特征直接不输出，并写明原因。

用法：
  python features.py --in work/messages.anon.jsonl --out work
  python features.py --in work/messages.anon.jsonl --out work --anon-report work/anonymize_report.json

输出：
  <out>/features.json

退出码：0 成功；2 参数/数据错误；3 读取失败。
"""

import argparse
import json
import os
import random
import re
import statistics
import sys
from bisect import bisect_right
from datetime import datetime, timedelta

BURST_GAP_S = 120
REPLY_CAP_S = 12 * 3600
COVER_WINDOW_S = 3600
DIVERSITY_SAMPLE = 500
DIVERSITY_MIN = 10

AGREE = [
    "好的", "好呀", "好啊", "行吧", "可以", "嗯嗯", "对对", "确实", "同意",
    "明白", "收到", "没问题", "有道理", "说得对", "是这样的", "我理解", "辛苦了", "行",
]
DISAGREE = [
    "不对", "不是这样", "不同意", "反对", "没必要", "算了", "随便", "无所谓",
    "你错了", "我不这么认为", "但是我觉得", "可是我觉得",
]
EMOTION = [
    "开心", "高兴", "难过", "伤心", "生气", "烦", "累", "焦虑", "紧张", "害怕",
    "委屈", "失望", "无语", "崩溃", "幸福", "感动", "喜欢", "讨厌", "期待", "担心",
    "郁闷", "舒服", "难受", "心疼", "气死", "烦死",
]
PLAN = [
    "明天", "后天", "下周", "周末", "之后", "之前", "到时候", "安排", "计划",
    "约", "几点", "截止", "提醒", "记得", "时间", "地点", "一起",
]
INTENSITY_RE = re.compile(r"(哈{3,}|啊{2,}|呀{2,}|哦{2,}|嗯{2,})")
QUESTION_END = ("吗", "呢", "吧", "么")
QUESTION_START = ("为什么", "怎么", "是不是", "能不能", "要不要", "有没有", "啥", "什么")
PUNCT = "，。？！；：、,.?!;:"


def build_regex(words):
    parts = sorted(set(words), key=len, reverse=True)
    return re.compile("|".join(re.escape(w) for w in parts))


AGREE_RE = build_regex(AGREE)
DISAGREE_RE = build_regex(DISAGREE)
EMOTION_RE = build_regex(EMOTION)
PLAN_RE = build_regex(PLAN)


def load_rows(path):
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def to_dt(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def grade_of(n, days, partners):
    # v1 只支持一对一，partners 恒为 1，因此不再作为 A 级条件；
    # 门槛按"1:1 聊天实际能拿到的量"重定：多数用户能凑到 300 条 / 10 天。
    if n >= 1500 and days >= 30:
        return "A"
    if n >= 300 and days >= 10:
        return "B"
    if n >= 120 and days >= 5:
        return "C"
    return "D"


def sender_key(r):
    return "me" if r.get("is_me") else "other"


def split_bursts(rows):
    out = []
    cur = None
    for r in rows:
        key = sender_key(r)
        chars = len(r.get("text") or "") if r.get("type") == "text" else 0
        dt = to_dt(r.get("ts"))
        if cur is not None and cur["key"] == key and dt and cur["last"] and \
                (dt - cur["last"]).total_seconds() <= BURST_GAP_S:
            cur["chars"] += chars
            cur["last"] = dt
            cur["n"] += 1
        else:
            cur = {"key": key, "chars": chars, "last": dt, "n": 1}
            out.append(cur)
    return out


def session_stats(sid, rows):
    """单个会话的充分统计量。"""
    rows = [r for r in rows if r.get("type") != "system"]

    def _key(r):
        dt = to_dt(r.get("ts"))
        return (0, dt.timestamp()) if dt else (1, 0.0)

    rows = sorted(rows, key=_key)
    mine = [r for r in rows if r.get("is_me")]
    other = [r for r in rows if not r.get("is_me")]
    st = {"sid": sid, "rows": rows, "mine": mine, "other": other}
    st["bursts"] = split_bursts(rows)

    # 发起
    my_ts = [to_dt(r["ts"]) for r in mine if r.get("ts")]
    ot_ts = [to_dt(r["ts"]) for r in other if r.get("ts")]
    st["init"] = None
    if my_ts and ot_ts:
        st["init"] = 1 if min(my_ts) < min(ot_ts) else 0

    # 回复时延
    lat = []
    prev_other = None
    for r in rows:
        dt = to_dt(r.get("ts"))
        if dt is None:
            continue
        if not r.get("is_me"):
            prev_other = dt
        else:
            if prev_other is not None:
                d = (dt - prev_other).total_seconds()
                if 0 < d <= REPLY_CAP_S:
                    lat.append(d)
            prev_other = None
    st["latency"] = lat

    # 夜间
    night = 0
    night_den = 0
    for r in mine:
        dt = to_dt(r.get("ts"))
        if dt is None:
            continue
        night_den += 1
        if dt.hour >= 23 or dt.hour <= 5:
            night += 1
    st["night"] = (night, night_den)

    # 字符多样性：按会话切样本，短会话也允许（下限 10 字），否则 1:1 短消息场景全部缺失
    text = "".join(r.get("text") or "" for r in mine if r.get("type") == "text")
    chars = re.sub(r"[^\w]", "", text)
    st["div"] = None
    if len(chars) >= DIVERSITY_MIN:
        rnd = random.Random(1000 + (int(sid[1:]) if sid[1:].isdigit() else 0))
        k = min(DIVERSITY_SAMPLE, len(chars))
        sample = rnd.sample(chars, k)
        st["div"] = (len(set(sample)), k)

    # 轮次深度
    depth = None
    if len(rows) >= 2:
        switches = 0
        for a, b in zip(rows, rows[1:]):
            if sender_key(a) != sender_key(b):
                switches += 1
        depth = switches + 1
    st["depth"] = depth

    # 回应覆盖
    cov_num = 0
    cov_den = 0
    my_dts = sorted([to_dt(r["ts"]) for r in mine if r.get("ts")])
    for r in other:
        dt = to_dt(r.get("ts"))
        if dt is None:
            continue
        cov_den += 1
        i = bisect_right(my_dts, dt)
        if i < len(my_dts) and (my_dts[i] - dt).total_seconds() <= COVER_WINDOW_S:
            cov_num += 1
    st["cover"] = (cov_num, cov_den)
    return st


def text_stats(mine):
    """单会话内我的文本消息的计数类统计。"""
    q_num = q_den = 0
    agree_n = dis_n = 0
    struct_n = plan_n = 0
    emo_hits = 0
    inten_hits = 0
    chars = 0
    for r in mine:
        if r.get("type") != "text":
            continue
        t = r.get("text") or ""
        q_den += 1
        chars += len(t)
        q_num += 1 if is_question(t) else 0
        if has_agree(t):
            agree_n += 1
        if DISAGREE_RE.search(t):
            dis_n += 1
        if any(p in t for p in PUNCT) or len(t) >= 15:
            struct_n += 1
        if PLAN_RE.search(t):
            plan_n += 1
        emo_hits += len(EMOTION_RE.findall(t))
        inten_hits += len(INTENSITY_RE.findall(t)) + t.count("！") + t.count("!")
    return {
        "q": (q_num, q_den), "agree": (agree_n, q_den), "dis": (dis_n, q_den),
        "struct": (struct_n, q_den), "plan": (plan_n, q_den),
        "emo": (emo_hits, chars), "inten": (inten_hits, chars), "texts": q_den,
    }


def is_question(t):
    s = t.strip()
    if not s:
        return False
    if "？" in s or "?" in s:
        return True
    if s.endswith(QUESTION_END):
        return True
    return any(s.startswith(w) for w in QUESTION_START)


def has_agree(t):
    for m in AGREE_RE.finditer(t):
        if m.start() > 0 and t[m.start() - 1] == "不":
            continue
        return True
    return False


def ratio(series, key="c"):
    num = sum(s.get("num", 0) for s in series)
    den = sum(s.get("den", 0) for s in series)
    return (float(num) / den) if den else None


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="计算聊天特征（本地、零依赖）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n  python features.py --in work/messages.anon.jsonl --out work\n",
    )
    ap.add_argument("--in", dest="inp", required=True, help="messages.anon.jsonl 路径")
    ap.add_argument("--out", required=True, help="输出目录")
    ap.add_argument("--anon-report", help="anonymize_report.json 路径（可选）")
    args = ap.parse_args(argv)

    inp = args.inp
    if os.path.isdir(inp):
        inp = os.path.join(inp, "messages.anon.jsonl")
    if not os.path.isfile(inp):
        print("错误：输入不存在：%s" % inp, file=sys.stderr)
        return 3
    rows = load_rows(inp)
    rows = [r for r in rows if r.get("type") != "system"]
    if not rows:
        print("错误：没有可分析的消息", file=sys.stderr)
        return 2
    if not any(r.get("is_me") for r in rows):
        print("错误：未指认'我'（is_me 全为空），无法计算", file=sys.stderr)
        return 2

    partners = sorted({r.get("sender") for r in rows if not r.get("is_me")})
    if len(partners) > 1:
        print("错误：检测到 %d 个对话对象（%s）。v1 仅支持一对一。"
              % (len(partners), "、".join(partners)), file=sys.stderr)
        return 2

    sessions = {}
    for r in rows:
        sessions.setdefault(r.get("session_id") or "S001", []).append(r)
    sids = sorted(sessions)
    stats = [session_stats(sid, sessions[sid]) for sid in sids]

    dts = [to_dt(r["ts"]) for r in rows if r.get("ts")]
    span_days = 0
    if dts:
        span_days = (max(dts).date() - min(dts).date()).days + 1

    my_all = [r for r in rows if r.get("is_me")]
    my_text = [r for r in my_all if r.get("type") == "text"]
    media = sum(1 for r in rows if r.get("type") == "media")

    # ---------------- 特征与 series
    feats = {}
    missing = []

    def put(key, series, pool, unit, extra=None):
        if not series:
            missing.append({"key": key, "reason": extra or "有效数据不足"})
            return
        cs = [s["c"] for s in series]
        if pool == "ratio":
            v = ratio(cs)
        elif pool == "median":
            vals = [x for s in cs for x in s.get("values", [])]
            v = statistics.median(vals) if vals else None
        elif pool == "mean":
            n = sum(s.get("n", 0) for s in cs)
            v = (sum(s.get("sum", 0.0) for s in cs) / n) if n else None
        else:
            v = None
        if v is None:
            missing.append({"key": key, "reason": extra or "有效数据不足"})
            return
        item = {"value": round(v, 6), "unit": unit, "pool": pool,
                "n": len(series), "series": {s["sid"]: s["c"] for s in series}}
        feats[key] = item

    put("initiation_ratio",
        [{"sid": s["sid"], "c": {"num": s["init"], "den": 1}} for s in stats if s["init"] is not None],
        "ratio", "ratio", "没有同时包含双方且带时间戳的会话")

    put("reply_latency_median_s",
        [{"sid": s["sid"], "c": {"values": s["latency"]}} for s in stats if s["latency"]],
        "median", "s", "没有可用的'对方→我'回复间隔")

    put("bursts_per_session",
        [{"sid": s["sid"], "c": {"num": sum(1 for b in s["bursts"] if b["key"] == "me"), "den": 1}}
         for s in stats if s["mine"]],
        "ratio", "个/会话", "没有我的会话")

    put("night_ratio",
        [{"sid": s["sid"], "c": {"num": s["night"][0], "den": s["night"][1]}}
         for s in stats if s["night"][1]],
        "ratio", "ratio", "我的消息没有时间戳")

    put("char_diversity_500",
        [{"sid": s["sid"], "c": {"sum": (float(s["div"][0]) / s["div"][1]) * s["div"][1], "n": s["div"][1]}}
         for s in stats if s["div"]],
        "mean", "ratio", "我的文本不足 10 字")

    txt = [text_stats(s["mine"]) for s in stats]

    put("question_ratio",
        [{"sid": s["sid"], "c": {"num": t["q"][0], "den": t["q"][1]}} for s, t in zip(stats, txt) if t["q"][1]],
        "ratio", "ratio", "没有我的文本消息")

    put("turn_depth_mean",
        [{"sid": s["sid"], "c": {"sum": float(s["depth"]), "n": 1}} for s in stats if s["depth"]],
        "mean", "轮", "会话消息不足 2 条")

    put("agree_ratio",
        [{"sid": s["sid"], "c": {"num": t["agree"][0], "den": t["agree"][1]}} for s, t in zip(stats, txt) if t["agree"][1]],
        "ratio", "ratio", "没有我的文本消息")

    put("disagree_ratio",
        [{"sid": s["sid"], "c": {"num": t["dis"][0], "den": t["dis"][1]}} for s, t in zip(stats, txt) if t["dis"][1]],
        "ratio", "ratio", "没有我的文本消息")

    put("response_coverage",
        [{"sid": s["sid"], "c": {"num": s["cover"][0], "den": s["cover"][1]}} for s in stats if s["cover"][1]],
        "ratio", "ratio", "对方消息没有时间戳")

    put("structure_score",
        [{"sid": s["sid"], "c": {"num": t["struct"][0], "den": t["struct"][1]}} for s, t in zip(stats, txt) if t["struct"][1]],
        "ratio", "ratio", "没有我的文本消息")

    put("plan_density",
        [{"sid": s["sid"], "c": {"num": t["plan"][0], "den": t["plan"][1]}} for s, t in zip(stats, txt) if t["plan"][1]],
        "ratio", "ratio", "没有我的文本消息")

    put("emotion_density",
        [{"sid": s["sid"], "c": {"num": t["emo"][0], "den": t["emo"][1]}} for s, t in zip(stats, txt) if t["emo"][1]],
        "ratio", "次/100字", "没有我的文本消息")

    put("intensity_density",
        [{"sid": s["sid"], "c": {"num": t["inten"][0], "den": t["inten"][1]}} for s, t in zip(stats, txt) if t["inten"][1]],
        "ratio", "次/100字", "没有我的文本消息")

    # 密度类换算成每 100 字（value 已换算，series 保持原始计数，用 scale 还原口径）
    for k in ("emotion_density", "intensity_density"):
        if k in feats:
            feats[k]["value"] = round(feats[k]["value"] * 100, 4)
            feats[k]["scale"] = 100

    bursts_mine = [b for s in stats for b in s["bursts"] if b["key"] == "me"]
    burst_lens = [b["chars"] for b in bursts_mine if b["chars"] > 0]

    l1 = {
        "my_messages": len(my_all),
        "my_share": round(len(my_all) / float(len(rows)), 4),
        "my_text_messages": len(my_text),
        "median_reply_s": feats.get("reply_latency_median_s", {}).get("value"),
        "median_burst_chars": statistics.median(burst_lens) if burst_lens else None,
        "night_ratio": feats.get("night_ratio", {}).get("value"),
        "media_share": round(media / float(len(rows)), 4),
        "sensitive_dropped": None,
        "span_days": span_days,
    }
    if args.anon_report and os.path.isfile(args.anon_report):
        try:
            with open(args.anon_report, encoding="utf-8") as f:
                ar = json.load(f)
            l1["sensitive_dropped"] = ar.get("dropped")
            l1["sensitive_messages"] = ar.get("sensitive_messages")
        except ValueError:
            pass

    grade = grade_of(len(rows), span_days, len(partners))
    out = {
        "meta": {
            "messages": len(rows), "sessions": len(sids), "span_days": span_days,
            "partners": len(partners), "grade": grade,
            "me_text_messages": len(my_text),
        },
        "l1": l1,
        "features": feats,
        "missing": missing,
    }

    os.makedirs(args.out, exist_ok=True)
    path = os.path.join(args.out, "features.json")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print("特征完成：%d 项可用，%d 项缺失" % (len(feats), len(missing)))
    print("  样本等级 %s（%d 条 / %d 天 / %d 个对象）" % (grade, len(rows), span_days, len(partners)))
    for m in missing:
        print("  - 缺失 %s：%s" % (m["key"], m["reason"]))
    print("  输出：%s" % path)
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.exit(main())
