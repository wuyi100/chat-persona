# -*- coding: utf-8 -*-
"""score.py 的单元测试：手工构造 features.json，验证加权、插值、bootstrap 与分级。"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPT = os.path.join(ROOT, "skills", "chat-persona", "scripts", "score.py")
PY = sys.executable
TOL = 0.05

VALS = {
    "initiation_ratio": (0.45, "ratio"),
    "reply_latency_median_s": (900.0, "median"),
    "bursts_per_session": (3.5, "mean"),
    "night_ratio": (0.12, "ratio"),
    "char_diversity_500": (0.16, "mean"),
    "question_ratio": (0.12, "ratio"),
    "turn_depth_mean": (6.0, "mean"),
    "agree_ratio": (0.08, "ratio"),
    "disagree_ratio": (0.05, "ratio"),
    "response_coverage": (0.7, "ratio"),
    "structure_score": (0.5, "ratio"),
    "plan_density": (0.05, "ratio"),
    "emotion_density": (1.5, "ratio"),
    "intensity_density": (1.5, "ratio"),
}


def make_features(d, grade="B", drop=(), override=None):
    override = override or {}
    sids = ["S%02d" % i for i in range(1, 13)]
    features = {}
    for key, (value, pool) in VALS.items():
        if key in drop:
            continue
        v = override.get(key, value)
        if pool == "ratio":
            num = int(round(v * 100))
            series = {s: {"num": num, "den": 100} for s in sids}
        elif pool == "median":
            series = {s: {"values": [float(v)]} for s in sids}
        else:
            series = {s: {"sum": float(v), "n": 1} for s in sids}
        features[key] = {
            "value": v, "unit": "", "pool": pool, "n": len(sids), "series": series,
        }
    data = {
        "meta": {"messages": 900, "sessions": len(sids), "span_days": 20,
                 "partners": 1, "grade": grade, "me_text_messages": 500},
        "l1": {},
        "features": features,
        "missing": [],
    }
    with open(os.path.join(d, "features.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def run(d, *extra):
    p = subprocess.run(
        [PY, SCRIPT, "--in", d, "--out", d] + list(extra),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return p.returncode, p.stdout, p.stderr


def load(d):
    with open(os.path.join(d, "score.json"), encoding="utf-8") as f:
        return json.load(f)


def test_weights_and_bootstrap():
    d = tempfile.mkdtemp(prefix="cp_score_")
    try:
        make_features(d)
        code, so, se = run(d, "--bootstrap", "200")
        assert code == 0, se
        data = load(d)
        dims = data["dims"]
        expect = {
            "extraversion": 65.25,
            "openness": 51.5,
            "agreeableness": 51.5,
            "conscientiousness": 57.5,
            "expressiveness": 60.0,
        }
        for k, want in expect.items():
            got = dims[k]["score"]
            assert abs(got - want) < TOL, "%s: %r != %r" % (k, got, want)
            assert dims[k]["coverage"] == 1.0
            assert dims[k]["stability"] == "high", dims[k]
            assert len(dims[k]["range"]) == 2
            assert abs(dims[k]["range"][0] - want) < TOL
        assert dims["extraversion"]["band"] == "偏高"
        assert data["confidence"] == "中"
        assert data["grade"] == "B"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_partial_coverage_renormalizes():
    d = tempfile.mkdtemp(prefix="cp_score_")
    try:
        make_features(d, drop=("night_ratio",))
        code, so, se = run(d, "--bootstrap", "50")
        assert code == 0, se
        dim = load(d)["dims"]["extraversion"]
        assert abs(dim["coverage"] - 0.8) < 1e-9
        assert abs(dim["score"] - 66.6) < 0.1, dim["score"]
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_low_coverage_nulls_dimension():
    d = tempfile.mkdtemp(prefix="cp_score_")
    try:
        make_features(d, drop=("initiation_ratio", "reply_latency_median_s",
                               "bursts_per_session"))
        code, so, se = run(d, "--bootstrap", "50")
        assert code == 0, se
        dim = load(d)["dims"]["extraversion"]
        assert dim["score"] is None
        assert dim["coverage"] < 0.6
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_clamp_at_anchor_ends():
    d = tempfile.mkdtemp(prefix="cp_score_")
    try:
        make_features(d, override={"initiation_ratio": 5.0})
        code, so, se = run(d, "--bootstrap", "0")
        assert code == 0, se
        assert abs(load(d)["dims"]["extraversion"]["score"] - 75.75) < TOL

        make_features(d, override={"initiation_ratio": -1.0})
        code, so, se = run(d, "--bootstrap", "0")
        assert code == 0, se
        assert abs(load(d)["dims"]["extraversion"]["score"] - 48.75) < TOL
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_grade_c_no_scores():
    d = tempfile.mkdtemp(prefix="cp_score_")
    try:
        make_features(d, grade="C")
        code, so, se = run(d)
        assert code == 0, se
        data = load(d)
        assert data["dims"] == {}
        assert "不出维度分" in data["note"]
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_grade_d_refuses():
    d = tempfile.mkdtemp(prefix="cp_score_")
    try:
        make_features(d, grade="D")
        code, so, se = run(d)
        assert code == 3, code
        assert "样本不足" in se
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_grade_d_force_marks_demo():
    """--force：D 级也出分，但必须带 forced 标记与“仅供演示”警告。"""
    d = tempfile.mkdtemp(prefix="cp_score_")
    try:
        make_features(d, grade="D")
        code, so, se = run(d, "--force", "--bootstrap", "0")
        assert code == 0, se
        data = load(d)
        assert data["forced"] is True
        assert data["confidence"] == "低"
        assert data["dims"], "force 后应出分"
        assert "仅供流程演示" in data["warnings"][0], data["warnings"]
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_rebuild_respects_scale():
    """密度类 value 是 ×100 后的口径，rebuild 必须按 scale 还原，否则 bootstrap 与主分不一致。"""
    import importlib.util
    spec = importlib.util.spec_from_file_location("cp_score_mod", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    item = {"value": 4.1667, "pool": "ratio", "scale": 100,
            "series": {"S1": {"num": 3, "den": 74}, "S2": {"num": 3, "den": 70}}}
    raw = m.rebuild(item, ["S1", "S2"])
    assert abs(raw - (6.0 / 144.0) * 100.0) < 1e-9, raw
    plain = {"value": 0.5, "pool": "ratio", "series": {"S1": {"num": 1, "den": 2}}}
    assert abs(m.rebuild(plain, ["S1"]) - 0.5) < 1e-9
    mean_item = {"pool": "mean", "series": {"S1": {"sum": 2.0, "n": 1}, "S2": {"sum": 4.0, "n": 1}}}
    assert abs(m.rebuild(mean_item, ["S1", "S2"]) - 3.0) < 1e-9
