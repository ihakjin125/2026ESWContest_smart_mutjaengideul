"""Package successful PlatformIO C6 builds; does not access a serial port."""

import argparse
from pathlib import Path
import hashlib
import json
import subprocess
import sys


def main():
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-dir", type=Path, default=root / ".pio/build")
    args = parser.parse_args()
    build = args.build_dir.resolve()
    roles = ("receiver", "transmitter")
    for role in roles:
        for name in ("bootloader.bin", "partitions.bin", "firmware.bin"):
            if not (build / f"c6_{role}" / name).is_file():
                raise SystemExit(
                    f"Build both C6 roles first; missing {role}/{name}"
                )
    out = root / "bin"
    out.mkdir(exist_ok=True)
    manifest = dict(
        chip="esp32c6",
        flash_size="4MB",
        channel=11,
        target_hz=60,
        physical_hardware_validated=False,
        idf="5.4.0",
        platform="espressif32@6.10.0",
        gain_component="0.1.5",
    )
    for role in roles:
        folder = build / f"c6_{role}"
        target = out / f"{role}.bin"
        subprocess.run(
            [
                sys.executable,
                "-m",
                "esptool",
                "--chip",
                "esp32c6",
                "merge_bin",
                "-o",
                str(target),
                "--flash_mode",
                "dio",
                "--flash_size",
                "4MB",
                "0x0",
                str(folder / "bootloader.bin"),
                "0x8000",
                str(folder / "partitions.bin"),
                "0x10000",
                str(folder / "firmware.bin"),
            ],
            check=True,
        )
        manifest[role] = dict(
            sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
            bytes=target.stat().st_size,
            application_sha256=hashlib.sha256(
                (folder / "firmware.bin").read_bytes()
            ).hexdigest(),
        )
    names = (
        "CMakeLists.txt",
        "platformio.ini",
        "sdkconfig.defaults",
        "src/CMakeLists.txt",
        "src/idf_component.yml",
        "src/main.c",
    )
    manifest["sources"] = {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest()
        for name in names
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
