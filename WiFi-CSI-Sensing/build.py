"""Build the portable desktop application using the checked-in specification."""

import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def main():
    if sys.platform != "win32":
        raise SystemExit("Build the Windows executable on Windows.")
    environment = os.environ.copy()
    windows = Path(environment.get("SystemRoot", "C:/Windows"))
    # Avoid collecting unrelated DLLs from other applications on the host PATH.
    environment["PATH"] = os.pathsep.join(
        [
            str(windows / "System32"),
            str(windows),
            str(Path(sys.executable).parent),
        ]
    )
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--distpath",
            str(ROOT / "release"),
            "--workpath",
            str(ROOT / "build"),
            str(ROOT / "WifiSensing2.0.spec"),
        ],
        cwd=ROOT,
        env=environment,
        check=True,
    )


if __name__ == "__main__":
    main()
