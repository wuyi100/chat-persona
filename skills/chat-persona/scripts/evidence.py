#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""evidence.py — 为每个有分的维度挑出 1–2 条证据，并可选附 snippet。

输入：features.json + score.json + messages.anon.jsonl
输出：evidence.json

规则见 docs/DESIGN.md §13：
- 贡献度 w_i × |s_i − 50| 排序，取前 1–2；
- 每条证据带可读统计（含数字）；
- snippet 最多 3 条、每条 ≤40 字、跳过 sensitive；
- 无证据的维度进 insufficient，报告写"数据不足，未评估"；
- 反差需一高一低两维且各有证据。

用法：
  python evidence.py --in work --out work
"""

import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import features as F  # noqa: E402  复用词表与判定函数

FEATURE_LABEL = {
    "initiation_ratio": "发起会话",
    "reply_latency_median_s": "回复间隔",
    "bursts_per_session": "连发段数",
    "night_ratio": "深夜活跃",
    "char_diversity_500": "用字多样性",
    "question_ratio": "主动提问",
    "turn_depth_mean": "话轮深度",
    "agree_ratio": "附和倾向",
    "disagree_ratio": "异议倾向",
    "response_coverage": "回应覆盖",
    "structure_score": "表达完整度",
    "plan_density": "安排密度",
    "emotion_density": "情绪词密度",
    "intensity_density": "语气强度",
}

# (低分侧说法, 高分侧说法)
CLAIM = {
    "initiation_ratio": ("你较少主动开启对话", "你更常先开口"),
    "reply_latency_median_s": ("你回复偏慢", "你回复较快"),
    "bursts_per_session": ("你倾向一次说完", "你习惯连发消息"),
    "night_ratio": ("你很少深夜聊天", "你常在深夜聊天"),
    "char_diversity_500": ("你用词较集中", "你用词变化较多"),
    "question_ratio": ("你较少提问", "你常主动提问"),
    "turn_depth_mean": ("你们的对话偏短", "你们的对话来回较多"),
    "agree_ratio": ("你较少直接附和", "你常给出附和"),
    "disagree_ratio": ("你较少直接表达异议", "你更常表达不同意见"),
    "response_coverage": ("你有时不回应当前话题", "你回应较及时"),
    "structure_score": ("你多用短句碎片", "你发消息更完整"),
    "plan_density": ("你较少提具体安排", "你常把话题落到安排上"),
    "emotion_density": ("你很少直接写出情绪词", "你的消息里情绪词出现得更频繁"),
    "intensity_density": ("你的语气较平", "你常用感叹和重复语气"),
}


def die(msg, code=2):
    sys.stderr.write("错误：%s\n" % msg)
    raise SystemExit(code)


def load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except OSError as exc:
        die("读不到 %s（%s）" % (path, exc))
    except json.JSONDecodeError as exc:
        die("%s 不是合法 JSON（%s）" % (path, exc))


def load_messages(path):
    rows = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    return rows


def counts(item):
    ser = item.get("series") or {}
    num = sum(s.get("num", 0) for s in ser.values() if isinstance(s, dict))
    den = sum(s.get("den", 0) for s in ser.values() if isinstance(s, dict))
    return num, den


def n_values(item):
    ser = item.get("series") or {}
    pool = item.get("pool")
    if pool == "mean":
        return sum(s.get("n", 0) for s in ser.values() if isinstance(s, dict))
    if pool == "median":
        return sum(len(s.get("values", [])) for s in ser.values() if isinstance(s, dict))
    return None


def human_seconds(s):
    if s is None:
        return "未知"
    if s < 60:
        return "%d 秒" % int(round(s))
    if s < 3600:
        return "%d 分钟" % int(round(s / 60.0))
    return "%.1f 小时" % (s / 3600.0)


def build_stat(key, item):
    v = item.get("value")
    if v is None:
        return ""
    if key == "initiation_ratio":
        num, den = counts(item)
        return "%d/%d 段会话由你说第一句（%d%%）" % (num, den, int(round(v * 100)))
    if key == "reply_latency_median_s":
        return "中位回复间隔 %s（共 %s 次）" % (human_seconds(v), n_values(item) or "若干")
    if key == "bursts_per_session":
        return "平均每段会话连发 %.1f 段消息" % v
    if key == "night_ratio":
        return "23:00–06:00 的消息占 %d%%" % int(round(v * 100))
    if key == "char_diversity_500":
        return "500 字抽样中不同字约 %d%%" % int(round(v * 100))
    if key == "question_ratio":
        return "提问类消息占 %d%%" % int(round(v * 100))
    if key == "turn_depth_mean":
        return "平均每段会话 %.1f 个话轮" % v
    if key == "agree_ratio":
        return "附和类回应占 %d%%" % int(round(v * 100))
    if key == "disagree_ratio":
        return "直接表达异议的占 %d%%" % int(round(v * 100))
    if key == "response_coverage":
        return "对方消息后 1 小时内有你回应的占 %d%%" % int(round(v * 100))
    if key == "structure_score":
        return "带标点或 15 字以上的消息占 %d%%" % int(round(v * 100))
    if key == "plan_density":
        return "提到时间或安排的消息占 %d%%" % int(round(v * 100))
    if key == "emotion_density":
        return "每 100 字出现 %.1f 次情绪词" % v
    if key == "intensity_density":
        return "每 100 字有 %.1f 个感叹或重复语气" % v
    return "%s：%.2f" % (FEATURE_LABEL.get(key, key), v)


def hour_of(ts):
    try:
        s = (ts or "").replace("Z", "+00:00")
        return dt.datetime.fromisoformat(s).hour
    except ValueError:
        return None


def first_of_session(messages):
    """返回 (由我首发的会话集合, {会话: 首条消息 i})。"""
    first = {}
    for r in messages:
        sid = r.get("session_id")
        if sid is None:
            continue
        i = r.get("i")
        if sid not in first or (isinstance(i, int) and i < first[sid].get("i", 10 ** 9)):
            first[sid] = r
    initiated = {sid for sid, r in first.items() if r.get("is_me")}
    return initiated, {sid: r.get("i") for sid, r in first.items()}


def match_snippet(key, r, initiated, first_i):
    t = (r.get("text") or "").strip()
    if not t:
        return False
    if key == "initiation_ratio":
        sid = r.get("session_id")
        return sid in initiated and r.get("i") == first_i.get(sid)
    if key == "night_ratio":
        h = hour_of(r.get("ts"))
        return h is not None and (h >= 23 or h < 6)
    if key == "question_ratio":
        return F.is_question(t)
    if key == "agree_ratio":
        return F.has_agree(t)
    if key == "disagree_ratio":
        return bool(F.DISAGREE_RE.search(t))
    if key == "plan_density":
        return bool(F.PLAN_RE.search(t))
    if key == "emotion_density":
        return bool(F.EMOTION_RE.search(t))
    if key == "intensity_density":
        return bool(F.INTENSITY_RE.search(t)) or "！" in t or "!" in t
    if key == "structure_score":
        return any(p in t for p in F.PUNCT) or len(t) >= 15
    return False


def clip(t):
    t = " ".join((t or "").split())
    return t[:40] + "…" if len(t) > 40 else t


def run(in_dir, out_dir):
    feats = load_json(os.path.join(in_dir, "features.json"))
    score = load_json(os.path.join(in_dir, "score.json"))
    messages = load_messages(os.path.join(in_dir, "messages.anon.jsonl"))

    dims = score.get("dims") or {}
    fmap = feats.get("features") or {}
    evidence = []
    by_dim = {}
    insufficient = []
    warnings = []
    snippet_budget = 3
    initiated, first_i = first_of_session(messages)

    for dim_key, dim in dims.items():
        label = dim.get("label") or dim_key
        if dim.get("score") is None:
            insufficient.append({"dim": dim_key, "label": label, "reason": "覆盖度不足"})
            continue
        items = dim.get("items") or {}
        contrib = {}
        for key, it in items.items():
            s = it.get("score")
            if s is None:
                continue
            contrib[key] = it.get("weight", 0.0) * abs(s - 50.0)
        total = sum(contrib.values())
        ranked = sorted(contrib, key=lambda k: contrib[k], reverse=True)
        ranked = [k for k in ranked if contrib[k] > 0][:2]
        if not ranked or total <= 0:
            insufficient.append({"dim": dim_key, "label": label, "reason": "各项都接近中位，无区分证据"})
            continue

        ids = []
        for key in ranked:
            it = items[key]
            s = it.get("score")
            direction = "high" if s >= 50 else "low"
            claim = CLAIM.get(key, ("", ""))[1 if direction == "high" else 0]
            stat = build_stat(key, fmap.get(key) or {})
            snippet = None
            if snippet_budget > 0:
                for r in messages:
                    if not r.get("is_me") or r.get("type") != "text" or r.get("sensitive"):
                        continue
                    if match_snippet(key, r, initiated, first_i):
                        snippet = clip(r.get("text"))
                        snippet_budget -= 1
                        break
            eid = "E%d" % (len(evidence) + 1)
            evidence.append({
                "id": eid,
                "dim": dim_key,
                "dim_label": label,
                "feature": key,
                "feature_label": FEATURE_LABEL.get(key, key),
                "stat": stat,
                "claim": claim,
                "score": s,
                "weight": it.get("weight"),
                "contribution": round(contrib[key] / total, 3),
                "direction": direction,
                "snippet": snippet,
            })
            ids.append(eid)
        by_dim[dim_key] = ids

    contrast = None
    highs = [k for k, d in dims.items() if d.get("score") is not None and d["score"] >= 65 and by_dim.get(k)]
    lows = [k for k, d in dims.items() if d.get("score") is not None and d["score"] <= 38 and by_dim.get(k)]
    if highs and lows:
        hi = max(highs, key=lambda k: dims[k]["score"])
        lo = min(lows, key=lambda k: dims[k]["score"])
        contrast = {
            "high": hi, "high_label": dims[hi].get("label"),
            "low": lo, "low_label": dims[lo].get("label"),
            "ids": [by_dim[hi][0], by_dim[lo][0]],
        }

    out = {
        "version": "0.1.0",
        "evidence": evidence,
        "by_dim": by_dim,
        "contrast": contrast,
        "insufficient": insufficient,
        "warnings": warnings,
    }
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "evidence.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    sys.stdout.write("已写出 %s（证据 %d 条，snippet %d 条）\n"
                     % (path, len(evidence), 3 - snippet_budget))
    return out


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except AttributeError:
            pass
    ap = argparse.ArgumentParser(description="为五维挑证据与 snippet（规则见 DESIGN.md §13）。")
    ap.add_argument("--in", dest="in_dir", required=True,
                    help="包含 features.json、score.json、messages.anon.jsonl 的目录")
    ap.add_argument("--out", dest="out_dir", required=True, help="输出 evidence.json 的目录")
    args = ap.parse_args()
    run(args.in_dir, args.out_dir)


if __name__ == "__main__":
    main()
