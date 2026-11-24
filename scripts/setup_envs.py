"""Install independent, locked course environments and register working kernels."""

import argparse
import hashlib
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PYTHON = "3.10.20"
MIN_UV = (0, 11, 24)
COURSES = {
    1: "Neural Networks and Deep Learning",
    2: "Improving Deep Neural Networks",
    3: "Structuring Machine Learning Projects",
    4: "Convolutional Neural Networks",
    5: "Sequence Models",
}


def run(args, **kwargs):
    print("+ " + subprocess.list2cmdline([str(arg) for arg in args]), flush=True)
    subprocess.run(args, check=True, cwd=ROOT, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--course", nargs="+", type=int, choices=COURSES, default=list(COURSES))
    parser.add_argument("--uv", default=shutil.which("uv"))
    parser.add_argument("--check-only", action="store_true", help="Verify installed environments without syncing")
    args = parser.parse_args()
    if not args.uv:
        parser.error("uv was not found. Run setup.ps1 or setup.sh to install it automatically.")
    version = subprocess.check_output([args.uv, "--version"], text=True).strip()
    match = re.search(r"uv (\d+)\.(\d+)\.(\d+)", version)
    if not match or tuple(map(int, match.groups())) < MIN_UV:
        parser.error(f"Need uv >= 0.11.24; found {version}. Update uv, then retry.")
    supported = {("Windows", "AMD64"), ("Linux", "x86_64"), ("Darwin", "arm64"), ("Darwin", "x86_64")}
    if (platform.system(), platform.machine()) not in supported:
        parser.error("Supported: Windows/Linux x86_64 and macOS Intel/Apple Silicon (64-bit).")
    print(f"Reusing {version}; Python {PYTHON}; CPU environments", flush=True)
    assets = [sys.executable, ROOT / "scripts" / "supplement_assets.py", "--course", *map(str, args.course)]
    if args.check_only:
        assets.append("--check-only")
    run(assets)
    clone_id = hashlib.sha256(os.path.normcase(str(ROOT)).encode()).hexdigest()[:8]
    for course in dict.fromkeys(args.course):
        project = ROOT / "environments" / f"course{course}"
        venv = project / ".venv"
        python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        kernel = f"dls-course-{course}-{clone_id}"
        env = os.environ.copy()
        # An activated unrelated venv or uv override must not merge course environments.
        for key in ("VIRTUAL_ENV", "PYTHONHOME", "PYTHONPATH", "UV_PROJECT", "UV_WORKING_DIR"):
            env.pop(key, None)
        env.update(UV_PROJECT_ENVIRONMENT=str(venv), PYTHONUTF8="1", TF_CPP_MIN_LOG_LEVEL="2")
        # Another setup may still be downloading a large shared TensorFlow wheel.
        env.setdefault("UV_LOCK_TIMEOUT", "1800")
        print(f"\nCourse {course}: {COURSES[course]}", flush=True)
        if args.check_only and not python.exists():
            parser.error(f"Missing {python}; run setup without --check-only first.")
        sync = [args.uv, "sync", "--project", project, "--locked", "--managed-python", "--python", PYTHON]
        if args.check_only:
            sync.append("--check")
        run(sync, env=env)
        if not args.check_only:
            run([python, "-m", "ipykernel", "install", "--user", "--name", kernel,
                 "--display-name", f"DLS Course {course} - {COURSES[course]} ({clone_id})"], env=env)
        run([args.uv, "pip", "check", "--python", python], env=env)
        run([python, ROOT / "scripts" / "check_env.py", "--course", str(course), "--kernel", kernel], env=env)
    print("\nReady. Open Deep-Learning.code-workspace in VS Code.", flush=True)
    print("Notebook > Select Kernel > Select Another Kernel > Python Environments / Jupyter Kernels.")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        print(f"\nSetup failed (exit {exc.returncode}). Fix the reported error and rerun; completed installs are reused.", file=sys.stderr)
        sys.exit(exc.returncode)
