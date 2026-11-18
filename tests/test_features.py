# -*- coding: utf-8 -*-
"""features.py 的单元测试：用手算得到的合成会话验证 14 项特征。"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPT = os.path.join(ROOT, "skills", "chat-persona", "scripts", "features.py")
PY = sys.executable

CORE = [
    ("S001", "2024-01-01T20:00:00+08:00", True, "在吗"),
    ("S001", "2024-01-01T20:01:00+08:00", False, "在"),
    ("S001", "2024-01-01T20:02:00+08:00", True, "明天一起吃饭吗"),
    ("S001", "2024-01-01T20:03:00+08:00", True, "我请客"),
    ("S001", "2024-01-01T20:10:00+08:00", False, "好啊"),
    ("S001", "2024-01-01T20:11:00+08:00", True, "那说定了"),
    ("S002", "2024-01-02T09:00:00+08:00", False, "早"),
    ("S002", "2024-01-02T09:05:00+08:00", True, "早啊"),
]

TOL = 1e-6


def write_rows(d, rows):
    path = os.path.join(d, "messages.anon.jsonl")
    with open(path, "w", encoding="utf-8") as f:
        for i, (sid, ts, me, text) in enumerate(rows):
            f.write(json.dumps({
                "i": i, "session_id": sid, "sender": "我" if me else "对方A",
                "is_me": me, "ts": ts, "text": text, "type": "text", "raw_ts": "",
            }, ensure_ascii=False) + "\n")
    return path


def run(d, path):
    p = subprocess.run(
        [PY, SCRIPT, "--in", path, "--out", d],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return p.returncode, p.stdout, p.stderr


def load(d):
    with open(os.path.join(d, "features.json"), encoding="utf-8") as f:
        return json.load(f)


def test_core_values():
    d = tempfile.mkdtemp(prefix="cp_feat_")
    try:
        path = write_rows(d, CORE)
        code, so, se = run(d, path)
        assert code == 0, se
        data = load(d)
        f = data["features"]
        assert data["meta"]["messages"] == 8
        assert data["meta"]["sessions"] == 2
        assert data["meta"]["span_days"] == 2
        assert data["meta"]["grade"] == "D", data["meta"]

        def near(key, want):
            assert key in f, "missing " + key
            got = f[key]["value"]
            assert abs(got - want) < TOL, "%s: got %r want %r" % (key, got, want)

        near("initiation_ratio", 0.5)
        near("reply_latency_median_s", 60.0)
        near("bursts_per_session", 2.0)
        near("night_ratio", 0.0)
        near("question_ratio", 0.4)
        near("turn_depth_mean", 3.5)
        near("agree_ratio", 0.0)
        near("disagree_ratio", 0.0)
        near("response_coverage", 1.0)
        near("structure_score", 0.0)
        near("plan_density", 0.2)
        near("emotion_density", 0.0)
        near("intensity_density", 0.0)

        assert any(m["key"] == "char_diversity_500" for m in data["missing"]), data["missing"]
        assert abs(data["l1"]["median_reply_s"] - 60.0) < TOL
        assert abs(data["l1"]["median_burst_chars"] - 3.0) < TOL
        assert abs(data["l1"]["my_share"] - 5.0 / 8) < TOL

        # series 结构可用于 bootstrap
        it = f["initiation_ratio"]
        assert it["pool"] == "ratio"
        assert it["series"]["S001"] == {"num": 1, "den": 1}
        assert it["series"]["S002"] == {"num": 0, "den": 1}
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_diversity_exact():
    d = tempfile.mkdtemp(prefix="cp_feat_")
    try:
        chars = "".join(chr(0x4E00 + i) for i in range(59)) + "一" * 41
        path = write_rows(d, [
            ("S001", "2024-01-01T20:00:00+08:00", False, "hi"),
            ("S001", "2024-01-01T20:01:00+08:00", True, chars),
        ])
        code, so, se = run(d, path)
        assert code == 0, se
        data = load(d)
        assert "char_diversity_500" in data["features"], data["missing"]
        got = data["features"]["char_diversity_500"]["value"]
        assert abs(got - 0.59) < TOL, got
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_reject_group():
    d = tempfile.mkdtemp(prefix="cp_feat_")
    try:
        path = os.path.join(d, "messages.anon.jsonl")
        with open(path, "w", encoding="utf-8") as f:
            for i, (who, me) in enumerate([("我", True), ("对方A", False), ("对方B", False)]):
                f.write(json.dumps({
                    "i": i, "session_id": "S001", "sender": who, "is_me": me,
                    "ts": "2024-01-01T20:0%d:00+08:00" % i, "text": "hi", "type": "text",
                }, ensure_ascii=False) + "\n")
        code, so, se = run(d, path)
        assert code == 2, code
        assert "一对一" in se, se
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_reject_no_me():
    d = tempfile.mkdtemp(prefix="cp_feat_")
    try:
        path = os.path.join(d, "messages.anon.jsonl")
        with open(path, "w", encoding="utf-8") as f:
            for i in range(2):
                f.write(json.dumps({
                    "i": i, "session_id": "S001", "sender": "对方A", "is_me": None,
                    "ts": "2024-01-01T20:0%d:00+08:00" % i, "text": "hi", "type": "text",
                }, ensure_ascii=False) + "\n")
        code, so, se = run(d, path)
        assert code == 2, code
        assert "未指认" in se, se
    finally:
        shutil.rmtree(d, ignore_errors=True)
