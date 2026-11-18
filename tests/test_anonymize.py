# -*- coding: utf-8 -*-
"""anonymize.py 的单元测试。"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPT = os.path.join(ROOT, "skills", "chat-persona", "scripts", "anonymize.py")
PY = sys.executable

ROWS = [
    {"i": 0, "session_id": "S001", "sender": "张三", "is_me": True,
     "ts": "2024-01-01T20:00:00+08:00",
     "text": "我手机13812345678，证件110101199001011234，邮箱a@b.com，看https://x.test/a",
     "type": "text", "raw_ts": ""},
    {"i": 1, "session_id": "S001", "sender": "李四", "is_me": False,
     "ts": "2024-01-01T20:01:00+08:00",
     "text": "卡号6222021234567890123 转我", "type": "text", "raw_ts": ""},
    {"i": 2, "session_id": "S001", "sender": "张三", "is_me": True,
     "ts": "2024-01-01T20:02:00+08:00", "text": "@小明 你好", "type": "text", "raw_ts": ""},
    {"i": 3, "session_id": "S002", "sender": "李四", "is_me": False,
     "ts": "2024-01-02T09:00:00+08:00", "text": "我确诊了，最近很焦虑",
     "type": "text", "raw_ts": ""},
    {"i": 4, "session_id": "S002", "sender": "张三", "is_me": True,
     "ts": "2024-01-02T09:01:00+08:00", "text": "王五也来", "type": "text", "raw_ts": ""},
]


def setup(rows=None):
    d = tempfile.mkdtemp(prefix="cp_anon_")
    with open(os.path.join(d, "messages.jsonl"), "w", encoding="utf-8") as f:
        for r in (rows or ROWS):
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return d


def run(d, *extra):
    p = subprocess.run(
        [PY, SCRIPT, "--in", os.path.join(d, "messages.jsonl"), "--out", d] + list(extra),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return p.returncode, p.stdout, p.stderr


def read_out(d):
    rows = []
    with open(os.path.join(d, "messages.anon.jsonl"), encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    with open(os.path.join(d, "anonymize_report.json"), encoding="utf-8") as f:
        rep = json.load(f)
    return rows, rep


def test_mask_and_map():
    d = setup()
    try:
        names = os.path.join(d, "names.txt")
        with open(names, "w", encoding="utf-8") as f:
            f.write("王五\n")
        code, so, se = run(d, "--name-list", names)
        assert code == 0, se
        rows, rep = read_out(d)
        blob = "\n".join(r["text"] for r in rows)
        for bad in ("13812345678", "110101199001011234", "a@b.com", "https://", "6222021234567890123", "小明", "王五"):
            assert bad not in blob, bad
        assert rep["sender_map"] == {"张三": "我", "李四": "对方A"}, rep["sender_map"]
        assert rows[0]["sender"] == "我"
        assert rows[1]["sender"] == "对方A"
        assert rep["masked"]["手机"] == 1, rep["masked"]
        assert rep["masked"]["证件"] == 1, rep["masked"]
        assert rep["masked"]["邮箱"] == 1, rep["masked"]
        assert rep["masked"]["链接"] == 1, rep["masked"]
        assert rep["masked"]["卡号"] == 1, rep["masked"]
        assert rep["masked"]["提及"] == 1, rep["masked"]
        assert rep["masked"]["姓名"] == 1, rep["masked"]
        assert rep["sensitive_messages"] == 1, rep["sensitive_messages"]
        assert rep["safety_notice"] is None
        assert len(rows) == 5
        assert rows[0]["session_id"] == "S001"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_drop_sensitive():
    d = setup()
    try:
        code, so, se = run(d, "--drop-sensitive")
        assert code == 0, se
        rows, rep = read_out(d)
        assert rep["dropped"] == 1, rep
        assert len(rows) == 4
        assert all("确诊" not in r["text"] for r in rows)
        assert [r["i"] for r in rows] == [0, 1, 2, 3]
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_crisis_notice():
    rows = [dict(ROWS[0], text="他昨天家暴了我")]
    d = setup(rows)
    try:
        code, so, se = run(d)
        assert code == 0, se
        _, rep = read_out(d)
        assert rep["safety_notice"], rep
        assert "紧急服务" in rep["safety_notice"]
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_no_me():
    rows = [dict(r, is_me=None) for r in ROWS]
    d = setup(rows)
    try:
        code, so, se = run(d)
        assert code == 0, se
        rows_out, rep = read_out(d)
        assert rep["me_found"] is False
        assert set(rep["sender_map"].values()) == {"对方A", "对方B"}, rep["sender_map"]
        assert rep["warnings"]
        assert rows_out[0]["sender"] == "对方A"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_bad_input():
    d = tempfile.mkdtemp(prefix="cp_anon_")
    try:
        with open(os.path.join(d, "messages.jsonl"), "w", encoding="utf-8") as f:
            f.write("not json\n")
        code, so, se = run(d)
        assert code == 3, code
    finally:
        shutil.rmtree(d, ignore_errors=True)
