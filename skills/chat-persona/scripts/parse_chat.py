#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""parse_chat.py — 把聊天记录文本/导出文件解析为统一的 messages.jsonl。

支持：
  - WhatsApp 导出 txt（[日期, 时间] 发送者: 内容）
  - 微信多选复制 / 导出 txt（日期 时间 发送者 + 正文，或 发送者 日期 时间 + 正文）
  - 微信合并转发三行式（2024年1月1日 下午3:20 / 发送者 / 正文）
  - QQ 消息管理器导出 txt（日期 时间 发送者(QQ号) + 正文）
  - Telegram Desktop 导出 result.json
  - 通用 CSV / TSV
  - 冒号行文本（发送者: 内容，无时间戳）
  - 纯文本（单会话、无时间戳，降级）

用法：
  python parse_chat.py --in chat.txt --out work
  python parse_chat.py --in chat.txt --out work --me 张三
  python parse_chat.py --in chat.txt --list-senders
  python parse_chat.py --in result.json --out work --me 1

示例：
  python parse_chat.py --in "C:\\Users\\me\\Desktop\\wechat.txt" --out "D:\\work\\cp" --me "我"
  python parse_chat.py --in wa.txt --out work --format whatsapp --gap-hours 4

输出：
  <out>/messages.jsonl     每行一条消息（UTF-8，JSON）
  <out>/parse_report.json  解析报告（格式、条数、发送者、未识别行样例）

