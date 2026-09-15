"""CSI parsing, signal inspection and grouped baseline training.

Raw I/Q is retained. Preprocessed NPY never masquerades as raw CSI.
"""

import csv
import hashlib
import io
import json
from pathlib import Path

import numpy as np

from radio import (
    CARRIERS as SUBCARRIERS,
    amplitude as map_amplitude,
    infer_legacy_layout,
)


def parse_csi_line(line, header=None, arrival=None, layout=None):
    line = line.strip()
    if not line:
        return None
    row = {}
    try:
        if line.startswith("{"):
            row = json.loads(line)
            iq = row.get("data", row.get("iq"))
            iq = json.loads(iq) if isinstance(iq, str) else iq
        else:
            fields = next(csv.reader([line]))
            if header:
                row = dict(zip(header, fields))
            if row.get("data") or row.get("iq_json"):
                iq = json.loads(row.get("data") or row["iq_json"])
            else:
                start, end = line.find("["), line.rfind("]")
                if start < 0 or end <= start:
                    return None
                iq = json.loads(line[start : end + 1])
            if not header and not line.startswith("CSI_DATA"):
                row["real_timestamp"] = fields[0]
        if not isinstance(iq, list) or len(iq) not in (114, 128):
            return None
        values = np.asarray(iq, dtype=float)
        if (
            not np.isfinite(values).all()
            or np.any(values < -128)
            or np.any(values > 127)
        ):
            return None
        if np.any(values != np.floor(values)):
            return None
        actual_layout = row.get("layout") or layout or infer_legacy_layout(iq)
        invalid = row.get(
            "first_word_invalid", row.get("first_word", False)
        ) in (True, 1, "1", "true")
        amplitude = map_amplitude(iq, actual_layout, invalid)
        if row.get("csi_profile") == "c6_espnow_ht20_v1":
            gain = float(row.get("gain_compensation", 0))
            if (
                not np.isfinite(gain)
                or gain <= 0
                or row.get("gain_ready") not in (True, False)
            ):
                return None
        timestamp = row.get(
            "real_timestamp",
            row.get("timestamp", row.get("t", row.get("time_seconds"))),
        )
        basis = "device_seconds"
        if timestamp in (None, ""):
            timestamp = row.get("local_timestamp")
            if timestamp not in (None, ""):
                timestamp = float(timestamp) / 1e6
                basis = "device_microseconds"
            else:
                timestamp = arrival
                basis = "host_arrival"
        timestamp = float(timestamp)
        if not np.isfinite(timestamp):
            return None
        rssi = (
            float(row["rssi"]) if row.get("rssi") not in (None, "") else None
        )
        if rssi is not None and not np.isfinite(rssi):
            rssi = None
        return {
            "t": timestamp,
            "amp": amplitude.tolist(),
            "iq": values.astype(int).tolist(),
            "rssi": rssi,
            "raw_line": line,
            "clock": basis,
            "radio": {
                key: row[key]
                for key in (
                    "channel",
                    "noise_floor",
                    "fft_gain",
                    "agc_gain",
                    "rate",
                )
                if key in row
            },
            "first_word_invalid": row.get(
                "first_word_invalid", row.get("first_word")
            ),
            "layout": actual_layout,
            "carrier_ids": SUBCARRIERS,
            **{
                key: row[key]
                for key in (
                    "csi_profile",
                    "gain_compensation",
                    "gain_ready",
                    "rx_seq",
                    "dropped",
                    "chip",
                )
                if key in row
            },
        }
    except (ValueError, TypeError, KeyError, OverflowError, csv.Error):
        return None


def parse_csv(text, rate=60):
    frames, header = [], None
    rejected = 0
    for line in text.splitlines():
        fields = next(csv.reader([line]), [])
        if ("data" in fields or "iq_json" in fields) and "[" not in line:
            header = fields
            continue
        frame = parse_csi_line(line, header, len(frames) / rate)
        if frame is None:
            if line.strip():
                rejected += 1
            continue
        if frames and frame["t"] <= frames[-1]["t"]:
            rejected += 1
            continue
        frames.append(frame)
    if len(frames) < 2:
        raise ValueError(
            "유효한 CSI 프레임이 2개 이상 필요합니다. CSV의 data와 타임스탬프를 확인하세요."
        )
    start = frames[0]["t"]
    for f in frames:
        f["device_t"] = f["t"]
        f["t"] -= start
    return frames, rejected


