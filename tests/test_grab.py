# -*- coding: utf-8 -*-
"""grab.py 的单元测试（纯标准库）。"""

import importlib.util
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPTS = os.path.join(ROOT, "skills", "chat-persona", "scripts")
PY = sys.executable
SCRIPT = os.path.join(SCRIPTS, "grab.py")


def load_grab():
    spec = importlib.util.spec_from_file_location("grab_mod", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run(*args):
    p = subprocess.run(
        [PY, SCRIPT] + list(args),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return p.returncode, p.stdout, p.stderr


def test_append_and_dedupe():
    g = load_grab()
    d = tempfile.mkdtemp(prefix="cp_grab_")
    try:
        raw = os.path.join(d, "raw.txt")
        added, chars, lines = g.append_text(raw, "张三：你好\r\n李四：在的")
        assert added and chars > 0 and lines >= 2, (added, chars, lines)
        added2, _, _ = g.append_text(raw, "张三：你好\n李四：在的")
        assert not added2, "同一段内容不应重复追加"
        added3, _, _ = g.append_text(raw, "张三：晚点聊")
        assert added3
        with open(raw, encoding="utf-8") as f:
            body = f.read()
        assert body.count("你好") == 1, body
        assert "晚点聊" in body
        assert "\r" not in body
    finally:
        import shutil
        shutil.rmtree(d, ignore_errors=True)


def test_reset_replaces():
    g = load_grab()
    d = tempfile.mkdtemp(prefix="cp_grab_r_")
    try:
        raw = os.path.join(d, "raw.txt")
        g.append_text(raw, "旧内容")
        added, _, _ = g.append_text(raw, "新内容", reset=True)
        assert added
        with open(raw, encoding="utf-8") as f:
            body = f.read()
        assert "新内容" in body and "旧内容" not in body, body
    finally:
        import shutil
        shutil.rmtree(d, ignore_errors=True)


def test_cli_from_file_and_peek():
    d = tempfile.mkdtemp(prefix="cp_grab_cli_")
    try:
        src = os.path.join(d, "seg1.txt")
        raw = os.path.join(d, "raw.txt")
        with open(src, "w", encoding="utf-8", newline="\n") as f:
            f.write("张三 2024-01-01 12:00:00\n你好\n")
        code, so, se = run("--out", raw, "--from-file", src)
        assert code == 0, (code, so, se)
        assert "已追加" in so, so
        code2, so2, _ = run("--out", raw, "--peek", "--chars", "200")
        assert code2 == 0 and "你好" in so2, so2
        assert "共 " in so2
    finally:
        import shutil
        shutil.rmtree(d, ignore_errors=True)


def test_cli_empty_input_is_error():
    d = tempfile.mkdtemp(prefix="cp_grab_empty_")
    try:
        src = os.path.join(d, "empty.txt")
        with open(src, "w", encoding="utf-8") as f:
            f.write("   \n\n")
        code, so, se = run("--out", os.path.join(d, "raw.txt"), "--from-file", src)
        assert code == 2, (code, so, se)
        assert "没有拿到任何文本" in se, se
    finally:
        import shutil
        shutil.rmtree(d, ignore_errors=True)
