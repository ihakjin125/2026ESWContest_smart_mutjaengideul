"""Explicit C6 installation; refuses another chip and backs up before writing."""

from pathlib import Path
import hashlib
import json
import sys
import time


def flash(port, role, destination):
    import esptool
    from esptool.cmds import detect_chip, detect_flash_size

    if role not in ("receiver", "transmitter"):
        raise ValueError("송신·수신 역할을 선택하세요.")
    root = (
        Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
        / "firmware-c6"
        / "bin"
    )
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    image = root / (role + ".bin")
    if (
        hashlib.sha256(image.read_bytes()).hexdigest()
        != manifest[role]["sha256"]
    ):
        raise ValueError("펌웨어 파일 검증에 실패했습니다.")
    device = detect_chip(port)
    try:
        if device.CHIP_NAME != "ESP32-C6":
            raise ValueError(
                f"연결된 보드는 {device.CHIP_NAME}입니다. C6만 설치할 수 있습니다."
            )
        if (
            device.secure_download_mode
            or device.get_secure_boot_enabled()
            or device.get_flash_encryption_enabled()
        ):
            raise ValueError(
                "보안 부팅/암호화 보드에는 이 설치기를 사용하지 않습니다."
            )
        stub = device.run_stub()
        size = detect_flash_size(stub)
        if size not in ("4MB", "8MB", "16MB"):
            raise ValueError(
                "4·8·16MB C6 개발 보드만 지원합니다. 제품의 플래시 크기를 확인하세요."
            )
        count = int(size[:-2]) * 1024 * 1024
        folder = Path(destination)
        folder.mkdir(parents=True, exist_ok=True)
        backup = folder / f"C6-{port}-{time.time_ns()}-before.bin"
        print("기존 전체 플래시 백업 중...", flush=True)
        data = stub.read_flash(0, count)
        if len(data) != count:
            raise ValueError("백업 길이가 맞지 않아 설치를 중단했습니다.")
        backup.write_bytes(data)
        if (
            hashlib.sha256(backup.read_bytes()).digest()
            != hashlib.sha256(data).digest()
        ):
            raise ValueError("백업 저장 검증에 실패했습니다.")
        backup.with_suffix(".json").write_text(
            json.dumps(
                dict(
                    chip=device.CHIP_NAME,
                    role=role,
                    mac=list(device.read_mac()),
                    bytes=count,
                    sha256=hashlib.sha256(data).hexdigest(),
                ),
                indent=2,
            ),
            encoding="utf-8",
        )
        stub.hard_reset()
    finally:
        device._port.close()
    print("백업 완료. C6 펌웨어 설치 및 검증 중...", flush=True)
    esptool.main(
        [
            "--chip",
            "esp32c6",
            "--port",
            port,
            "--baud",
            "460800",
            "write_flash",
            "--flash_mode",
            "dio",
            "--flash_size",
            "4MB",
            "0x0",
            str(image),
        ]
    )
    print(
        "설치 완료. USB를 다시 연결한 뒤 앱에서 보드를 연결하세요.", flush=True
    )


def worker(port, role, destination, log):
    import traceback

    with open(log, "w", encoding="utf-8", buffering=1) as stream:
        sys.stdout = sys.stderr = stream
        try:
            flash(port, role, destination)
            return 0
        except BaseException:
            traceback.print_exc()
            return 1
