"""Run every offline test:   python tests/run_all.py

Nothing here touches real windows or sends input (Qt runs off-screen). A few tests read your library
and settings without changing them. Screenshots and scratch files go to tests/_out.
"""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "_out")
TESTS = ["home_select", "home_sort", "home_cards", "library_tags_combine", "editor_codebar", "editor_stamps",
         "editor_tools", "capture_mixed_dpi", "capture_features", "scroll_sim", "scroll_cases"]


def main():
    os.makedirs(OUT, exist_ok=True)
    only = sys.argv[1:]
    bad = 0
    for name in TESTS:
        if only and name not in only:
            continue
        t = time.time()
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        p = subprocess.run([sys.executable, os.path.join(HERE, f"{name}.py"), OUT], capture_output=True,
                           text=True, encoding="utf-8", errors="replace", env=env, timeout=900)
        out = p.stdout + p.stderr
        fails = [l for l in out.splitlines() if l.startswith("FAIL") or "Traceback" in l or "Error:" in l]
        ok = p.returncode == 0 and not fails
        bad += not ok
        passes = sum(1 for l in out.splitlines() if l.startswith("PASS"))
        print(f"{'ok  ' if ok else 'FAIL'}  {name:<22} {passes:>3} checks passed   {time.time() - t:5.1f} s")
        for l in fails[:8]:
            print("        " + l)
    print("\nAll tests passed." if not bad else f"\n{bad} test file(s) failed.")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
