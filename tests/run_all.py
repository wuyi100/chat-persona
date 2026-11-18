# -*- coding: utf-8 -*-
"""顺序执行 tests/ 下全部 test_*.py。"""

import importlib
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    sys.path.insert(0, HERE)
    mods = sorted(
        f[:-3] for f in os.listdir(HERE)
        if f.startswith("test_") and f.endswith(".py")
    )
    total = 0
    failed = 0
    for name in mods:
        mod = importlib.import_module(name)
        cases = sorted(n for n in dir(mod) if n.startswith("test_") and callable(getattr(mod, n)))
        print("\n[%s]" % name)
        for case in cases:
            total += 1
            try:
                getattr(mod, case)()
                print("  PASS  %s" % case)
            except Exception:
                failed += 1
                print("  FAIL  %s" % case)
                traceback.print_exc()
    print("\n%d/%d passed" % (total - failed, total))
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.exit(main())
