# -*- coding: utf-8 -*-
"""parse_chat.py 的单元测试（纯标准库）。"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPTS = os.path.join(ROOT, "skills", "chat-persona", "scripts")
FIX = os.path.join(HERE, "fixtures")
PY = sys.executable
SCRIPT = os.path.join(SCRIPTS, "parse_chat.py")


def run(*args):
    p = subprocess.run(
        [PY, SCRIPT] + list(args),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return p.returncode, p.stdout, p.stderr


def parse(fixture, *extra):
    out = tempfile.mkdtemp(prefix="cp_parse_")
    code, so, se = run("--in", os.path.join(FIX, fixture), "--out", out, *extra)
    assert code == 0, "exit %d\nSTDOUT:\n%s\nSTDERR:\n%s" % (code, so, se)
    with open(os.path.join(out, "parse_report.json"), encoding="utf-8") as f:
        rep = json.load(f)
    msgs = []
    with open(os.path.join(out, "messages.jsonl"), encoding="utf-8") as f:
        for line in f:
            if line.strip():
                msgs.append(json.loads(line))
    return out, rep, msgs


def cleanup(d):
    shutil.rmtree(d, ignore_errors=True)


def test_whatsapp():
    d, rep, msgs = parse("whatsapp.txt")
    try:
        assert rep["format"] == "whatsapp_bracket", rep["format"]
        assert rep["messages"] == 4, rep["messages"]
        assert rep["sessions"] == 2, rep["sessions"]
        assert rep["span_days"] == 2, rep["span_days"]
        assert rep["senders"][0]["label"] == "张三", rep["senders"]
        assert msgs[0]["ts"].startswith("2024-01-01T20:00:00"), msgs[0]["ts"]
        assert rep["unparsed_lines"] == 0, rep["unparsed_samples"]
    finally:
        cleanup(d)


def test_wechat_two_line():
    d, rep, msgs = parse("wechat.txt", "--me", "张三")
    try:
        assert rep["format"] == "date_time_sender", rep["format"]
        assert rep["messages"] == 4, rep["messages"]
        assert rep["media_messages"] == 1, rep["media_messages"]
        assert rep["sessions"] == 1, rep["sessions"]
        assert rep["me"] == "张三"
        assert msgs[3]["type"] == "media", msgs[3]
        assert msgs[0]["is_me"] is True
        assert msgs[1]["is_me"] is False
    finally:
        cleanup(d)


def test_qq_tail_number():
    d, rep, msgs = parse("qq.txt", "--me", "1")
    try:
        assert rep["messages"] == 3, rep["messages"]
        assert {s["label"] for s in rep["senders"]} == {"张三", "李四"}, rep["senders"]
        assert [m["is_me"] for m in msgs] == [True, False, True], [m["is_me"] for m in msgs]
    finally:
        cleanup(d)


def test_telegram_json():
    d, rep, msgs = parse("tg.json", "--me", "张三")
    try:
        assert rep["format"] == "telegram", rep["format"]
        assert rep["messages"] == 4, rep["messages"]
        assert rep["text_messages"] == 2, rep["text_messages"]
        assert rep["media_messages"] == 1, rep["media_messages"]
        assert rep["system_messages"] == 1, rep["system_messages"]
        assert "看这个" in msgs[1]["text"], msgs[1]["text"]
    finally:
        cleanup(d)


def test_tsv():
    d, rep, msgs = parse("table.tsv")
    try:
        assert rep["format"] == "tsv", rep["format"]
        assert rep["messages"] == 2, rep["messages"]
        assert msgs[0]["sender"] == "张三"
        assert msgs[1]["sender"] == "李四"
    finally:
        cleanup(d)


def test_colon_no_timestamp():
    d, rep, msgs = parse("colon.txt")
    try:
        assert rep["format"] == "colon", rep["format"]
        assert rep["messages"] == 3, rep["messages"]
        assert rep["has_timestamps"] is False
        assert rep["sessions"] == 1, rep["sessions"]
        assert any("无时间戳" in w for w in rep["warnings"]), rep["warnings"]
    finally:
        cleanup(d)


def test_cn3():
    d, rep, msgs = parse("wechat_cn3.txt")
    try:
        assert rep["format"] == "cn_date_3line", rep["format"]
        assert rep["messages"] == 4, rep["messages"]
        assert msgs[0]["ts"].startswith("2024-01-01T20:00:00"), msgs[0]["ts"]
    finally:
        cleanup(d)


def test_list_senders():
    code, so, se = run("--in", os.path.join(FIX, "qq.txt"), "--list-senders")
    assert code == 0, se
    assert "张三" in so and "李四" in so, so
    assert "1." in so, so


def test_bad_me():
    out = tempfile.mkdtemp(prefix="cp_parse_")
    try:
        code, so, se = run("--in", os.path.join(FIX, "qq.txt"), "--out", out, "--me", "王五")
        assert code == 2, code
        assert "王五" in se, se
    finally:
        cleanup(out)


def test_missing_file():
    code, so, se = run("--in", os.path.join(FIX, "nope.txt"), "--out",
                       tempfile.mkdtemp(prefix="cp_parse_"))
    assert code == 2, code
