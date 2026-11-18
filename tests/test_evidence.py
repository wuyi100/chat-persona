# -*- coding: utf-8 -*-
"""evidence.py 的单元测试：贡献度排序、snippet 预算与脱敏、反差门槛。"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPT = os.path.join(ROOT, "skills", "chat-persona", "scripts", "evidence.py")
PY = sys.executable

MSGS = [
    # i, session, me, ts, text, sensitive
    (0, "S01", True, "2024-01-01T20:00:00+08:00", "在吗", False),
    (1, "S01", False, "2024-01-01T20:01:00+08:00", "在", False),
    (2, "S01", True, "2024-01-01T20:02:00+08:00", "明天一起吃饭吧", False),
    (3, "S01", True, "2024-01-01T20:03:00+08:00", "哈哈哈哈太开心了！！！", False),
    (4, "S02", False, "2024-01-02T09:00:00+08:00", "早", False),
    (5, "S02", True, "2024-01-02T09:01:00+08:00", "早啊", False),
    (6, "S03", True, "2024-01-03T21:00:00+08:00", "不对，我不同意，电话13800001111", True),
    (7, "S03", False, "2024-01-03T21:01:00+08:00", "为什么", False),
    (8, "S03", True, "2024-01-03T21:02:00+08:00", "不对，我不同意这个说法", False),
    (9, "S04", True, "2024-01-04T23:30:00+08:00", "还没睡呢", False),
    (10, "S04", False, "2024-01-04T23:31:00+08:00", "嗯", False),
    (11, "S05", True, "2024-01-05T10:00:00+08:00", "好的，没问题", False),
]

FEATURE_VALUES = {
    "initiation_ratio": (0.5, "ratio"),
    "bursts_per_session": (2.0, "mean"),
    "reply_latency_median_s": (600.0, "median"),
    "night_ratio": (0.1, "ratio"),
    "char_diversity_500": (0.16, "mean"),
    "question_ratio": (0.2, "ratio"),
    "turn_depth_mean": (4.0, "mean"),
    "agree_ratio": (0.05, "ratio"),
    "disagree_ratio": (0.1, "ratio"),
    "response_coverage": (0.8, "ratio"),
    "structure_score": (0.6, "ratio"),
    "plan_density": (0.1, "ratio"),
    "emotion_density": (2.0, "ratio"),
    "intensity_density": (2.0, "ratio"),
}


def make_work(d, dims):
    features = {}
    sids = ["S01", "S02"]
    for key, (v, pool) in FEATURE_VALUES.items():
        if pool == "ratio":
            series = {s: {"num": int(round(v * 10)), "den": 10} for s in sids}
        elif pool == "median":
            series = {s: {"values": [v]} for s in sids}
        else:
            series = {s: {"sum": v, "n": 1} for s in sids}
        features[key] = {"value": v, "unit": "", "pool": pool, "n": 2, "series": series}
    with open(os.path.join(d, "features.json"), "w", encoding="utf-8") as f:
        json.dump({"meta": {}, "l1": {}, "features": features, "missing": []},
                  f, ensure_ascii=False)
    with open(os.path.join(d, "score.json"), "w", encoding="utf-8") as f:
        json.dump({"version": "0.1.0", "grade": "B", "confidence": "中", "dims": dims},
                  f, ensure_ascii=False)
    with open(os.path.join(d, "messages.anon.jsonl"), "w", encoding="utf-8") as f:
        for i, sid, me, ts, text, sens in MSGS:
            f.write(json.dumps({
                "i": i, "session_id": sid, "sender": "我" if me else "对方A",
                "is_me": me, "ts": ts, "text": text, "type": "text",
                "sensitive": sens,
            }, ensure_ascii=False) + "\n")


def dim(label, score, items):
    return {"label": label, "score": score, "band": None, "range": None,
            "coverage": 1.0, "stability": "high", "sensitivity": 0.0,
            "items": {k: {"weight": w, "raw": None, "score": s, "n": 2}
                      for k, (w, s) in items.items()}}


def run(d):
    p = subprocess.run([PY, SCRIPT, "--in", d, "--out", d],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p.returncode, p.stdout, p.stderr


def load(d):
    with open(os.path.join(d, "evidence.json"), encoding="utf-8") as f:
        return json.load(f)


def standard_dims():
    return {
        "extraversion": dim("社交主动性", 72.5, {
            "initiation_ratio": (0.30, 85), "reply_latency_median_s": (0.25, 55),
            "bursts_per_session": (0.25, 80), "night_ratio": (0.20, 60)}),
        "openness": dim("探索开放度", 30.0, {
            "char_diversity_500": (0.40, 20), "question_ratio": (0.30, 35),
            "turn_depth_mean": (0.30, 30)}),
        "agreeableness": dim("回应亲和度", 55.0, {
            "agree_ratio": (0.40, 50), "disagree_ratio": (0.30, 62),
            "response_coverage": (0.30, 52)}),
        "conscientiousness": {"label": "条理规划度", "score": None, "items": {
            "structure_score": {"weight": 0.5, "raw": None, "score": None, "n": 2}}},
        "expressiveness": dim("情绪外显度", 50.0, {
            "emotion_density": (0.50, 50), "intensity_density": (0.50, 50)}),
    }


def test_evidence_and_contrast():
    d = tempfile.mkdtemp(prefix="cp_evi_")
    try:
        make_work(d, standard_dims())
        code, so, se = run(d)
        assert code == 0, se
        data = load(d)
        assert len(data["evidence"]) == 6, data["evidence"]
        assert [e["id"] for e in data["evidence"]] == ["E1", "E2", "E3", "E4", "E5", "E6"]
        assert data["by_dim"]["extraversion"] == ["E1", "E2"]
        assert data["contrast"] is not None
        assert data["contrast"]["high"] == "extraversion"
        assert data["contrast"]["low"] == "openness"
        assert data["contrast"]["ids"] == ["E1", "E3"]

        labels = [i["dim"] for i in data["insufficient"]]
        assert "conscientiousness" in labels
        assert "expressiveness" in labels

        e1 = data["evidence"][0]
        assert e1["feature"] == "initiation_ratio"
        assert e1["direction"] == "high"
        assert e1["claim"] == "你更常先开口"
        assert "10/20" in e1["stat"] and "%" in e1["stat"]
        assert e1["snippet"] == "在吗"

        snippets = [e["snippet"] for e in data["evidence"] if e["snippet"]]
        assert len(snippets) <= 3
        assert all(len(s) <= 41 for s in snippets)
        assert not any("138" in s for s in snippets)
        assert "不对，我不同意这个说法" in snippets
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_no_contrast_when_close():
    d = tempfile.mkdtemp(prefix="cp_evi_")
    try:
        dims = standard_dims()
        dims["openness"]["score"] = 45.0
        make_work(d, dims)
        code, so, se = run(d)
        assert code == 0, se
        assert load(d)["contrast"] is None
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_snippet_budget():
    d = tempfile.mkdtemp(prefix="cp_evi_")
    try:
        dims = {
            "extraversion": dim("社交主动性", 80, {"initiation_ratio": (1.0, 80)}),
            "openness": dim("探索开放度", 80, {"question_ratio": (1.0, 80)}),
            "agreeableness": dim("回应亲和度", 80, {"agree_ratio": (1.0, 80)}),
            "conscientiousness": dim("条理规划度", 80, {"plan_density": (1.0, 80)}),
            "expressiveness": dim("情绪外显度", 80, {"emotion_density": (1.0, 80)}),
        }
        make_work(d, dims)
        code, so, se = run(d)
        assert code == 0, se
        data = load(d)
        assert len(data["evidence"]) == 5
        assert sum(1 for e in data["evidence"] if e["snippet"]) == 3
    finally:
        shutil.rmtree(d, ignore_errors=True)
