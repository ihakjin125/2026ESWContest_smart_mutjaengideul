#!/usr/bin/env python3
"""Run frozen Python sign recognition with C++ vision JSON/JSONL input."""

import argparse
import importlib.util
import sys
from pathlib import Path

from frame_hands_adapter import load_recording_frames


REPO_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_PATH = REPO_ROOT / "07g_webcam_15class_final_frozen.py"


def load_runtime():
    sys.path.insert(0, str(REPO_ROOT))
    spec = importlib.util.spec_from_file_location("runtime15_offline", RUNTIME_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"runtime import failed: {RUNTIME_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate C++ hand JSON/JSONL with the frozen 15-class runtime."
    )
    parser.add_argument("result_json", type=Path, nargs="+")
    args = parser.parse_args()

    frames = load_recording_frames(args.result_json)
    if not frames:
        raise RuntimeError("no accepted hand frames")

    runtime = load_runtime()
    captures = iter((frames, None))
    runtime.u.capture_sequence = lambda: next(captures)
    runtime.input = lambda prompt="": "q"

    print("OFFLINE C++ JSONL -> PYTHON 15-CLASS VALIDATION")
    print("Inputs:", ", ".join(map(str, args.result_json)))
    print("Frames:", len(frames))
    runtime.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
