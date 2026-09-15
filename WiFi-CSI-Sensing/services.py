"""V2-only records and model lifecycle. Never shares the V1 data folder."""

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import unicodedata
import uuid
import zipfile

import numpy as np
import server as db
import teaching
from core import signal_quality


DEFAULT_BEHAVIORS = ("정지", "낙상")


def behavior_name(value):
    name = unicodedata.normalize("NFC", " ".join(str(value).split()))
    if not name or name == "미라벨":
        raise ValueError("기록할 행동 이름을 입력하세요. 예: 걷기, 호흡, 앉기")
    if len(name) > 80:
        raise ValueError("행동 이름은 80자 이내로 입력하세요.")
    return name


def custom_behaviors(settings):
    # Category preferences never rename, hide or delete collected records.
    values = settings.get("custom_behaviors", [])
    if not isinstance(values, list):
        values = []
    names = []
    for value in values:
        if not isinstance(value, str):
            continue
        try:
            name = behavior_name(value)
        except ValueError:
            continue
        if name not in DEFAULT_BEHAVIORS and name not in names:
            names.append(name)
    return names


def hardware_for_chip(chip, board=None):
    if chip == "esp32c6":
        return (
            "c6_espnow_ht20_v1"
            if board
            and board.get("role") == "receiver"
            and board.get("mode") == "espnow"
            else None
        )
    return {
        "esp32": "router_esp32",
        "esp32c3": "router_c3",
        "esp32s3": "router_s3",
    }.get(chip)


def baud_for_port(vid):
    # UART bridges need enough throughput for 50 full CSI JSON frames/second.
    # Native Espressif USB ignores the UART line rate and keeps V1 defaults.
    return 921600 if vid in (0x1A86, 0x10C4, 0x0403) else 115200


def settings_path():
    return db.DATA / "workspace.json"


