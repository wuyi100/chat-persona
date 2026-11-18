#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""grab.py — 把剪贴板里的一段聊天记录追加到原始输入文件。

为什么需要它：微信 / QQ 桌面端都不再提供"导出为 txt"，但都支持多选后复制。
用户复制一段，脚本追加一段，最后 parse_chat.py 直接吃这个文件；重复复制同一段会被跳过。

用法：
  python grab.py --out work/raw.txt --watch            # 持续监听，复制一段追加一段，Ctrl+C 结束
  python grab.py --out work/raw.txt                    # 读一次剪贴板并追加
  python grab.py --out work/raw.txt --peek             # 只看文件末尾，不写入
  python grab.py --out work/raw.txt --from-file a.txt   # 从文件追加（便于测试/批处理）
  python grab.py --out work/raw.txt --reset            # 清空重来

退出码：0 成功（含"没有新增"）；2 参数/输入问题；3 剪贴板不可用。
"""
import argparse
import os
import sys
import time

SEP = "\n\n"


def read_clipboard():
    """读 Windows 剪贴板文本；失败抛 RuntimeError。"""
    if os.name != "nt":
        raise RuntimeError("当前系统不是 Windows，剪贴板读取不可用；请改用 --from-file")
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.GetClipboardData.restype = wintypes.HANDLE
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [wintypes.HANDLE]
    kernel32.GlobalUnlock.argtypes = [wintypes.HANDLE]

    if not user32.OpenClipboard(None):
        raise RuntimeError("无法打开剪贴板（可能被其他程序占用），请稍后再试")
    try:
        for fmt in (13, 1):  # CF_UNICODETEXT, CF_TEXT
            handle = user32.GetClipboardData(fmt)
            if not handle:
                continue
            ptr = kernel32.GlobalLock(handle)
            if not ptr:
                continue
            try:
                if fmt == 13:
                    return ctypes.wstring_at(ptr)
                raw = ctypes.string_at(ptr)
                return raw.decode("utf-8", errors="replace")
            finally:
                kernel32.GlobalUnlock(handle)
        return ""
    finally:
        user32.CloseClipboard()


def read_existing(path):
    if not os.path.isfile(path):
        return ""
    with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
        return f.read()


def append_text(path, text, reset=False):
    """把 text 追加到 path；已存在则跳过。返回 (added, total_chars, total_lines)。

    返回值 added 为 False 表示这段内容此前已经收过（或为空）。
    """
    block = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not block:
        return False, len(read_existing(path)), 0

    existing = "" if reset else read_existing(path)
    if block in existing:
        return False, len(existing), existing.count("\n") + 1 if existing else 0

    body = (existing.rstrip() + SEP + block + "\n") if existing.strip() else (block + "\n")
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(body)
    return True, len(body), body.count("\n")


def watch(path, reset=False):
    """持续监听剪贴板，每出现一段新文本就追加；Ctrl+C 结束。"""
    if reset:
        append_text(path, "", reset=True)
    print("监听中：在微信/QQ 里复制一段，就会自动追加到 %s" % path, flush=True)
    print("复制多段后按 Ctrl+C 结束。", flush=True)
    last = None
    try:
        while True:
            try:
                text = read_clipboard()
            except RuntimeError as e:
                sys.stderr.write("读取失败：%s\n" % e)
                return 3
            if text and text.strip() and text != last:
                last = text
                added, total_chars, _ = append_text(path, text)
                if added:
                    print("  + %d 字（累计 %d 字）" % (len(text.strip()), total_chars), flush=True)
                else:
                    print("  = 重复段落，已跳过", flush=True)
            time.sleep(0.5)
    except KeyboardInterrupt:
        total = len(read_existing(path))
        print("\n已停止，共收集 %d 字。下一步：python profile.py --in <work>" % total)
        return 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="把剪贴板（或指定文件）中的一段聊天记录追加到原始输入文件",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "典型流程：\n"
            "  1) 在微信/QQ 里多选消息，Ctrl+C\n"
            "  2) python grab.py --out work/raw.txt\n"
            "  3) 重复 1-2 直到够用\n"
            "  4) python parse_chat.py --in work/raw.txt --out work --me 1\n"
        ),
    )
    ap.add_argument("--out", required=False, help="目标原始文件（不存在会自动创建）")
    ap.add_argument("--from-file", help="从文件读取一段内容，而不是剪贴板")
    ap.add_argument("--peek", action="store_true", help="只打印文件末尾，不写入")
    ap.add_argument("--watch", action="store_true",
                    help="持续监听剪贴板：每复制一段就自动追加，Ctrl+C 结束")
    ap.add_argument("--reset", action="store_true", help="先清空目标文件再写入")
    ap.add_argument("--chars", type=int, default=1200, help="--peek 显示的字符数（默认 1200）")
    args = ap.parse_args(argv)

    if not args.out:
        ap.print_help()
        return 2

    if args.watch:
        return watch(args.out, reset=args.reset)

    if args.peek:
        text = read_existing(args.out)
        if not text:
            print("（文件不存在或为空）：%s" % args.out)
            return 0
        print(text[-args.chars:])
        print("\n--- 共 %d 字符 / %d 行 ---" % (len(text), text.count("\n") + 1))
        return 0

    try:
        if args.from_file:
            with open(args.from_file, "r", encoding="utf-8-sig", errors="replace") as f:
                text = f.read()
        else:
            text = read_clipboard()
    except RuntimeError as e:
        sys.stderr.write("读取失败：%s\n" % e)
        return 3
    except OSError as e:
        sys.stderr.write("读取文件失败：%s\n" % e)
        return 2

    if not (text or "").strip():
        sys.stderr.write("没有拿到任何文本：剪贴板为空，或复制的内容不含纯文本。\n")
        return 2

    added, total_chars, total_lines = append_text(args.out, text, reset=args.reset)
    if added:
        print("已追加 %d 字符；文件现有 %d 字符 / %d 行" % (len(text.strip()), total_chars, total_lines))
    else:
        print("没有新增内容（这段之前已经收过）；文件现有 %d 字符" % total_chars)
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.exit(main())
