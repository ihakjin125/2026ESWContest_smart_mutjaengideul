"""Headless collection and portable inference for Raspberry Pi 4/5 (64 bit)."""

from pathlib import Path
from collections import deque
from datetime import datetime, timezone
import argparse
import csv
import json
import time
import uuid
import numpy as np
from core import parse_csi_line
from radio import board_layout
from live_timing import LiveClock
from signal_pipeline import latest_signal
from signal_processing import PROFILE
from cnn_runtime import probabilities


def load_bundle(folder):
    folder = Path(folder)
    meta = json.loads((folder / "model.json").read_text(encoding="utf-8"))
    if (
        meta.get("feature_profile") != PROFILE
        or meta.get("model") != "CSI_CNN3_v2"
    ):
        raise ValueError("전처리 버전이 맞는 모델을 PC에서 내보내세요.")
    with np.load(folder / "weights.npz", allow_pickle=False) as data:
        weights = {k: data[k] for k in data.files if k != "input_scale"}
        scale = data["input_scale"]
    return meta, weights, scale


def infer(frames, bundle):
    meta, weights, scale = bundle
    expected = meta.get("radio_configuration")
    recent = [
        f
        for f in frames
        if frames[-1]["t"] - f["t"] <= meta["window_seconds"] + 0.05
    ]
    if expected and any(
        [f.get("layout"), f.get("radio", {}).get("channel")] != expected
        for f in recent
    ):
        raise ValueError("모델과 C6 무선 채널·형식이 다릅니다.")
    waveform = latest_signal(
        frames, meta["representation"], meta["window_seconds"]
    )
    scores = probabilities(
        weights,
        np.asarray(waveform["components"], dtype=np.float32).T[None],
        scale,
        meta["temperature"],
    )[0]
    order = np.argsort(scores)
    index = order[-1]
    accept = (
        scores[index] >= meta["score_threshold"]
        and scores[index] - scores[order[-2]] >= meta["score_margin"]
    )
    return dict(
        label=meta["labels"][index] if accept else "판단 보류",
        scores=dict(zip(meta["labels"], map(float, scores))),
        window_seconds=meta["window_seconds"],
        device_time=frames[-1]["t"],
    )


def main():
    import serial

    parser = argparse.ArgumentParser()
    parser.add_argument("--port", required=True)
    parser.add_argument("--baud", type=int, default=921600)
    parser.add_argument("--model", default=None)
    parser.add_argument("--out", default="pi-records")
    parser.add_argument("--label")
    parser.add_argument("--seconds", type=int, default=30)
    parser.add_argument("--round", dest="round_id", default=None)
    args = parser.parse_args()
    if args.label and (not args.round_id or not 2 <= args.seconds <= 120):
        parser.error(
            "라벨 수집은 --round 회차와 --seconds 2~120을 지정하세요."
        )
    if not args.label and not args.model:
        parser.error("--model 또는 --label을 지정하세요.")
    bundle = load_bundle(args.model) if args.model else None
    output = Path(args.out)
    output.mkdir(parents=True, exist_ok=True)
    sid = uuid.uuid4().hex
    frames = deque(maxlen=7200)
    capture = []
    header = None
    board = {}
    tracker = LiveClock()
    started = time.perf_counter()
    last_report = 0.0
    capture_start = None
    with (
        serial.Serial(args.port, args.baud, timeout=0.2) as port,
        (output / f"{sid}.jsonl").open("w", encoding="utf-8") as journal,
    ):
        port.reset_input_buffer()
        port.write(b'{"cmd":"status"}\n')
        while True:
            line = (
                port.readline(65536).decode("utf-8", errors="replace").strip()
            )
            now = time.perf_counter() - started
            try:
                event = json.loads(line)
            except ValueError:
                event = {}
            if isinstance(event, dict) and event.get("event") == "status":
                board.update(event)
                continue
            if "data" in line and "[" not in line:
                fields = next(csv.reader([line]), [])
                if "data" in fields:
                    header = fields
                    continue
            frame = parse_csi_line(
                line, header, now, layout=board_layout(board)
            )
            if frame:
                device_t = frame["t"]
                mapped = tracker.map_time(device_t, now)
                if (
                    frame.get("csi_profile") == "c6_espnow_ht20_v1"
                    and frame.get("gain_ready") is not True
                ):
                    mapped = None
                frame.update(
                    device_t=device_t,
                    arrival_t=now,
                    t=now if mapped is None else mapped,
                    accepted_live=mapped is not None,
                    stream_epoch=tracker.epoch,
                )
                journal.write(json.dumps(frame, ensure_ascii=False) + "\n")
                journal.flush()
                if mapped is not None:
                    if (
                        frames
                        and frames[-1]["stream_epoch"] != frame["stream_epoch"]
                    ):
                        frames.clear()
                        capture.clear()
                        capture_start = None
                    frames.append(frame)
                    if args.label:
                        if capture_start is None:
                            capture_start = mapped
                        capture.append(frame)
                        if mapped - capture_start >= args.seconds:
                            normalized = [
                                dict(f, t=f["t"] - capture_start)
                                for f in capture
                            ]
                            hardware = (
                                "c6_espnow_ht20_v1"
                                if board.get("mode") == "espnow"
                                else {
                                    "esp32": "router_esp32",
                                    "esp32c3": "router_c3",
                                    "esp32s3": "router_s3",
                                }.get(board.get("chip"), "unknown")
                            )
                            record = dict(
                                id=sid,
                                source_id=sid,
                                experiment_id=args.round_id,
                                label=args.label,
                                name=f"Pi · {args.label}",
                                representation="raw_iq_52",
                                frames=normalized,
                                created_at=datetime.now(
                                    timezone.utc
                                ).isoformat(),
                                collection=dict(
                                    dataset="Pi",
                                    mode="live",
                                    hardware=hardware,
                                ),
                            )
                            target = output / f"{sid}.json"
                            target.write_text(
                                json.dumps(record, ensure_ascii=False),
                                encoding="utf-8",
                            )
                            print(
                                json.dumps(
                                    dict(saved=str(target), label=args.label),
                                    ensure_ascii=False,
                                ),
                                flush=True,
                            )
                            return
            if now - last_report >= 0.6:
                last_report = now
                try:
                    if not frames or now - frames[-1]["t"] > 0.75:
                        raise ValueError("새 신호 대기")
                    if bundle:
                        expected = bundle[0]["collection"]["hardware"]
                        actual = (
                            "c6_espnow_ht20_v1"
                            if board.get("mode") == "espnow"
                            else {
                                "esp32": "router_esp32",
                                "esp32c3": "router_c3",
                                "esp32s3": "router_s3",
                            }.get(board.get("chip"))
                        )
                        if expected != actual:
                            raise ValueError("모델과 보드 구성이 다릅니다.")
                        result = infer(list(frames), bundle)
                    else:
                        result = dict(
                            state="collecting",
                            seconds=0
                            if capture_start is None
                            else now - capture_start,
                        )
                except ValueError as exc:
                    result = dict(label="판단 보류", reason=str(exc))
                print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
