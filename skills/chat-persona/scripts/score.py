#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""score.py — 把 features.json 折算成五维分、波动范围与稳定性。

输入：features.json（features.py 产出）+ assets/weights.v0.json + assets/anchors.v0.json
输出：score.json

用法：
  python score.py --in work --out work
  python score.py --in work --out work --bootstrap 2000 --seed 7
  python score.py --in work --out work --assets ../assets

退出码：
  0  成功（A/B 级出分，C 级只回 L1 提示）
  2  输入错误
  3  样本不足（D 级），拒绝出分
"""

import argparse
import json
import os
import random
import statistics
import sys

BAND_NAMES = ["低", "偏低", "中", "偏高", "高"]
DEFAULT_ASSETS = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "assets")


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


def interp(anchors, x):
    """在锚点上线性插值；x 为 None 返回 None，超界取端点。"""
    if x is None:
        return None
    pts = sorted((float(a), float(b)) for a, b in anchors)
    if not pts:
        return None
    if x <= pts[0][0]:
        return pts[0][1]
    if x >= pts[-1][0]:
        return pts[-1][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= x <= x1:
            if x1 == x0:
                return y1
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return pts[-1][1]


def band_of(score):
    if score is None:
        return None
    return BAND_NAMES[min(4, max(0, int(score // 20)))]


def band_label(score, lo, hi):
    """range 跨档时给组合标签，否则给单档。"""
    base = band_of(score)
    if base is None:
        return None
    if lo is None or hi is None:
        return base
    a, b = band_of(lo), band_of(hi)
    if a == b:
        return base
    ia, ib = BAND_NAMES.index(a), BAND_NAMES.index(b)
    if (ia, ib) == (2, 3):
        return "中偏高"
    if (ia, ib) == (1, 2):
        return "中偏低"
    return "%s至%s" % (a, b)


def percentile(sorted_vals, p):
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = (len(sorted_vals) - 1) * p
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = pos - lo
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * frac


def rebuild(item, sids):
    """按 series 把若干会话重新聚合成 pooled raw。"""
    pool = item.get("pool")
    series = item.get("series") or {}
    picked = [series[s] for s in sids if s in series]
    if not picked:
        return None
    if pool == "ratio":
        num = sum(float(s.get("num", 0)) for s in picked)
        den = sum(float(s.get("den", 0)) for s in picked)
        if not den:
            return None
        return (num / den) * float(item.get("scale", 1))
    if pool == "median":
        vals = [float(v) for s in picked for v in s.get("values", [])]
        return statistics.median(vals) if vals else None
    if pool == "mean":
        n = sum(float(s.get("n", 0)) for s in picked)
        total = sum(float(s.get("sum", 0.0)) for s in picked)
        return (total / n) if n else None
    return None


def compute(items_scores, spec):
    acc = 0.0
    tw = 0.0
    cov = 0.0
    for key, w in spec["items"].items():
        s = items_scores.get(key)
        if s is None:
            continue
        acc += w * s
        tw += w
        cov += w
    score = (acc / tw) if tw else None
    if cov < 0.6:
        score = None
    return score, cov


def run(in_dir, out_dir, assets_dir, B, seed):
    feats = load_json(os.path.join(in_dir, "features.json"))
    weights = load_json(os.path.join(assets_dir, "weights.v0.json"))
    anchors_doc = load_json(os.path.join(assets_dir, "anchors.v0.json"))
    anchors = anchors_doc["anchors"]

    meta = feats.get("meta") or {}
    grade = meta.get("grade") or "D"
    warnings = []
    if grade == "D":
        die("样本不足以出分（grade D：%s 条 / %s 天）。只可做定性描述或建议用户提供更多记录。"
            % (meta.get("messages"), meta.get("span_days")), 3)

    fmap = feats.get("features") or {}
    sids = sorted({sid for item in fmap.values() for sid in (item.get("series") or {})})

    if grade == "C":
        out = {
            "version": "0.1.0",
            "grade": "C",
            "confidence": "低",
            "note": "样本量只够 L1 事实，不出维度分。",
            "dims": {},
            "warnings": ["grade C：不输出分数"],
            "bootstrap": {"B": 0, "sessions": len(sids), "seed": seed},
        }
        write_out(out_dir, out)
        return out

    dims = {}
    for key in weights["dims"]:
        spec = weights["dims"][key]
        raw_by_key = {}
        n_by_key = {}
        item_scores = {}
        item_raw = {}
        for item_key in spec["items"]:
            item = fmap.get(item_key)
            if not item:
                raw_by_key[item_key] = None
                n_by_key[item_key] = 0
                item_scores[item_key] = None
                continue
            raw = item.get("value")
            raw_by_key[item_key] = raw
            n_by_key[item_key] = item.get("n")
            item_scores[item_key] = interp(anchors.get(item_key, []), raw)
            item_raw[item_key] = raw

        score, cov = compute(item_scores, spec)

        rng = range_low = range_high = None
        if B > 0 and len(sids) >= 8:
            samples = []
            r = random.Random(seed)
            for _ in range(B):
                pick = [r.choice(sids) for _ in range(len(sids))]
                rebuilt = {}
                for item_key in spec["items"]:
                    item = fmap.get(item_key)
                    rebuilt[item_key] = None if not item else interp(
                        anchors.get(item_key, []), rebuild(item, pick))
                s, _ = compute(rebuilt, spec)
                if s is not None:
                    samples.append(s)
            if len(samples) >= 50:
                samples.sort()
                range_low = round(percentile(samples, 0.10), 1)
                range_high = round(percentile(samples, 0.90), 1)
            else:
                warnings.append("%s：有效重采样不足，未给波动范围" % spec["label"])
        elif B > 0:
            warnings.append("%s：会话数 <8，未做 bootstrap" % spec["label"])

        # 敏感性：删 30% 会话
        sens = 0.0
        if len(sids) >= 4:
            for s in range(1, 6):
                rr = random.Random(s)
                k = max(1, int(round(len(sids) * 0.3)))
                drop = set(rr.sample(sids, k))
                keep = [x for x in sids if x not in drop]
                rebuilt = {}
                for item_key in spec["items"]:
                    item = fmap.get(item_key)
                    rebuilt[item_key] = None if not item else interp(
                        anchors.get(item_key, []), rebuild(item, keep))
                s2, _ = compute(rebuilt, spec)
                if score is not None and s2 is not None:
                    sens = max(sens, abs(score - s2))
        stability = "high" if sens <= 8 else ("medium" if sens <= 15 else "low")

        item_out = {}
        for item_key in spec["items"]:
            item_out[item_key] = {
                "weight": spec["items"][item_key],
                "raw": (round(item_raw[item_key], 4)
                        if isinstance(item_raw.get(item_key), float) else item_raw.get(item_key)),
                "score": (round(item_scores.get(item_key), 1)
                          if item_scores.get(item_key) is not None else None),
                "n": n_by_key.get(item_key),
            }

        dims[key] = {
            "label": spec["label"],
            "score": round(score, 1) if score is not None else None,
            "band": band_label(score, range_low, range_high),
            "range": [range_low, range_high] if range_low is not None else None,
            "coverage": round(cov, 2),
            "stability": stability,
            "sensitivity": round(sens, 1),
            "items": item_out,
        }
        if score is None:
            warnings.append("%s：有效项覆盖不足（<0.6），不出分" % spec["label"])
        elif stability == "low":
            warnings.append("%s：去掉 30%% 会话后波动 %.1f 分，稳定性低" % (spec["label"], sens))

    out = {
        "version": "0.1.0",
        "grade": grade,
        "confidence": "高" if grade == "A" else "中",
        "dims": dims,
        "warnings": warnings,
        "bootstrap": {"B": B if len(sids) >= 8 else 0, "sessions": len(sids), "seed": seed},
    }
    write_out(out_dir, out)
    return out


def write_out(out_dir, out):
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "score.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    sys.stdout.write("已写出 %s\n" % path)


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except AttributeError:
            pass
    ap = argparse.ArgumentParser(
        description="把 features.json 折算成五维分（v0 先验权重与锚点）。")
    ap.add_argument("--in", dest="in_dir", required=True, help="包含 features.json 的目录")
    ap.add_argument("--out", dest="out_dir", required=True, help="输出 score.json 的目录")
    ap.add_argument("--assets", default=DEFAULT_ASSETS, help="weights/anchors 所在目录")
    ap.add_argument("--bootstrap", type=int, default=1000, help="bootstrap 次数，默认 1000")
    ap.add_argument("--seed", type=int, default=42, help="bootstrap 随机种子，默认 42")
    args = ap.parse_args()
    run(args.in_dir, args.out_dir, args.assets, max(0, args.bootstrap), args.seed)


if __name__ == "__main__":
    main()
