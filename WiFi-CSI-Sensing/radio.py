"""Explicit physical subcarrier mapping shared by collection, import and inference."""

import numpy as np

# Exclude DC and +/-1; +1 overlaps first_word_invalid on legacy ESP32.
# Use the same 50 physical tones on legacy LLTF and C6 HT20, in frequency order.
CARRIERS = list(range(-26, -1)) + list(range(2, 27))
LAYOUTS = {
    "esp_lltf64": 128,
    "c6_ht20_centered64": 128,
    "c6_ht20_packed57": 114,
}


def infer_legacy_layout(iq):
    """Only for old files with no metadata; refuse ambiguous/nonstandard layouts."""
    a = np.asarray(iq, dtype=float)
    if a.ndim == 1:
        a = a[None, :]
    if a.shape[1] != 128:
        raise ValueError(
            "CSI 배열 형식을 알 수 없습니다. 전용 수집 펌웨어와 형식 정보를 사용하세요."
        )
    zero = np.mean((a[:, ::2] == 0) & (a[:, 1::2] == 0), axis=0)
    middle = float(zero[[28, 29, 30, 31, 33, 34, 35, 36]].mean())
    edges = float(zero[[0, 1, 2, 3, 61, 62, 63]].mean())
    if middle >= 0.8 and middle - edges >= 0.5:
        return "esp_lltf64"
    if edges >= 0.8 and edges - middle >= 0.5:
        return "c6_ht20_centered64"
    raise ValueError(
        "기존 CSI의 채널 배열을 확정할 수 없습니다. 보드 형식이 명시된 새 기록을 수집하세요."
    )


def amplitude(iq, layout, first_word_invalid=False):
    if layout not in LAYOUTS:
        raise ValueError("지원하지 않는 CSI 배열 형식입니다.")
    values = np.asarray(iq, dtype=float)
    if (
        values.ndim != 1
        or len(values) != LAYOUTS[layout]
        or not np.isfinite(values).all()
    ):
        raise ValueError("CSI 배열 길이 또는 값이 올바르지 않습니다.")
    if (
        np.any(abs(values) > 128)
        or np.any(values > 127)
        or np.any(values != np.floor(values))
    ):
        raise ValueError("원본 CSI는 부호 있는 8비트 I/Q 값이어야 합니다.")
    indexes = (
        [k % 64 for k in CARRIERS]
        if layout == "esp_lltf64"
        else [k + (32 if len(values) == 128 else 28) for k in CARRIERS]
    )
    if first_word_invalid and min(indexes) < 2:
        raise ValueError("유효하지 않은 CSI 첫 영역이 선택되었습니다.")
    return np.hypot(values[::2], values[1::2])[indexes]


def upgrade_record(record):
    """Repair old raw records in memory. User files and labels are never rewritten."""
    if record.get("representation") != "raw_iq_52":
        return record
    frames = record.get("frames", [])
    if not frames:
        return record
    if all(
        f.get("carrier_ids") == CARRIERS
        and len(f.get("amp", [])) == len(CARRIERS)
        for f in frames
    ):
        return record
    if any(not isinstance(f.get("iq"), list) for f in frames):
        return dict(
            record,
            processing_error="채널 교정에 필요한 원본 I/Q가 없습니다. 새 기록을 수집하세요.",
        )
    try:
        hw = record.get("collection", {}).get("hardware", "")
        layout = (
            "esp_lltf64"
            if hw in ("router_esp32", "router_c3", "router_s3")
            else infer_legacy_layout([f["iq"] for f in frames[:120]])
        )
        fixed = []
        for f in frames:
            actual = f.get("layout") or layout
            fixed.append(
                dict(
                    f,
                    amp=amplitude(
                        f["iq"], actual, bool(f.get("first_word_invalid"))
                    ).tolist(),
                    layout=actual,
                    carrier_ids=CARRIERS,
                )
            )
        return dict(record, frames=fixed, channel_mapping="physical_50_v1")
    except ValueError as exc:
        return dict(record, processing_error=str(exc))


def board_layout(board):
    if board.get("chip") in ("esp32", "esp32c3", "esp32s3"):
        return "esp_lltf64"
    return None  # C6 packets must declare their own HT20 layout.
