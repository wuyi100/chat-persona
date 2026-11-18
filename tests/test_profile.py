# -*- coding: utf-8 -*-
"""profile.py 一条命令跑通全流程的测试。"""

import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPTS = os.path.join(ROOT, "skills", "chat-persona", "scripts")
PY = sys.executable
PROFILE = os.path.join(SCRIPTS, "profile.py")

ME_TEXTS = ["在吗", "明天一起吃饭吧", "好的，没问题", "哈哈哈哈太开心了！",
            "我觉得可以", "那你安排一下时间", "今天有点累", "收到"]
OTHER_TEXTS = ["在的", "可以啊", "好", "嗯嗯", "我看看", "怎么了", "行，听你的", "改天吧"]


def write_log(path, total, days):
    import datetime as dt
    per_day = max(1, total // days)
    start = dt.datetime(2024, 3, 1, 9, 0, 0)
    lines = []
    for i in range(total):
        day, k = i // per_day, i % per_day
        ts = start + dt.timedelta(days=day, minutes=6 * k)
        me = i % 2 == 0
        sender = "张三" if me else "李四"
        text = (ME_TEXTS if me else OTHER_TEXTS)[i % 8]
        lines.append("%s %s" % (ts.strftime("%Y-%m-%d %H:%M:%S"), sender))
        lines.append(text)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")


def run(args):
    p = subprocess.run([PY, PROFILE] + args, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return p.returncode, p.stdout, p.stderr


def test_full_pipeline_one_command():
    d = tempfile.mkdtemp(prefix="cp_profile_")
    try:
        write_log(os.path.join(d, "raw.txt"), 360, 20)
        code, so, se = run(["--in", d, "--me", "张三", "--bootstrap", "200"])
        assert code == 0, (code, so, se)
        assert os.path.isfile(os.path.join(d, "report.md"))
        with open(os.path.join(d, "report.md"), encoding="utf-8") as f:
            report = f.read()
        for sec in ("## 1. 数据范围", "## 3. 沟通风格分档", "## 6. 限制与删除"):
            assert sec in report, report[:200]
    finally:
        import shutil
        shutil.rmtree(d, ignore_errors=True)


def test_no_me_lists_senders():
    d = tempfile.mkdtemp(prefix="cp_profile_nm_")
    try:
        write_log(os.path.join(d, "raw.txt"), 120, 6)
        code, so, se = run(["--in", d])
        assert code == 0, (code, so, se)
        assert "张三" in so and "发送者" in so, so
        assert "确认后重跑" in so
    finally:
        import shutil
        shutil.rmtree(d, ignore_errors=True)


def test_grade_d_stops_at_score():
    d = tempfile.mkdtemp(prefix="cp_profile_d_")
    try:
        write_log(os.path.join(d, "raw.txt"), 60, 2)
        code, so, se = run(["--in", d, "--me", "张三"])
        assert code == 3, (code, so, se)
        assert "计分" in so and "停在" in so, so
        assert not os.path.isfile(os.path.join(d, "report.md"))
    finally:
        import shutil
        shutil.rmtree(d, ignore_errors=True)
