#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""profile.py — 一条命令跑完整条流水线。

    python profile.py --in work --me "我的昵称"

依次执行 parse_chat → anonymize → features → score → evidence → render_report，
任何一步失败就停在那一步并打印原因。单步调试仍可直接调用各自的脚本。

退出码：0 成功；2 参数问题；3 样本不足或解析失败。
"""
import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable

STEPS = [
    ("解析", "parse_chat.py"),
    ("脱敏", "anonymize.py"),
    ("特征", "features.py"),
    ("计分", "score.py"),
    ("证据", "evidence.py"),
    ("报告", "render_report.py"),
]


def run_step(script, args):
    path = os.path.join(HERE, script)
    p = subprocess.run(
        [PY, path] + args,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    out = (p.stdout or "").strip()
    if out:
        print(out)
    if p.returncode != 0:
        err = (p.stderr or "").strip()
        if err:
            sys.stderr.write(err + "\n")
    return p.returncode


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="一条命令跑完聊天风格画像流水线",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  python profile.py --in work --me 张三\n"
            "  python profile.py --in work --me 1 --drop-sensitive\n"
            "不给 --me 时只列出发送者，方便先确认身份。\n"
        ),
    )
    ap.add_argument("--in", dest="inp", required=True, help="工作目录（内含 raw.txt 或导出文件）")
    ap.add_argument("--out", dest="out", help="输出目录，默认与 --in 相同")
    ap.add_argument("--me", help="指认'我'：发送者名或序号")
    ap.add_argument("--format", default="auto", help="输入格式，透传给 parse_chat.py")
    ap.add_argument("--gap-hours", type=float, default=6.0, help="会话切分间隔（默认 6 小时）")
    ap.add_argument("--drop-sensitive", action="store_true", help="直接丢弃敏感消息而不是打标")
    ap.add_argument("--bootstrap", type=int, default=1000, help="bootstrap 次数（默认 1000）")
    ap.add_argument("--assets", help="权重/锚点目录，默认技能自带 assets")
    ap.add_argument("--force", action="store_true",
                    help="样本不足时也出分（报告标注“仅供演示”，不得当结论）")
    args = ap.parse_args(argv)

    if args.out:
        work = args.out
    elif os.path.isdir(args.inp):
        work = args.inp
    else:
        stem = os.path.splitext(os.path.basename(args.inp))[0]
        work = os.path.join(os.path.dirname(os.path.abspath(args.inp)), stem + "_out")
    os.makedirs(work, exist_ok=True)

    base = ["--in", args.inp, "--out", work]
    if args.format and args.format != "auto":
        base += ["--format", args.format]

    # 未指认身份：只解析并列出候选，交给用户选
    if not args.me:
        print("== 解析（未指定 --me，先列出发送者）==")
        code = run_step("parse_chat.py", base + ["--list-senders"])
        if code != 0:
            return code
        print("\n确认后重跑：python profile.py --in %s --me <名字或序号>" % args.inp)
        return 0

    parse_args = base + ["--me", args.me, "--gap-hours", str(args.gap_hours)]
    anon_args = ["--in", work, "--out", work]
    if args.drop_sensitive:
        anon_args.append("--drop-sensitive")
    steps_args = {
        "parse_chat.py": parse_args,
        "anonymize.py": anon_args,
        "features.py": ["--in", work, "--out", work],
        "score.py": ["--in", work, "--out", work, "--bootstrap", str(args.bootstrap)]
                    + (["--assets", args.assets] if args.assets else [])
                    + (["--force"] if args.force else []),
        "evidence.py": ["--in", work, "--out", work],
        "render_report.py": ["--in", work, "--out", work],
    }

    for label, script in STEPS:
        print("\n== %s ==" % label)
        code = run_step(script, steps_args[script])
        if code != 0:
            print("\n流水线停在「%s」这一步。按上面的提示处理后，重跑同一命令即可。" % label)
            return code

    report = os.path.join(work, "report.md")
    print("\n完成：%s" % report)
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.exit(main())
