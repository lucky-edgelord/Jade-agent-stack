#!/usr/bin/env python3
"""Build the docs from one source.  python build/build.py [--out docs] [--format html|md|both] [--check] [--report]"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from jade.docsbuild import build, report  # noqa: E402
from jade.errors import JadeError  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--out", default="docs")
ap.add_argument("--format", default="both", choices=("html", "md", "both"))
ap.add_argument("--check", action="store_true", help="exit 1 if a committed output is stale")
ap.add_argument("--report", action="store_true", help="warn about dead links and undocumented commands")
a = ap.parse_args()
if a.report:
    w = report(ROOT)
    for x in w:
        print("warning:", x)
    print(f"{len(w)} warning(s)")
    sys.exit(0)
try:
    r = build(Path(a.out), format=a.format, check=a.check, root=ROOT)
except JadeError as e:
    print(e, file=sys.stderr)
    sys.exit(1)
print(("up to date: " if a.check else "built: ") + f"{r['files']} files")
