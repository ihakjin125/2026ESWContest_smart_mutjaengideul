"""Timed acquisition and automatic learning. Independent of the GUI clock."""

from collections import defaultdict
from datetime import datetime, timezone
import json
import math
import uuid

import numpy as np
import server as db
from core import estimate_rate, train_baseline, signal_quality
from signal_pipeline import latest_signal
from signal_processing import PROFILE


class TimedCapture:
    def __init__(self, source, label, seconds, prepare, now, context):
        if not str(label).strip() or label == "미라벨":
            raise ValueError("행동 범주를 선택하세요.")
        if not (2 <= seconds <= 120 and 0 <= prepare <= 30):
            raise ValueError("수집은 2~120초, 준비는 0~30초로 설정하세요.")
        self.source = {k: v for k, v in source.items() if k != "frames"}
        self.label, self.seconds, self.context = (
            label.strip(),
            seconds,
            dict(context),
        )
        self.start = now + prepare
        self.end = self.start + seconds
        self.frames = []
        self.last_t = -math.inf
        self.state = "preparing" if prepare else "recording"
        self.error = ""
        self.quality = None

    def cancel(self):
        if self.state in ("preparing", "recording"):
            self.state = "cancelled"

    def update(self, now, frames, connected=True):
        if self.state not in ("preparing", "recording"):
            return self.state
        if not connected:
            self.state, self.error = (
                "failed",
                "수집 중 보드 연결이 끊겼습니다. 이번 구간은 학습에 넣지 않습니다.",
            )
            return self.state
        self.state = "preparing" if now < self.start else "recording"
        for frame in frames:
            t = frame["t"]
            if self.start <= t <= min(now, self.end) and t > self.last_t:
                self.frames.append(dict(frame))
                self.last_t = t
        if now >= self.end:
            try:
                self.quality = check_capture(
                    self.frames, self.start, self.seconds
                )
                self.state = "complete"
            except ValueError as exc:
                self.state, self.error = "failed", str(exc)
        return self.state


def check_capture(frames, start, seconds):
    if len(frames) < max(4, int(seconds * 15)):
        raise ValueError(
            "수신 프레임이 부족합니다. 초당 20프레임 이상의 CSI 출력을 확인하세요."
        )
    t = np.asarray([f["t"] for f in frames])
    rate = estimate_rate(frames)
    if np.any(np.diff(t) <= 0) or rate < 20:
        raise ValueError(
            "수신 시간 또는 샘플링 속도를 확인하세요. 최소 20 Hz가 필요합니다."
        )
    if (
        t[0] - start > 0.25
        or start + seconds - t[-1] > 0.25
        or np.max(np.diff(t)) > 0.5
    ):
        raise ValueError(
            "수집 구간에 긴 신호 공백이 있어 자동 학습에서 제외했습니다. 원본 저널은 유지됩니다."
        )
    quality = signal_quality(
        frames, "raw_iq_52" if "amp" in frames[0] else "processed_1d"
    )
    if not quality["transport_ok"]:
        raise ValueError(
            "수집 구간 시간 확인 실패: " + ", ".join(quality["issues"])
        )
    return {
        "rate_hz": round(rate, 2),
        "frame_count": len(frames),
        "max_gap_seconds": float(np.max(np.diff(t))),
        "coverage_seconds": float(t[-1] - t[0]),
        "requested_seconds": seconds,
        "signal_quality": quality,
    }


