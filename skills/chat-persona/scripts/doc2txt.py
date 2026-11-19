#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""doc2txt.py — 把 Word 聊天记录（.docx / .doc）转成纯文本，供 parse_chat.py 读取。

.docx 用标准库 zipfile 直接拆；.doc 是 OLE 二进制，只有装了 Word 的 Windows
能转（借 PowerShell 调 Word COM），转不了会明确报错并给出替代办法。

用法：
  python doc2txt.py --in 聊天记录.doc --out work/raw.txt
  python doc2txt.py --in 聊天记录.docx --out work/raw.txt
  python doc2txt.py --in 聊天记录.doc            # 只打印统计，不写文件
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile


def eprint(*a):
    print(*a, file=sys.stderr)


def die(msg, code=3):
    eprint("错误：" + msg)
    raise SystemExit(code)


W_P_RE = re.compile(r"<w:p[ >].*?</w:p>", re.S)
W_T_RE = re.compile(r"<w:t[^>]*>(.*?)</w:t>", re.S)
BR_RE = re.compile(r"<w:(?:br|cr)\b[^>]*/>")
TAB_RE = re.compile(r"<w:tab\b[^>]*/>")


def unescape(s):
    return (s.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
             .replace("&quot;", '"').replace("&apos;", "'"))


def docx_to_text(path):
    with zipfile.ZipFile(path) as z:
        try:
            xml = z.read("word/document.xml").decode("utf-8", "replace")
        except KeyError:
            die("这个 .docx 里没有 word/document.xml，可能不是 Word 文档")
    out = []
    for para in W_P_RE.findall(xml):
        para = BR_RE.sub("\n", para)
        para = TAB_RE.sub("\t", para)
        text = "".join(unescape(t) for t in W_T_RE.findall(para))
        out.append(text)
    return "\n".join(out)


PS_SCRIPT = r"""
param([string]$src, [string]$dst)
$ErrorActionPreference = "Stop"
$w = New-Object -ComObject Word.Application
$w.Visible = $false
$w.DisplayAlerts = 0
try {
  $doc = $w.Documents.Open($src, $false, $true)
  $text = $doc.Content.Text
  $doc.Close(0)
} finally {
  $w.Quit()
}
$text = $text -replace "`r`n", "`n" -replace "`r", "`n"
$text = [regex]::Replace($text, "[\x00-\x08\x0b\x0c\x0e-\x1f]", " ")
[IO.File]::WriteAllText($dst, $text, [Text.UTF8Encoding]::new($false))
"""


def doc_to_text(path):
    if os.name != "nt":
        die("旧版 .doc 只能在装了 Word 的 Windows 上转换；请用 Word 另存为 .txt 或 .docx 后重试")
    tmp = tempfile.mkdtemp(prefix="doc2txt_")
    ps = os.path.join(tmp, "conv.ps1")
    out = os.path.join(tmp, "out.txt")
    with open(ps, "w", encoding="utf-8") as f:
        f.write(PS_SCRIPT)
    exe = shutil.which("powershell") or shutil.which("pwsh")
    if not exe:
        die("找不到 PowerShell，无法调用 Word 转换 .doc；请另存为 .txt 或 .docx")
    p = subprocess.run(
        [exe, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps, "-src", os.path.abspath(path),
         "-dst", out],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if p.returncode != 0 or not os.path.exists(out):
        die("Word 转换失败（是否安装了 Word？）。可手动用 Word 打开后“另存为 → 纯文本”。\n"
            + (p.stderr or "")[-500:])
    with open(out, encoding="utf-8", errors="replace") as f:
        return f.read()


def convert(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".docx":
        return docx_to_text(path)
    if ext == ".doc":
        return doc_to_text(path)
    die("只支持 .doc / .docx，收到：" + ext)


def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except AttributeError:
            pass
    ap = argparse.ArgumentParser(
        description="把 Word 聊天记录转成 UTF-8 纯文本（.docx 零依赖；.doc 需要 Windows + Word）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n  python doc2txt.py --in 聊天记录.doc --out work/raw.txt\n",
    )
    ap.add_argument("--in", dest="inp", required=True, help="输入 .doc / .docx")
    ap.add_argument("--out", dest="out", help="输出 .txt；省略时只打印统计")
    args = ap.parse_args(argv)

    if not os.path.exists(args.inp):
        die("文件不存在：" + args.inp)
    text = convert(args.inp)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [ln for ln in text.split("\n") if ln.strip()]
    print("转换完成：%d 字符，%d 个非空段落" % (len(text), len(lines)))
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
        with open(args.out, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        print("输出：%s" % args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