def load_settings():
    try:
        return json.loads(settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_settings(value):
    db.write_json(settings_path(), value)


def scope(record):
    c = record.get("collection", {})
    return (
        record["representation"],
        c.get("mode", "live"),
        c.get("hardware", "unknown"),
    )


def selection_state(records, seconds):
    if not records:
        return (
            False,
            "학습할 기록에 체크하세요. 정지·걷기처럼 행동 2종 이상을 선택합니다.",
        )
    if len({scope(r) for r in records}) != 1:
        return (
            False,
            "서로 다른 장치 또는 원본·전처리 기록이 섞였습니다. 같은 구성의 기록만 선택하세요.",
        )
    c6_configs = {
        (f.get("layout"), f.get("radio", {}).get("channel"))
        for r in records
        for f in r["frames"]
        if f.get("csi_profile") == "c6_espnow_ht20_v1"
    }
    if len(c6_configs) > 1:
        return (
            False,
            "C6 무선 채널·형식이 다른 기록을 섞을 수 없습니다. 같은 설정의 기록만 선택하세요.",
        )
    for record in records:
        if len(record["frames"]) < 4:
            return False, "너무 짧은 기록이 포함되어 있습니다."
        q = signal_quality(record["frames"], record["representation"])
        if not q["transport_ok"]:
            return (
                False,
                f"{record['label']}: 수신 불량 기록을 선택 해제하세요. "
                + ", ".join(q["issues"]),
            )
        if (
            record["frames"][-1]["t"] - record["frames"][0]["t"]
            < seconds - 0.025
        ):
            return (
                False,
                f"{record['label']}: {seconds}초보다 짧은 기록이 있습니다. 판단 구간을 줄이거나 선택 해제하세요.",
            )
    state = teaching.readiness(records, seconds)
    return state["ready"], state["message"].replace(
        "자동 학습 조건을 충족했습니다.",
        "준비 완료 · 체크한 기록만 학습에 사용합니다.",
    )


def train_selected(records, seconds, name):
    ready, reason = selection_state(records, seconds)
    if not ready:
        raise ValueError(reason)
    context = {
        "dataset": name.strip() or "나의 행동 모델",
        "mode": scope(records[0])[1],
        "hardware": scope(records[0])[2],
    }
    result = teaching.train_collection(records, seconds, context)
    result["name"] = context["dataset"]
    result["record_count"] = len(records)
    result["record_labels"] = dict(Counter(r["label"] for r in records))
    result["schema"] = "wifisensing-v2-model"
    result["training_records"] = [
        {
            "id": r["id"],
            "label": r["label"],
            "name": r.get("name", r.get("source_name", "")),
            "experiment_id": r["experiment_id"],
        }
        for r in records
    ]
    db.write_json(db.MODELS / f"{result['model_id']}.json", result)
    return result


def read_model(mid):
    if (
        not isinstance(mid, str)
        or len(mid) != 32
        or any(c not in "0123456789abcdef" for c in mid)
    ):
        return None
    try:
        result = json.loads(
            (db.MODELS / f"{mid}.json").read_text(encoding="utf-8")
        )
        return (
            result
            if result.get("schema") == "wifisensing-v2-model"
            and (db.MODELS / f"{mid}.joblib").exists()
            else None
        )
    except (OSError, ValueError):
        return None


def validate_record(record):
    if (
        not isinstance(record, dict)
        or not str(record.get("label", "")).strip()
        or record.get("label") == "미라벨"
    ):
        raise ValueError("행동 라벨이 포함된 기록 JSON을 선택하세요.")
    kind = record.get("representation")
    frames = record.get("frames")
    if (
        kind not in ("raw_iq_52", "processed_1d")
        or not isinstance(frames, list)
        or not 4 <= len(frames) <= 60000
    ):
        raise ValueError("기록 형식 또는 프레임 수가 지원 범위를 벗어납니다.")
    for f in frames:
        if not isinstance(f, dict) or not np.isfinite(
            float(f.get("t", float("nan")))
        ):
            raise ValueError("기록 시간이 올바르지 않습니다.")
        values = f.get("amp") if kind == "raw_iq_52" else [f.get("signal")]
        if (
            not isinstance(values, list)
            or len(values) not in ((50, 52) if kind == "raw_iq_52" else (1,))
            or not np.isfinite(np.asarray(values, dtype=float)).all()
        ):
            raise ValueError("유효한 신호 값이 없습니다.")
    from radio import upgrade_record

    return upgrade_record(record)


def import_records(paths):
    candidates = []
    for path in map(Path, paths):
        if path.stat().st_size > 200_000_000:
            raise ValueError("200 MB 이하 파일을 가져오세요.")
        if path.suffix.lower() == ".zip":
            with zipfile.ZipFile(path) as archive:
                infos = [
                    i
                    for i in archive.infolist()
                    if i.filename.startswith("segments/")
                    and i.filename.endswith(".json")
                ]
                if (
                    not infos
                    or len(infos) > 500
                    or sum(i.file_size for i in infos) > 200_000_000
                ):
                    raise ValueError(
                        "지원 범위의 라벨 데이터 ZIP을 선택하세요."
                    )
                for info in infos:
                    candidates.append(
                        (
                            validate_record(json.loads(archive.read(info))),
                            info.filename,
                        )
                    )
        else:
            candidates.append(
                (
                    validate_record(
                        json.loads(path.read_text(encoding="utf-8"))
                    ),
                    path.name,
                )
            )
    staged = []
    for record, filename in candidates:
        # Deterministic identity preserves the original evaluation group on reimport.
        original_id = str(
            record.get("id")
            or hashlib.sha256(
                json.dumps(record["frames"]).encode()
            ).hexdigest()
        )
        sid = hashlib.sha256(
            ("v2-import:" + original_id).encode()
        ).hexdigest()[:32]
        if (
            (db.SEGMENTS / f"{sid}.json").exists()
            or (db.DATA / "trash" / "segments" / f"{sid}.json").exists()
            or any(r["id"] == sid for r in staged)
        ):
            continue
        original_group = str(
            record.get("experiment_id")
            or record.get("source_id")
            or original_id
        )
        result = dict(
            record,
            id=sid,
            name=record.get("name") or f"가져온 기록 · {record['label']}",
            source_name=record.get("source_name", filename),
            imported_from=filename,
            imported_at=datetime.now(timezone.utc).isoformat(),
            experiment_id=original_group,
        )
        result.setdefault(
            "collection",
            {"dataset": "가져온 기록", "mode": "live", "hardware": "unknown"},
        )
        staged.append(result)
    for result in staged:
        db.write_json(db.SEGMENTS / f"{result['id']}.json", result)
    return [r["id"] for r in staged]


def export_records(records, path):
    if not records:
        raise ValueError("내보낼 기록에 체크하세요.")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "manifest.json",
            json.dumps(
                {"schema": "wifisensing-v2-records", "count": len(records)},
                ensure_ascii=False,
            ),
        )
        for r in records:
            archive.writestr(
                f"segments/{r['id']}.json", json.dumps(r, ensure_ascii=False)
            )


def clip_record(record, start, end, label):
    if not label.strip() or end <= start:
        raise ValueError("행동 이름과 시작·끝 시간을 확인하세요.")
    frames = [dict(f) for f in record["frames"] if start <= f["t"] <= end]
    if len(frames) < 4:
        raise ValueError("신호 구간이 너무 짧습니다.")
    origin = frames[0]["t"]
    for f in frames:
        f["source_t"] = f["t"]
        f["t"] -= origin
    result = dict(
        record,
        id=uuid.uuid4().hex,
        label=label.strip()[:80],
        frames=frames,
        start=0,
        end=frames[-1]["t"],
        parent_record_id=record["id"],
        name=f"{label.strip()} · 선택 구간",
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    # A crop remains in its parent's group. It is never a new independent trial.
    db.write_json(db.SEGMENTS / f"{result['id']}.json", result)
    return result
