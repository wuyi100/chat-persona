# -*- coding: utf-8 -*-
"""端到端：合成一份 650 条、20 天的微信格式记录，跑完 6 个脚本并检查报告。"""

import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPTS = os.path.join(ROOT, "skills", "chat-persona", "scripts")
PY = sys.executable

ME = "张三"
OTHER = "李四"
ME_TEXTS = ["在吗", "明天一起吃饭吧", "好的，没问题", "哈哈哈哈太开心了！", "我觉得可以",
            "那你安排一下时间", "今天有点累", "收到", "周末有安排吗", "这个方案我同意"]
OTHER_TEXTS = ["在的", "可以啊", "好", "嗯嗯", "我看看", "怎么了", "行，听你的",
               "这周有点忙", "改天吧", "哈哈"]

BANNED = ["保证", "一定", "准确率", "诊断", "你就是", "天生", "性格类型", "MBTI",
          "心理测试", "科学证明", "超过 X%"]


def write_log(path, total=650, days=20):
    per_day = total // days
    start = dt.datetime(2024, 1, 1, 9, 0, 0)
    lines = []
    for i in range(total):
        day = i // per_day
        k = i % per_day
        ts = start + dt.timedelta(days=day, minutes=5 * k)
        me = (i % 2 == 0)
        sender = ME if me else OTHER
        text = (ME_TEXTS if me else OTHER_TEXTS)[i % len(ME_TEXTS if me else OTHER_TEXTS)]
        lines.append("%s %s" % (ts.strftime("%Y-%m-%d %H:%M:%S"), sender))
        lines.append(text)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def run(args):
    p = subprocess.run([PY] + args, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return p.returncode, p.stdout, p.stderr


def pipeline(work, total=650, days=20):
    write_log(os.path.join(work, "input.txt"), total, days)
    steps = [
        [os.path.join(SCRIPTS, "parse_chat.py"), "--in", os.path.join(work, "input.txt"),
         "--out", work, "--me", ME],
        [os.path.join(SCRIPTS, "anonymize.py"), "--in", os.path.join(work, "messages.jsonl"),
         "--out", work],
        [os.path.join(SCRIPTS, "features.py"), "--in", work, "--out", work],
        [os.path.join(SCRIPTS, "score.py"), "--in", work, "--out", work, "--bootstrap", "200"],
        [os.path.join(SCRIPTS, "evidence.py"), "--in", work, "--out", work],
        [os.path.join(SCRIPTS, "render_report.py"), "--in", work, "--out", work],
    ]
    for args in steps:
        code, so, se = run(args)
        assert code == 0, "%s 失败：%s" % (os.path.basename(args[0]), se)


def load(work, name):
    with open(os.path.join(work, name), encoding="utf-8") as f:
        return json.load(f)


def test_e2e_grade_b():
    work = tempfile.mkdtemp(prefix="cp_e2e_")
    try:
        pipeline(work)
        score = load(work, "score.json")
        assert score["grade"] == "B", score["grade"]
        assert len(score["dims"]) == 5
        for key, d in score["dims"].items():
            assert d["score"] is not None, key
            assert d["band"], key
            assert d["range"] and len(d["range"]) == 2, key
            lo, hi = d["range"]
            # 波动带必须围绕主分（曾因密度类 scale 口径不一致出现 54 分/18–18 带）
            assert hi - lo <= 40, (key, d["range"])
            assert abs((lo + hi) / 2.0 - d["score"]) <= 20, (key, d["score"], d["range"])

        ev = load(work, "evidence.json")
        assert len(ev["evidence"]) >= 3
        assert ev["evidence"][0]["id"] == "E1"
        assert sum(1 for e in ev["evidence"] if e["snippet"]) <= 3

        with open(os.path.join(work, "report.md"), encoding="utf-8") as f:
            report = f.read()
        for sec in ["## 1. 数据范围", "## 2. 事实速览", "## 3. 沟通风格分档",
                    "## 4. 三条结论", "## 5. 一个反差", "## 6. 限制与删除"]:
            assert sec in report, sec
        assert re.search(r"（E\d+）", report), "结论里应引用证据编号"
        assert "删除" in report and "工作目录" in report
        assert ME not in report and OTHER not in report
        assert not re.search(r"1[3-9]\d{9}", report)
        for w in BANNED:
            assert w not in report, w
        assert "总分" not in report and "排名" not in report and "百分位" not in report
        assert len(re.findall(r"^\| ", report, re.M)) >= 6  # 表头 + 5 维
    finally:
        shutil.rmtree(work, ignore_errors=True)


def test_e2e_grade_c_no_scores():
    work = tempfile.mkdtemp(prefix="cp_e2e_")
    try:
        pipeline(work, total=260, days=9)
        score = load(work, "score.json")
        assert score["grade"] == "C", score["grade"]
        assert score["dims"] == {}
        with open(os.path.join(work, "report.md"), encoding="utf-8") as f:
            report = f.read()
        assert "只出事实，不出维度分" in report
        assert "样本量不足，本次不形成结论" in report
    finally:
        shutil.rmtree(work, ignore_errors=True)