退出码：0 成功；2 参数/指认错误；3 编码或解析失败。
"""

import argparse
import csv
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------- 常量

MEDIA_RE = re.compile(
    r"^\[(图片|表情|动画表情|语音|视频|文件|位置|链接|转账|红包|语音通话|视频通话|名片|音乐|小程序)\]$"
)
SYSTEM_RE = re.compile(
    r"(撤回了一条消息|加入了群聊|邀请.{0,12}加入|以下为新消息|消息已发出，但被对方拒收|"
    r"开启了朋友验证|你已添加了|以上是打招呼的内容|对方开启了朋友验证)"
)

CN_DATE_RE = re.compile(r"^(\d{4})年(\d{1,2})月(\d{1,2})日$")
DATE_RE = re.compile(r"^(\d{4})[/.\-](\d{1,2})[/.\-](\d{1,2})$")
TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$")
AMPM_RE = re.compile(r"^(上午|下午|晚上|凌晨|中午)?\s*")

INLINE_FAMILIES = [
    (
        "whatsapp_bracket",
        re.compile(
            r"^\[?(\d{1,4}[/.\-]\d{1,2}[/.\-]\d{1,4})[,，]?\s+"
            r"(\d{1,2}:\d{2}(?::\d{2})?)\s*[\]\-–]\s*([^:：]{1,40})[:：]\s*(.*)$"
        ),
    ),
    (
        "whatsapp_dash",
        re.compile(
            r"^(\d{1,4}[/.\-]\d{1,2}[/.\-]\d{1,4})[,，]?\s+"
            r"(\d{1,2}:\d{2}(?::\d{2})?)\s*[-\u2013]\s*([^:：]{1,40})[:：]\s*(.*)$"
        ),
    ),
]

HEADER_FAMILIES = [
    (
        "date_time_sender",
        re.compile(
            r"^(?P<date>\d{4}[/.\-]\d{1,2}[/.\-]\d{1,2})\s+"
            r"(?P<time>\d{1,2}:\d{2}(?::\d{2})?)\s+(?P<sender>.{1,40}?)\s*$"
        ),
    ),
    (
        "sender_date_time",
        re.compile(
            r"^(?P<sender>.{1,40}?)\s+"
            r"(?P<date>\d{4}[/.\-]\d{1,2}[/.\-]\d{1,2})\s+"
            r"(?P<time>\d{1,2}:\d{2}(?::\d{2})?)\s*$"
        ),
    ),
]

CN3_HEADER_RE = re.compile(
    r"^(?P<date>\d{4}年\d{1,2}月\d{1,2}日)\s*(?P<ampm>上午|下午|晚上|凌晨|中午)?\s*"
    r"(?P<time>\d{1,2}:\d{2}(?::\d{2})?)\s*$"
)

COLON_RE = re.compile(r"^([^:：\n]{1,40})[:：]\s*(.*)$")

COL_NAMES = {
    "time": {"time", "date", "datetime", "timestamp", "时间", "日期", "发送时间", "消息时间"},
    "sender": {"sender", "from", "name", "author", "发送者", "发送人", "昵称", "名字", "用户", "发言人"},
    "text": {"text", "content", "message", "msg", "body", "内容", "消息", "正文", "消息内容"},
}


# ---------------------------------------------------------------- 工具

def eprint(*args):
    print(*args, file=sys.stderr)


def die(msg, code=3):
    eprint("错误：" + msg)
    sys.exit(code)


def norm_header(s):
    """仅用于表头识别的归一化：全角数字/斜杠/冒号转半角。"""
    trans = {}
    for i in range(10):
        trans[ord("０") + i] = ord("0") + i
    trans[ord("／")] = ord("/")
    trans[ord("－")] = "-"
    trans[ord("：")] = ":"
    trans[ord("．")] = "."
    return s.translate(trans).strip()


def clean_sender(s):
    s = s.strip()
    s = re.sub(r"\s*[\(（]\d{3,15}[\)）]\s*$", "", s)  # QQ 尾号
    s = s.rstrip(":：").strip()
    s = re.sub(r"[ \t\u3000]+", " ", s)
    return s


def parse_date(s):
    s = norm_header(s)
    m = CN_DATE_RE.match(s)
    if m:
        return int(m.group(1)), int(m.group(2)), int(m.group(3))
    m = DATE_RE.match(s)
    if m:
        y = int(m.group(1))
        if y < 100:
            y += 2000
        return y, int(m.group(2)), int(m.group(3))
    return None


def parse_time(s, ampm=None):
    s = norm_header(s)
    m = TIME_RE.match(s)
    if not m:
        return None
    h, mi, sec = int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)
    if ampm in ("下午", "晚上") and h < 12:
        h += 12
    if ampm == "中午" and h < 11:
        h += 12
    if ampm == "凌晨" and h == 12:
        h = 0
    if 0 <= h <= 23 and 0 <= mi <= 59 and 0 <= sec <= 59:
        return h, mi, sec
    return None


def parse_tz(s):
    s = (s or "").strip()
    if not s:
        return timezone(timedelta(hours=8))
    m = re.match(r"^([+-])(\d{1,2})(?::?(\d{2}))?$", s)
    if not m:
        if re.match(r"^\d{1,2}$", s):
            m = re.match(r"^(\d{1,2})$", s)
            return timezone(timedelta(hours=int(m.group(1))))
        die("--tz 格式应为 +08:00 或 8，收到 %r" % s, 2)
    sign = -1 if m.group(1) == "-" else 1
    hh = int(m.group(2))
    mm = int(m.group(3) or 0)
    return timezone(sign * timedelta(hours=hh, minutes=mm))


def make_dt(date_str, time_str, ampm, tz, fallback_date=None):
    d = parse_date(date_str) if date_str else fallback_date
    if d is None:
        return None
    t = parse_time(time_str, ampm) if time_str else None
    if t is None:
        return None
    try:
        return datetime(d[0], d[1], d[2], t[0], t[1], t[2], tzinfo=tz)
    except ValueError:
        return None


def classify(text):
    t = text.strip()
    if not t:
        return "empty"
    if MEDIA_RE.match(t):
        return "media"
    if SYSTEM_RE.search(t):
        return "system"
    return "text"


def tg_text(v):
    if isinstance(v, str):
        return v
    if isinstance(v, list):
        out = []
        for p in v:
            if isinstance(p, str):
                out.append(p)
            elif isinstance(p, dict):
                out.append(str(p.get("text", "")))
        return "".join(out)
    if v is None:
        return ""
    return str(v)


# ---------------------------------------------------------------- 读取

def read_text(path):
    with open(path, "rb") as f:
        raw = f.read()
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig"), "utf-8-sig"
    for enc in ("utf-8", "gb18030", "utf-16"):
        try:
            return raw.decode(enc), enc
        except (UnicodeDecodeError, UnicodeError):
            continue
    die("无法识别文件编码，请另存为 UTF-8 后重试：" + path, 3)


# ---------------------------------------------------------------- 解析器

def new_msg(sender, dt, raw_ts, text, is_me=None):
    return {
        "sender": clean_sender(sender) if sender else "",
        "dt": dt,
        "raw_ts": raw_ts,
        "text": text,
        "is_me": is_me,
    }


def parse_json_dump(obj, tz):
    msgs = []
    if isinstance(obj, dict):
        arr = obj.get("messages")
        arr = arr if isinstance(arr, list) else []
    elif isinstance(obj, list):
        arr = obj
    else:
        arr = []
    for m in arr:
        if not isinstance(m, dict):
            continue
        sender = m.get("from") or m.get("actor") or m.get("sender") or ""
        raw_date = m.get("date") or m.get("time") or ""
        dt = None
        if isinstance(raw_date, str) and raw_date:
            s = raw_date.replace("Z", "+00:00")
            try:
                dt = datetime.fromisoformat(s)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=tz)
            except ValueError:
                dt = None
        text = tg_text(m.get("text"))
        mtype = m.get("type") or ""
        if not text and m.get("media_type"):
            text = "[图片]"
        if mtype == "service":
            text = text or "[系统消息]"
        msgs.append(new_msg(sender or "系统", dt, str(raw_date), text))
    return msgs, "telegram"


def parse_delimited(lines, tz):
    sample = "\n".join(lines[:20])
    delim = "\t" if "\t" in sample else ","
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters="\t,;")
        delim = dialect.delimiter
    except csv.Error:
        pass
    rows = list(csv.reader(lines, delimiter=delim))
    rows = [r for r in rows if any(c.strip() for c in r)]
    if not rows:
        return [], None

    idx = {}
    head = [c.strip().lower() for c in rows[0]]
    for key, names in COL_NAMES.items():
        for i, c in enumerate(head):
            if c in names:
                idx[key] = i
                break
    if len(idx) == 3:
        body = rows[1:]
    elif len(rows[0]) >= 3 and not idx:
        idx = {"time": 0, "sender": 1, "text": 2}
        body = rows
        # 无表头时必须确认首列像时间，避免把普通聊天文本误判成 CSV
        ok = sum(
            1 for r in body[:8]
            if r and re.search(r"\d{1,2}:\d{2}", r[0])
        )
        if ok == 0:
            return [], None
    else:
        return [], None

    msgs = []
    for r in body:
        if len(r) <= max(idx.values()):
            continue
        date_s, time_s = None, None
        raw_t = r[idx["time"]].strip()
        if " " in raw_t:
            a, b = raw_t.split(" ", 1)
            date_s, time_s = a, b
        elif "T" in raw_t:
            a, b = raw_t.split("T", 1)
            date_s, time_s = a, b[:8]
        else:
            time_s = raw_t
        dt = make_dt(date_s, time_s, None, tz)
        text = r[idx["text"]].strip()
        msgs.append(new_msg(r[idx["sender"]], dt, raw_t, text))
    return msgs, "csv" if delim == "," else "tsv"


def detect_family(lines):
    nonempty = [ln for ln in lines if ln.strip()]
    if not nonempty:
        return None, 0
    sample = nonempty[:3000]
    total = len(sample)

    def score(fam):
        n = sum(1 for ln in sample if fam.match(norm_header(ln)))
        return n

    best, best_n = None, 0
    for name, fam in INLINE_FAMILIES:
        n = score(fam)
        if n > best_n:
            best, best_n = ("inline", fam, name), n
    for name, fam in HEADER_FAMILIES:
        n = score(fam)
        if n > best_n:
            best, best_n = ("header", fam, name), n
    n_cn = sum(1 for ln in sample if CN3_HEADER_RE.match(norm_header(ln)))
    if n_cn > best_n:
        best, best_n = ("cn3", CN3_HEADER_RE, "cn_date_3line"), n_cn

    if best is None or best_n < 2 or best_n / float(total) < 0.04:
        return None, 0
    return best, best_n


def best_header(lines):
    """在两种表头顺序里挑匹配更多的那个。"""
    sample = [ln for ln in lines if ln.strip()][:3000]
    best, best_n = (HEADER_FAMILIES[0][0], HEADER_FAMILIES[0][1]), 0
    for name, fam in HEADER_FAMILIES:
        n = sum(1 for ln in sample if fam.match(norm_header(ln)))
        if n > best_n:
            best, best_n = (name, fam), n
    return best, best_n


def parse_inline(lines, fam, tz):
    msgs, unparsed = [], []
    for ln in lines:
        if not ln.strip():
            continue
        m = fam.match(norm_header(ln))
        if not m:
            unparsed.append(ln)
            continue
        date_s, time_s, sender, text = m.group(1), m.group(2), m.group(3), m.group(4)
        dt = make_dt(date_s, time_s, None, tz)
        msgs.append(new_msg(sender, dt, "%s %s" % (date_s, time_s), text))
    return msgs, unparsed


def parse_header(lines, fam, tz):
    msgs, unparsed = [], []
    cur = None
    for ln in lines:
        m = fam.match(norm_header(ln))
        if m:
            if cur:
                msgs.append(cur)
            gd = m.groupdict()
            dt = make_dt(gd.get("date"), gd.get("time"), None, tz)
            cur = new_msg(gd.get("sender", ""), dt,
                          "%s %s" % (gd.get("date", ""), gd.get("time", "")), "")
            continue
        if cur is None:
            if ln.strip():
                unparsed.append(ln)
            continue
        cur["text"] = (cur["text"] + "\n" + ln).strip() if cur["text"] else ln.strip()
    if cur:
        msgs.append(cur)
    return msgs, unparsed


def parse_cn3(lines, tz):
    msgs, unparsed = [], []
    cur = None
    awaiting_sender = False
    for ln in lines:
        s = norm_header(ln)
        m = CN3_HEADER_RE.match(s)
        if m:
            if cur:
                msgs.append(cur)
            dt = make_dt(m.group("date"), m.group("time"), m.group("ampm"), tz)
            cur = new_msg("", dt, "%s %s" % (m.group("date"), m.group("time")), "")
            awaiting_sender = True
            continue
        if cur is None:
            if ln.strip():
                unparsed.append(ln)
            continue
        if awaiting_sender:
            if ln.strip():
                cur["sender"] = clean_sender(ln)
                awaiting_sender = False
            continue
        cur["text"] = (cur["text"] + "\n" + ln).strip() if cur["text"] else ln.strip()
    if cur:
        msgs.append(cur)
    return msgs, unparsed


def parse_colon(lines):
    msgs, unparsed = [], []
    for ln in lines:
        if not ln.strip():
            continue
        m = COLON_RE.match(ln)
        if not m:
            unparsed.append(ln)
            continue
        sender, text = m.group(1).strip(), m.group(2).strip()
        if re.match(r"^[\d\s:/.\-]+$", sender):
            unparsed.append(ln)
            continue
        msgs.append(new_msg(sender, None, "", text))
    return msgs, unparsed


def parse_plain(lines):
    msgs = [new_msg("", None, "", ln.strip()) for ln in lines if ln.strip()]
    return msgs, []


# ---------------------------------------------------------------- 后处理

def finalize(msgs, tz, gap_hours, me):
    msgs = [m for m in msgs if classify(m["text"]) != "empty"]

    # 排序：仅当全部有时间戳且非单调时才排序，避免打断无时间戳文件的顺序
    if msgs and all(m["dt"] is not None for m in msgs):
        ordered = all(
            msgs[i]["dt"] <= msgs[i + 1]["dt"] for i in range(len(msgs) - 1)
        )
        if not ordered:
            msgs.sort(key=lambda m: m["dt"])

    is_me = None
    if me:
        labels = []
        for m in msgs:
            if m["sender"] not in labels:
                labels.append(m["sender"])
        counts = {s: 0 for s in labels}
        for m in msgs:
            counts[m["sender"]] += 1
        ranked = sorted(counts, key=lambda s: (-counts[s], s))
        target = me.strip()
        if target.isdigit() and 1 <= int(target) <= len(ranked):
            target = ranked[int(target) - 1]
        if target not in counts:
            eprint("错误：--me 未匹配到发送者：%s" % me)
            for i, s in enumerate(ranked, 1):
                eprint("  %d. %s (%d 条)" % (i, s, counts[s]))
            sys.exit(2)
        is_me = target
        for m in msgs:
            m["is_me"] = (m["sender"] == is_me)

    gap = timedelta(hours=gap_hours)
    session_no = 1
    prev = None
    out = []
    for i, m in enumerate(msgs):
        if m["dt"] is not None and prev is not None and (m["dt"] - prev) > gap:
            session_no += 1
        out.append({
            "i": i,
            "session_id": "S%03d" % session_no,
            "sender": m["sender"],
            "is_me": m["is_me"],
            "ts": m["dt"].isoformat(timespec="seconds") if m["dt"] else None,
            "text": m["text"],
            "type": classify(m["text"]),
            "raw_ts": m["raw_ts"],
        })
        if m["dt"] is not None:
            prev = m["dt"]
    return out, is_me, session_no


# ---------------------------------------------------------------- 主流程

def main(argv=None):
    ap = argparse.ArgumentParser(
        description="把聊天记录解析为统一 messages.jsonl（本地、零依赖）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  python parse_chat.py --in chat.txt --out work --me 张三\n"
            "  python parse_chat.py --in chat.txt --list-senders\n"
            "  python parse_chat.py --in result.json --out work --format telegram\n"
        ),
    )
    ap.add_argument("--in", dest="inp", help="输入文件路径")
    ap.add_argument("--out", help="输出目录")
    ap.add_argument("--format", default="auto",
                    choices=["auto", "whatsapp", "wechat", "qq", "telegram", "tsv", "colon", "plain"],
                    help="输入格式（默认 auto）")
    ap.add_argument("--me", help="指认'我'：发送者名，或发送者序号 1..n")
    ap.add_argument("--gap-hours", type=float, default=6.0, help="会话切分间隔小时数（默认 6）")
    ap.add_argument("--tz", default="+08:00", help="无时区信息时使用的偏移，如 +08:00（默认）")
    ap.add_argument("--encoding", help="强制指定编码")
    ap.add_argument("--list-senders", action="store_true", help="只列出发送者及条数")
    ap.add_argument("--alias", action="append", default=[], help="发送者归并，如 --alias '张三=我'")
    args = ap.parse_args(argv)

    if not args.inp:
        ap.print_help()
        return 2
    if not os.path.isfile(args.inp):
        die("输入文件不存在：" + args.inp, 2)
    if not args.list_senders and not args.out:
        die("需要 --out 输出目录（或用 --list-senders 只看发送者）", 2)

    tz = parse_tz(args.tz)
    if args.encoding:
        with open(args.inp, "rb") as f:
            text = f.read().decode(args.encoding, errors="replace")
        enc = args.encoding
    else:
        text, enc = read_text(args.inp)

    stripped = text.strip()
    lines = text.splitlines()
    warnings = []
    unparsed = []
    fmt = args.format
    msgs = None

    if fmt in ("auto", "telegram") and stripped[:1] in ("{", "["):
        try:
            obj = json.loads(stripped)
            msgs, fmt = parse_json_dump(obj, tz)
        except ValueError:
            if fmt == "telegram":
                die("JSON 解析失败，请检查导出文件是否完整", 3)
            msgs = None
            fmt = args.format

    if msgs is None and fmt in ("auto", "tsv"):
        got, fmt2 = parse_delimited(lines, tz)
        if got:
            msgs, fmt = got, fmt2

    if msgs is None and fmt in ("auto", "whatsapp", "wechat", "qq"):
        if fmt == "whatsapp":
            fam, _n = detect_family(lines)
            if not fam or fam[0] != "inline":
                fam = ("inline", INLINE_FAMILIES[0][1], "whatsapp_bracket")
        elif fmt in ("wechat", "qq"):
            (fname, fregex), n = best_header(lines)
            if n == 0:
                fregex = HEADER_FAMILIES[0][1]
            fam = ("header", fregex, fname)
        else:
            fam, _n = detect_family(lines)
            if fam is None:
                fam = ("header", HEADER_FAMILIES[0][1], "date_time_sender")

        kind, regex, fam_name = fam
        if kind == "inline":
            msgs, unparsed = parse_inline(lines, regex, tz)
        elif kind == "cn3":
            msgs, unparsed = parse_cn3(lines, tz)
        else:
            msgs, unparsed = parse_header(lines, regex, tz)
            if not msgs:
                msgs, unparsed = parse_colon(lines)
                fam_name = "colon"
        fmt = fam_name

    if msgs is None and fmt == "colon":
        msgs, unparsed = parse_colon(lines)
    if msgs is None and fmt == "plain":
        msgs, unparsed = parse_plain(lines)

    if not msgs:
        die("未能解析出任何消息。请检查文件是否为空，或改用 --format 指定格式", 3)

    # 发送者别名
    if args.alias:
        amap = {}
        for pair in args.alias:
            if "=" in pair:
                a, b = pair.split("=", 1)
                amap[a.strip()] = b.strip()
        for m in msgs:
            if m["sender"] in amap:
                m["sender"] = amap[m["sender"]]

    out, is_me, n_sessions = finalize(msgs, tz, args.gap_hours, args.me)
    out.sort(key=lambda r: r["i"])
    for i, r in enumerate(out):
        r["i"] = i

    senders = {}
    for r in out:
        senders[r["sender"]] = senders.get(r["sender"], 0) + 1
    ranked = sorted(senders.items(), key=lambda kv: (-kv[1], kv[0]))

    if args.list_senders:
        print("发送者（按条数降序）：")
        for i, (s, c) in enumerate(ranked, 1):
            mark = "  <- 我" if s == is_me else ""
            print("  %d. %s  %d 条%s" % (i, s, c, mark))
        print("\n请让用户指认哪一个是他/她自己，然后加 --me 序号或名字重跑。")
        return 0

    ts_list = [r["ts"] for r in out if r["ts"]]
    span_days = 0
    if ts_list:
        d0 = datetime.fromisoformat(ts_list[0])
        d1 = datetime.fromisoformat(ts_list[-1])
        span_days = (d1.date() - d0.date()).days + 1
    else:
        warnings.append("无时间戳：行为类特征（发起、时延、夜间）不可用")

    n_text = sum(1 for r in out if r["type"] == "text")
    n_media = sum(1 for r in out if r["type"] == "media")
    n_sys = sum(1 for r in out if r["type"] == "system")
    if is_me is None:
        warnings.append("未指定 --me：无法计算'我'的特征")
    if len(ranked) == 1:
        warnings.append("只识别到 1 个发送者：请确认复制时是否包含双方消息")

    os.makedirs(args.out, exist_ok=True)
    mpath = os.path.join(args.out, "messages.jsonl")
    with open(mpath, "w", encoding="utf-8", newline="\n") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n")

    report = {
        "format": fmt,
        "input": os.path.abspath(args.inp),
        "encoding": enc,
        "messages": len(out),
        "text_messages": n_text,
        "media_messages": n_media,
        "system_messages": n_sys,
        "sessions": n_sessions,
        "span_days": span_days,
        "senders": [{"label": s, "count": c} for s, c in ranked],
        "me": is_me,
        "has_timestamps": bool(ts_list),
        "unparsed_lines": len(unparsed),
        "unparsed_samples": unparsed[:5],
        "warnings": warnings,
    }
    rpath = os.path.join(args.out, "parse_report.json")
    with open(rpath, "w", encoding="utf-8", newline="\n") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print("解析完成：%s" % fmt)
    print("  消息 %d（文本 %d / 媒体 %d / 系统 %d），会话 %d，跨度 %d 天"
          % (len(out), n_text, n_media, n_sys, n_sessions, span_days))
    print("  发送者：%s" % "，".join("%s(%d)" % (s, c) for s, c in ranked))
    if is_me:
        print("  我 = %s" % is_me)
    if unparsed:
        print("  未识别行：%d（示例：%r）" % (len(unparsed), unparsed[:2]))
    for w in warnings:
        print("  ! " + w)
    print("  输出：%s" % mpath)
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.exit(main())
