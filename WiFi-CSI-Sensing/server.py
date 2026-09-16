"""Local storage and serial acquisition for the desktop application."""

from collections import deque
import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import threading
import time
import uuid
from live_timing import LiveClock
from radio import upgrade_record, board_layout

from core import read_signal, source_id, parse_csi_line

ROOT = Path(__file__).resolve().parent
DATA = Path(
    os.environ.get("WIFI_SENSING2_DATA_DIR")
    or (
        Path(sys.executable).parent / "WifiSensing2.0-data"
        if getattr(sys, "frozen", False)
        else ROOT / "data-v2"
    )
)
SESSIONS = DATA / "sessions"
SEGMENTS = DATA / "segments"
MODELS = DATA / "models"
for folder in (SESSIONS, SEGMENTS, MODELS):
    folder.mkdir(parents=True, exist_ok=True)

CACHE = {}
LOCK = threading.RLock()


def write_json(path, value):
    temp = path.with_suffix(".tmp")
    temp.write_text(
        json.dumps(value, ensure_ascii=False, allow_nan=False),
        encoding="utf-8",
    )
    temp.replace(path)


def summary(session):
    frames = session["frames"]
    return {k: v for k, v in session.items() if k != "frames"} | {
        "count": len(frames),
        "start": frames[0]["t"] if frames else 0,
        "end": frames[-1]["t"] if frames else 0,
        "duration": frames[-1]["t"] - frames[0]["t"] if frames else 0,
    }


