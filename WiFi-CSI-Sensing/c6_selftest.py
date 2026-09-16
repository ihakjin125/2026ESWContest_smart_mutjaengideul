"""C6 protocol and installer guards with simulated transports only."""

from pathlib import Path
from unittest.mock import patch, MagicMock
import json
import tempfile


def run(check):
    import flash_c6
    from core import parse_csi_line
    from signal_pipeline import latest_signal
    from services import hardware_for_chip

    check(
        hardware_for_chip("esp32c6", {"role": "transmitter", "mode": "espnow"})
        is None,
        "TX USB cannot be treated as a sensing receiver",
    )
    check(
        hardware_for_chip("esp32c6", {"role": "receiver", "mode": "espnow"})
        == "c6_espnow_ht20_v1",
        "C6 RX has a separate collection profile",
    )
    packet = dict(
        timestamp=0,
        chip="esp32c6",
        layout="c6_ht20_packed57",
        csi_profile="c6_espnow_ht20_v1",
        channel=11,
        data=[8, 12] * 57,
        gain_ready=True,
        gain_compensation=1.2,
    )
    frames = [
        parse_csi_line(json.dumps(dict(packet, timestamp=i / 60)))
        for i in range(121)
    ]
    check(
        latest_signal(frames, "raw_iq_52", 2)["profile"]
        == "csi_physical50_pca3_v2",
        "C6 HT20 fixture reaches the shared final processing path",
    )
    for invalid in (
        dict(packet, gain_compensation=float("nan")),
        dict(packet, data=[1] * 113),
    ):
        check(
            parse_csi_line(json.dumps(invalid)) is None,
            "invalid gain or payload rejected",
        )
    for change in (
        {"gain_ready": False},
        {"radio": {"channel": 6}},
        {"layout": "c6_ht20_centered64"},
    ):
        bad = [dict(f) for f in frames]
        bad[40].update(change)
        try:
            latest_signal(bad, "raw_iq_52", 2)
        except ValueError:
            check(
                True, "warmup/channel/format transition cannot enter inference"
            )
        else:
            raise AssertionError("invalid transition accepted")
    # No serial port is opened by these tests.
    with tempfile.TemporaryDirectory() as temp:
        wrong = MagicMock()
        wrong.CHIP_NAME = "ESP32-C3"
        with (
            patch("esptool.cmds.detect_chip", return_value=wrong),
            patch("esptool.main") as write,
        ):
            try:
                flash_c6.flash("QA", "receiver", temp)
            except ValueError:
                pass
            else:
                raise AssertionError("wrong chip accepted")
            check(
                not write.called and not wrong.run_stub.called,
                "installer refuses C3 before any write",
            )
        device = MagicMock()
        device.CHIP_NAME = "ESP32-C6"
        device.secure_download_mode = False
        device.get_secure_boot_enabled.return_value = False
        device.get_flash_encryption_enabled.return_value = False
        device.run_stub.return_value.read_flash.return_value = b"short backup"
        with (
            patch("esptool.cmds.detect_chip", return_value=device),
            patch("esptool.cmds.detect_flash_size", return_value="4MB"),
            patch("esptool.main") as write,
        ):
            try:
                flash_c6.flash("QA", "transmitter", temp)
            except ValueError:
                pass
            else:
                raise AssertionError("incomplete backup accepted")
            check(not write.called, "backup failure prevents firmware write")
        device.run_stub.return_value.read_flash.return_value = bytes(
            4 * 1024 * 1024
        )
        device.read_mac.return_value = (1, 2, 3, 4, 5, 6)
        with (
            patch("esptool.cmds.detect_chip", return_value=device),
            patch("esptool.cmds.detect_flash_size", return_value="4MB"),
            patch("esptool.main") as write,
        ):
            flash_c6.flash("QA", "receiver", temp)
            check(
                write.called
                and list(Path(temp).glob("*-before.bin"))[0].stat().st_size
                == 4 * 1024 * 1024,
                "validated full backup precedes explicit C6 image write in simulated installer",
            )
            check(
                write.call_args.args[0][:2] == ["--chip", "esp32c6"],
                "write command retains C6 chip guard",
            )
