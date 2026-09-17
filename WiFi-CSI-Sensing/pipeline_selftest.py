"""End-to-end checks for plotted, stored, trained and portable model inputs."""

from pathlib import Path
from unittest.mock import patch
import tempfile
import zipfile
import numpy as np


def run(check, records, metadata):
    import server as db
    import teaching
    from core import inspect_signal, parse_csi_line
    from signal_pipeline import signal_windows
    from signal_processing import preprocess, preprocess_stages, PROFILE
    from optimized_classifier import WaveformClassifier
    from radio import amplitude, CARRIERS, LAYOUTS, infer_legacy_layout
    import json

    reference = np.arange(1, 51, dtype=float)
    for layout, length in LAYOUTS.items():
        iq = np.zeros(length, dtype=int)
        indexes = (
            [k % 64 for k in CARRIERS]
            if layout == "esp_lltf64"
            else [k + (32 if length == 128 else 28) for k in CARRIERS]
        )
        iq[np.asarray(indexes) * 2] = reference
        check(
            np.array_equal(amplitude(iq, layout, True), reference),
            f"{layout}: identical physical tones and invalid first word excluded",
        )
        frame = parse_csi_line(
            json.dumps(dict(timestamp=1, layout=layout, data=iq.tolist()))
        )
        check(
            frame is not None and frame["carrier_ids"] == CARRIERS,
            f"{layout}: packet protocol accepted",
        )
    try:
        infer_legacy_layout(np.ones(128))
    except ValueError:
        check(True, "ambiguous old radio layout rejected")
    else:
        raise AssertionError("ambiguous layout")
    raw = np.asarray([f["amp"] for f in records[0]["frames"]])[:120]
    check(
        np.array_equal(
            preprocess_stages(raw, False, False, False),
            raw[:, 0].astype(np.float32),
        ),
        "all stages off gives raw amplitude",
    )
    check(
        preprocess(raw).shape == (120, 3),
        "all three processed components preserved",
    )
    check(
        np.isfinite(preprocess(np.ones((120, 50)))).all(),
        "constant input remains finite",
    )
    try:
        preprocess(np.zeros((120, 50)))
    except ValueError:
        check(True, "zero power rejected")
    else:
        raise AssertionError("zero power must be rejected")
    # Filter transfer check is a signal test, not an action-accuracy measurement.
    t = np.arange(960) / 60
    wave = np.tile(
        (
            20
            + np.sin(2 * np.pi * 0.25 * t)
            + np.sin(2 * np.pi * 5 * t)
            + np.sin(2 * np.pi * 20 * t)
        )[:, None],
        (1, 50),
    )
    filtered = preprocess_stages(wave, False, False, True)

    def energy(x, hz):
        return abs(
            np.vdot(
                x[120:-120] - x[120:-120].mean(),
                np.exp(2j * np.pi * hz * t[120:-120]),
            )
        )

    check(
        energy(filtered, 0.25) / energy(wave[:, 0], 0.25) > 0.9
        and energy(filtered, 5) / energy(wave[:, 0], 5) > 0.85
        and energy(filtered, 20) / energy(wave[:, 0], 20) < 0.02,
        "8 Hz filter retains .25/5 Hz and attenuates 20 Hz",
    )
    check(
        metadata["model"] == "CSI_CNN3_v2"
        and metadata["feature_profile"] == PROFILE
        and metadata["input_channels"] == 3,
        "CNN consumes three final waveforms",
    )
    with np.load(
        db.MODELS / metadata["processed_signals_file"], allow_pickle=False
    ) as data:
        for r in records:
            indexes = np.flatnonzero(data["record_ids"] == r["id"])
            expected = np.asarray(
                [
                    np.asarray(w["components"]).T
                    for w in signal_windows(
                        r["frames"], r["representation"], 2
                    )
                ],
                dtype=np.float32,
            )
            check(
                np.array_equal(data["signals"][indexes], expected),
                f"audit inputs equal plotted components: {r['label']} / {r['experiment_id']}",
            )
        check(
            set(data["split"]) == {"train", "validation", "test"},
            "three independent data partitions stored",
        )
        partitions = [
            set(data["groups"][data["split"] == s])
            for s in ("train", "validation", "test")
        ]
        check(
            all(
                not partitions[i] & partitions[j]
                for i in range(3)
                for j in range(i)
            ),
            "no measurement group shared among train, validation or test",
        )
    frames = records[0]["frames"]
    plotted = inspect_signal(frames, "raw_iq_52", {"seconds": 2})
    original = WaveformClassifier.predict_proba
    captured = []

    def capture(model, x):
        captured.append(np.asarray(x).copy())
        return original(model, x)

    with patch.object(WaveformClassifier, "predict_proba", capture):
        prediction = teaching.predict_frames(metadata, frames, "raw_iq_52")
    check(
        np.array_equal(captured[0][0], np.asarray(plotted["components"]).T),
        "live inference gets exactly all plotted component values",
    )
    check(
        abs(sum(prediction["scores"].values()) - 1) < 1e-6,
        "saved model scores sum to one",
    )
    check(
        metadata["portable_max_error"] < 2e-4,
        "NumPy logits agree with PyTorch selected checkpoint",
    )
    from edge_export import export_bundle
    from edge_runtime import load_bundle, infer

    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "pi.zip"
        export_bundle(metadata, path)
        with zipfile.ZipFile(path) as z:
            z.extractall(Path(temp) / "pi")
        edge = infer(frames, load_bundle(Path(temp) / "pi/model"))
        check(
            all(
                abs(edge["scores"][k] - v) < 1e-6
                for k, v in prediction["scores"].items()
            ),
            "exported Pi model exactly agrees with desktop inference",
        )
    try:
        teaching.predict_frames(
            dict(metadata, feature_profile="old"), frames, "raw_iq_52"
        )
    except ValueError:
        check(True, "incompatible old model blocked")
    else:
        raise AssertionError("old model accepted")
    broken = [dict(f) for f in frames if not 0.6 < f["t"] < 0.9]
    check(
        len(signal_windows(broken, "raw_iq_52", 2))
        < len(signal_windows(frames, "raw_iq_52", 2)),
        "gap windows excluded instead of interpolated into training",
    )