def save_capture(job):
    if job.state != "complete":
        raise ValueError("완료된 수집 구간만 저장할 수 있습니다.")
    mode = job.context["mode"]
    # Replaying one file never creates a new independent evaluation group.
    group = job.source["id"] if mode == "practice" else job.context["round_id"]
    sid = uuid.uuid4().hex
    frames = [
        dict(f, source_t=f["t"], t=f["t"] - job.frames[0]["t"])
        for f in job.frames
    ]
    collection = dict(
        job.context,
        source_id=job.source["id"],
        source_start=job.start,
        source_end=job.end,
        requested_seconds=job.seconds,
    )
    session = {
        "id": sid,
        "name": f"{'연습' if mode == 'practice' else '실측'} · {job.label} · {job.seconds:g}초",
        "frames": frames,
        "representation": job.source["representation"],
        "source_path": "replay_capture"
        if mode == "practice"
        else "live_capture",
        "suggested_label": job.label,
        "experiment_id": group,
        "collection": collection,
        "note": job.context.get("note", ""),
        "quality": job.quality,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    db.write_json(db.SESSIONS / f"{sid}.json", session)
    with db.LOCK:
        db.CACHE[sid] = session
    segment = dict(
        session,
        id=uuid.uuid4().hex,
        source_id=sid,
        source_name=session["name"],
        label=job.label,
        start=0,
        end=frames[-1]["t"],
        processing={"stored": "original_iq", "training_profile": PROFILE},
    )
    db.write_json(db.SEGMENTS / f"{segment['id']}.json", segment)
    return segment


def collection_records(context, representation):
    return [
        r
        for r in db.saved_segments()
        if r["representation"] == representation
        and all(
            r.get("collection", {}).get(k) == context[k]
            for k in ("dataset", "mode", "hardware")
        )
    ]


def readiness(records, seconds):
    groups, counts = defaultdict(set), defaultdict(int)
    for record in records:
        counts[record["label"]] += 1
        times = np.asarray([f["t"] for f in record["frames"]])
        count = max(0, int(np.floor((times[-1] - times[0] + 0.025) / seconds)))
        for index in range(count):
            start = times[0] + index * seconds
            inside = times[
                (times >= start - 1e-9) & (times <= start + seconds + 1e-9)
            ]
            if (
                len(inside) >= seconds * 30
                and np.max(np.diff(inside)) <= 0.15
                and inside[0] - start <= 0.04
                and start + seconds - inside[-1] <= 0.04
            ):
                groups[record["label"]].add(record["experiment_id"])
                break
    missing = []
    if len(counts) < 2:
        missing.append("서로 다른 행동 2종 이상을 기록하세요.")
    for name in sorted(counts):
        needed = 3 - len(groups[name])
        if needed > 0:
            missing.append(
                f"{name}: {seconds}초 이상의 다른 측정 회차 {needed}개가 더 필요합니다."
            )
    errors = [
        r["processing_error"] for r in records if r.get("processing_error")
    ]
    missing.extend(sorted(set(errors)))
    return {
        "ready": not missing,
        "message": "\n".join(missing)
        if missing
        else "학습·검증·평가를 분리할 수 있습니다.",
        "counts": dict(counts),
        "groups": {k: len(v) for k, v in groups.items()},
    }


def fingerprint(records, seconds):
    return json.dumps(
        [
            PROFILE,
            seconds,
            sorted((r["id"], r["label"], r["experiment_id"]) for r in records),
        ]
    )


def train_collection(records, seconds, context):
    state = readiness(records, seconds)
    if not state["ready"]:
        raise ValueError(state["message"])
    model, result = train_baseline(records, seconds)
    c6_configs = {
        (f.get("layout"), f.get("radio", {}).get("channel"))
        for r in records
        for f in r["frames"]
        if f.get("csi_profile") == "c6_espnow_ht20_v1"
    }
    if len(c6_configs) > 1:
        raise ValueError("C6 무선 채널·형식이 다른 기록을 섞을 수 없습니다.")
    result["radio_configuration"] = (
        list(next(iter(c6_configs))) if c6_configs else None
    )
    import joblib

    model_id = uuid.uuid4().hex
    result.update(
        model_id=model_id,
        collection={k: context[k] for k in ("dataset", "mode", "hardware")},
        fingerprint=fingerprint(records, seconds),
        segment_ids=[r["id"] for r in records],
        feature_profile=PROFILE,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    signals_file = db.MODELS / f"{model_id}-signals.npz"
    np.savez_compressed(signals_file, **model.training_input)
    del model.training_input
    result["processed_signals_file"] = signals_file.name
    model_file = db.MODELS / f"{model_id}.joblib"
    result["model_path"] = str(model_file)
    joblib.dump({"model": model, "metadata": result}, model_file)
    db.write_json(db.MODELS / f"{model_id}.json", result)
    return result


def predict_frames(result, frames, representation):
    if (
        result.get("feature_profile") != PROFILE
        or result.get("model") != "CSI_CNN3_v2"
    ):
        raise ValueError(
            "전처리·학습 방식이 변경되었습니다. 기존 원본 기록으로 다시 학습하세요."
        )
    if representation != result["representation"]:
        raise ValueError("현재 신호와 모델의 데이터 유형이 다릅니다.")
    seconds = result["window_seconds"]
    if not frames or frames[-1]["t"] - frames[0]["t"] < seconds - 0.025:
        raise ValueError(f"새 신호가 {seconds}초 이상 쌓일 때까지 기다리세요.")
    end = frames[-1]["t"]
    recent = [f for f in frames if end - seconds <= f["t"] <= end]
    expected = result.get("radio_configuration")
    if expected and any(
        [f.get("layout"), f.get("radio", {}).get("channel")] != expected
        for f in recent
    ):
        raise ValueError(
            "모델과 C6 무선 채널·형식이 다릅니다. 같은 설정으로 수집·인식하세요."
        )
    check_capture(recent, end - seconds, seconds)
    signal = latest_signal(recent, representation, seconds)
    import joblib

    # Only load models generated by this app from its own models folder.
    model_id = result["model_id"]
    if len(model_id) != 32 or not model_id.isalnum():
        raise ValueError("모델 ID가 올바르지 않습니다.")
    model = joblib.load(db.MODELS / f"{model_id}.joblib")["model"]
    probabilities = model.predict_proba(
        np.asarray([np.asarray(signal["components"]).T], dtype=np.float32)
    )[0]
    index = int(np.argmax(probabilities))
    ordered = np.sort(probabilities)
    confident = probabilities[index] >= result.get(
        "score_threshold", 0.65
    ) and ordered[-1] - ordered[-2] >= result.get("score_margin", 0.15)
    return {
        "label": str(model.classes_[index]) if confident else "판단 보류",
        "candidate": str(model.classes_[index]),
        "reason": "" if confident else "점수가 낮거나 후보 행동이 비슷합니다.",
        "score": float(probabilities[index]),
        "scores": dict(
            zip(map(str, model.classes_), map(float, probabilities))
        ),
        "input_signal": signal,
    }