def make_session(
    blob, filename, rate=60, origin="import", note="", suggested_label="미라벨"
):
    frames, kind, quality = read_signal(blob, filename, rate)
    sid = source_id(blob, kind, rate)
    return {
        "id": sid,
        "name": filename,
        "frames": frames,
        "representation": kind,
        "quality": quality,
        "source_path": origin,
        "suggested_label": suggested_label,
        "note": note,
        "experiment_id": sid,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def load_session(sid):
    with LOCK:
        if sid == LIVE.sid:
            return LIVE.snapshot()
        if sid in CACHE:
            return CACHE[sid]
    if not sid.isalnum() or len(sid) > 40:
        raise ValueError("잘못된 기록 ID입니다.")
    file = SESSIONS / f"{sid}.json"
    if not file.exists():
        raise ValueError("기록을 찾을 수 없습니다.")
    result = upgrade_record(json.loads(file.read_text(encoding="utf-8")))
    with LOCK:
        CACHE[sid] = result
    return result


class LiveReader:
    def __init__(self):
        self.sid = ""
        self.port = None
        self.thread = None
        self.stop_event = threading.Event()
        self.frames = deque(maxlen=60000)
        self.error = ""
        self.rejected = 0
        self.received = 0
        self.device = ""
        self.header = None
        self.log_path = None
        self.started_at = 0.0
        self.board_info = {}
        self.networks = []
        self.event_seq = 0
        self.last_event = ""
        self.control_lock = threading.Lock()
        self.clock_tracker = LiveClock()
        self.warmup_frames = 0

    def elapsed(self):
        return (
            time.perf_counter() - self.started_at if self.started_at else 0.0
        )

    def snapshot(self):
        return {
            "id": self.sid,
            "name": f"실시간 {self.device}",
            "frames": list(self.frames),
            "representation": "raw_iq_52",
            "source_path": "live_serial",
            "experiment_id": self.sid,
            "suggested_label": "미라벨",
            "quality": {
                "rejected": self.rejected,
                "time_basis": "device_aligned_when_available",
                "warmup_frames": self.warmup_frames,
                "received": self.received,
                "trimmed": max(0, self.received - len(self.frames)),
            },
            "note": "장치 시간이 있으면 수신 시각에 정렬한 장치 시간축을 사용합니다. 재접속 직후 시간 확인 전 데이터는 표시·학습에서 제외합니다. 원래 장치 시간과 수신 시각·I/Q는 저널에 보존됩니다.",
            "journal": self.log_path.name if self.log_path else None,
        }

    def status(self):
        with LOCK:
            return {
                "connected": bool(
                    self.thread
                    and self.thread.is_alive()
                    and not self.stop_event.is_set()
                ),
                "id": self.sid,
                "port": self.device,
                "error": self.error,
                "received": self.received,
                "rejected": self.rejected,
                "buffer_count": len(self.frames),
                "synchronizing": not self.clock_tracker.ready,
                "warmup_frames": self.warmup_frames,
            }

    def board_status(self):
        with LOCK:
            return dict(
                self.board_info,
                networks=list(self.networks),
                event_seq=self.event_seq,
                last_event=self.last_event,
            )

    def command(self, payload):
        if not self.status()["connected"]:
            raise ValueError("USB 보드를 먼저 연결하세요.")
        if payload.get("cmd") not in (
            "status",
            "scan",
            "connect",
            "disconnect",
        ):
            raise ValueError("지원하지 않는 보드 명령입니다.")
        # Commands (including credentials) are never persisted in journals or logs.
        encoded = (json.dumps(payload, ensure_ascii=False) + "\n").encode(
            "utf-8"
        )
        if len(encoded) > 1000:
            raise ValueError("Wi-Fi 설정이 너무 깁니다.")
        with self.control_lock:
            self.port.write(encoded)

    def connect(self, device, baud):
        import serial
        from serial.tools import list_ports

        if device not in [p.device for p in list_ports.comports()]:
            raise ValueError(
                "포트가 보이지 않습니다. 보드와 데이터 USB 케이블을 연결하세요."
            )
        if baud not in (115200, 460800, 921600):
            raise ValueError("지원하지 않는 전송 속도입니다.")
        if self.status()["connected"]:
            raise ValueError("현재 연결을 먼저 종료하세요.")
        self.port = serial.Serial()
        self.port.port, self.port.baudrate, self.port.timeout = (
            device,
            baud,
            0.2,
        )
        self.port.write_timeout = 2
        self.port.dtr = self.port.rts = False
        self.port.open()
        with LOCK:
            self.sid = uuid.uuid4().hex
            self.frames.clear()
            self.received = self.rejected = 0
            self.error = ""
            self.board_info = {}
            self.networks = []
            self.last_event = ""
            self.event_seq += 1
            self.device = device
            self.header = None
            self.log_path = SESSIONS / f"{self.sid}.raw.jsonl"
            self.started_at = time.perf_counter()
            self.clock_tracker = LiveClock()
            self.warmup_frames = 0
            self.stop_event.clear()
        self.thread = threading.Thread(target=self.read_loop, daemon=True)
        self.thread.start()
        return self.status()

    def read_loop(self):
        start = self.started_at
        try:
            with self.log_path.open("a", encoding="utf-8") as journal:
                while not self.stop_event.is_set():
                    line = (
                        self.port.readline(65536)
                        .decode("utf-8", errors="replace")
                        .strip()
                    )
                    if not line:
                        continue
                    if line.startswith("{"):
                        try:
                            event = json.loads(line)
                            if isinstance(event, dict) and event.get(
                                "event"
                            ) in ("status", "scan"):
                                with LOCK:
                                    if event["event"] == "scan":
                                        self.networks = event.get(
                                            "networks", []
                                        )
                                    else:
                                        self.board_info.update(event)
                                    self.last_event = event["event"]
                                    self.event_seq += 1
                                continue
                        except ValueError:
                            pass
                    if "data" in line and "[" not in line:
                        fields = next(csv.reader([line]))
                        if "data" in fields:
                            self.header = fields
                            continue
                    # Python 3.12 on Windows exposes a coarse GetTickCount64
                    # monotonic clock (~15 ms). perf_counter uses QPC and keeps
                    # successive CSI arrivals distinct even at 50+ Hz.
                    now = time.perf_counter() - start
                    frame = parse_csi_line(
                        line,
                        self.header,
                        now,
                        layout=board_layout(self.board_info),
                    )
                    if frame is None:
                        self.rejected += 1
                        continue
                    frame["device_t"] = frame["t"]
                    frame["arrival_t"] = now
                    mapped = self.clock_tracker.map_time(
                        frame["device_t"], now
                    )
                    if (
                        frame.get("csi_profile") == "c6_espnow_ht20_v1"
                        and frame.get("gain_ready") is not True
                    ):
                        mapped = None
                    frame["accepted_live"] = mapped is not None
                    frame["stream_epoch"] = self.clock_tracker.epoch
                    frame["t"] = now if mapped is None else mapped
                    if mapped is None:
                        self.warmup_frames += 1
                    else:
                        with LOCK:
                            frame["seq"] = self.received
                            self.received += 1
                            self.frames.append(frame)
                    journal.write(json.dumps(frame, allow_nan=False) + "\n")
                    journal.flush()
        except Exception as exc:
            self.error = str(exc)
        finally:
            if self.port:
                self.port.close()
            with LOCK:
                snapshot = self.snapshot()
            if snapshot["frames"]:
                write_json(SESSIONS / f"{self.sid}.json", snapshot)

    def disconnect(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=2)
        return self.status()


LIVE = LiveReader()


def saved_segments():
    return [
        upgrade_record(json.loads(p.read_text(encoding="utf-8")))
        for p in sorted(SEGMENTS.glob("*.json"))
    ]


def save_segment(payload):
    session = load_session(str(payload["source_id"]))
    start, end = float(payload["start"]), float(payload["end"])
    if end <= start:
        raise ValueError("끝 시간이 시작 시간보다 커야 합니다.")
    all_frames = session["frames"]
    if (
        not all_frames
        or start < all_frames[0]["t"] - 0.01
        or end > all_frames[-1]["t"] + 0.01
    ):
        raise ValueError(
            "선택 구간이 현재 기록 범위를 벗어납니다. 오래된 라이브 기록은 원본 저널에 남아 있습니다."
        )
    selected = [f for f in all_frames if start <= f["t"] <= end]
    if len(selected) < 4:
        raise ValueError("4프레임 이상의 구간을 선택하세요.")
    label = str(payload.get("label", "")).strip()[:80]
    if not label or label == "미라벨":
        raise ValueError("저장할 행동 라벨을 선택하거나 직접 입력하세요.")
    group = str(
        payload.get("experiment_id", session["experiment_id"])
    ).strip()[:120]
    if not group:
        raise ValueError("측정 세션 ID를 입력하세요.")
    # Segments cut from one source may never be split across train/test groups.
    for old in saved_segments():
        if old["source_id"] == session["id"] and old["experiment_id"] != group:
            raise ValueError(
                "같은 원본 기록에는 기존 측정 세션 ID를 사용하세요: "
                + old["experiment_id"]
            )
    segment = {
        "id": uuid.uuid4().hex,
        "label": label,
        "start": start,
        "end": end,
        "frames": selected,
        "source_id": session["id"],
        "source_name": session["name"],
        "source_path": session["source_path"],
        "representation": session["representation"],
        "experiment_id": group,
        "note": str(payload.get("note", ""))[:1500],
        "processing": payload.get("processing", {}),
        "quality": session.get("quality", {}),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    write_json(SEGMENTS / f"{segment['id']}.json", segment)
    return summary(segment)