def read_signal(blob, filename, rate=60):
    if not 1 <= rate <= 1000:
        raise ValueError("샘플링 주파수는 1~1000 Hz로 입력하세요.")
    suffix = Path(filename).suffix.lower()
    if suffix == ".csv":
        text = blob.decode("utf-8-sig")
        rows = csv.DictReader(io.StringIO(text))
        if rows.fieldnames and "processed_signal" in rows.fieldnames:
            records = list(rows)
            if records and all(
                r.get("processed_signal", "").strip() for r in records
            ):
                frames = [
                    {
                        "t": float(r["time_seconds"]),
                        "signal": float(r["processed_signal"]),
                    }
                    for r in records
                ]
                if (
                    len(frames) < 2
                    or not np.isfinite(
                        [[f["t"], f["signal"]] for f in frames]
                    ).all()
                    or np.any(np.diff([f["t"] for f in frames]) <= 0)
                ):
                    raise ValueError("전처리 CSV 시간과 신호 값을 확인하세요.")
                start = frames[0]["t"]
                for f in frames:
                    f["t"] -= start
                return (
                    frames,
                    "processed_1d",
                    {"rejected": 0, "time_basis": "exported_seconds"},
                )
        frames, rejected = parse_csv(text, rate)
        return (
            frames,
            "raw_iq_52",
            {"rejected": rejected, "time_basis": frames[0]["clock"]},
        )
    if suffix == ".jsonl":
        frames = []
        rejected = 0
        for line in blob.decode("utf-8-sig").splitlines():
            try:
                saved = json.loads(line)
            except ValueError:
                rejected += 1
                continue
            if (
                not isinstance(saved, dict)
                or saved.get("accepted_live") is False
            ):
                rejected += 1
                continue
            frame = parse_csi_line(line)
            if frame and (not frames or frame["t"] > frames[-1]["t"]):
                for key in ("device_t", "arrival_t", "stream_epoch"):
                    if key in saved:
                        frame[key] = saved[key]
                frames.append(frame)
        if len(frames) < 2:
            raise ValueError("원본 CSI 저널에 유효한 프레임이 부족합니다.")
        start = frames[0]["t"]
        for frame in frames:
            frame["t"] -= start
        return (
            frames,
            "raw_iq_52",
            {"rejected": rejected, "time_basis": "journal_seconds"},
        )
    if suffix == ".npy":
        data = np.load(io.BytesIO(blob), allow_pickle=False)
        if (
            data.ndim > 2
            or data.size > 2_000_000
            or data.dtype.kind not in "fiu"
        ):
            raise ValueError("숫자로 구성된 1차원 전처리 NPY만 지원합니다.")
        data = np.squeeze(data)
        if data.ndim != 1 or len(data) < 2 or not np.isfinite(data).all():
            raise ValueError(
                "유한한 숫자로 구성된 1차원 전처리 NPY만 지원합니다."
            )
        return (
            [{"t": i / rate, "signal": float(v)} for i, v in enumerate(data)],
            "processed_1d",
            {
                "rejected": 0,
                "time_basis": "assumed_rate",
                "assumed_rate_hz": rate,
            },
        )
    raise ValueError(
        "원본 CSI CSV/JSONL 또는 1차원 전처리 NPY 파일을 선택하세요."
    )


def source_id(blob, representation, rate):
    # Re-importing identical data keeps the same group to reduce leakage.
    return hashlib.sha256(blob + representation.encode()).hexdigest()[:24]


def estimate_rate(frames):
    delta = np.diff([f["t"] for f in frames])
    good = delta[delta > 0]
    return float(1 / np.median(good)) if len(good) else 60.0


def signal_quality(frames, representation):
    """Transport checks and variation descriptors, never an action/noise verdict."""
    times = np.asarray([f["t"] for f in frames], dtype=float)
    dt = np.diff(times)
    issues = []
    if len(dt) == 0 or not np.isfinite(times).all() or np.any(dt <= 0):
        issues.append("시간 순서 오류")
    gap = float(np.max(dt)) if len(dt) else 0.0
    rate = (
        (len(times) - 1) / (times[-1] - times[0])
        if len(times) > 1 and times[-1] > times[0]
        else 0.0
    )
    if gap > 0.5:
        issues.append("0.5초 초과 수신 공백")
    if rate < 20:
        issues.append("수신 속도 20 Hz 미만")
    device_gap = None
    if len(frames) > 1 and all("device_t" in f for f in frames):
        device = np.asarray([f["device_t"] for f in frames], dtype=float)
        diff = np.diff(device)
        device_gap = float(np.max(diff))
        if (
            not np.isfinite(device).all()
            or np.any(diff <= 0)
            or np.any(diff > 0.5)
        ):
            issues.append("장치 시간 단절 · 재접속 버퍼 확인")
        elif np.any(np.abs(diff - dt) > 0.25):
            issues.append("장치·수신 시간 불일치")
    if len({f.get("stream_epoch", 0) for f in frames}) > 1:
        issues.append("수집 중 시간 동기화 변경")
    raw = np.asarray(
        [
            f["amp"] if representation == "raw_iq_52" else [f["signal"]]
            for f in frames
        ]
    )
    if not np.isfinite(raw).all():
        issues.append("신호 값 오류")
    variation = None
    if representation == "raw_iq_52":
        variation = float(
            np.median(raw.std(axis=0) / np.maximum(np.median(raw, axis=0), 1))
            * 100
        )
    return {
        "transport_ok": not issues,
        "issues": issues,
        "rate_hz": rate,
        "max_gap_seconds": gap,
        "device_max_gap_seconds": device_gap,
        "relative_channel_std_percent": variation,
        "behavior_validated": False,
    }


def inspect_signal(frames, representation, options=None):
    from signal_pipeline import inspect_signal as inspect

    return inspect(frames, representation, options)


def window_features(frames, representation, seconds=2):
    from signal_pipeline import window_features as final_windows

    return final_windows(frames, representation, seconds)


def train_baseline(segments, seconds=2):
    from signal_pipeline import train_baseline as train

    return train(segments, seconds)
