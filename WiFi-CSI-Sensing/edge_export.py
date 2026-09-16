from pathlib import Path
import io
import json
import zipfile
import numpy as np


def export_bundle(metadata, path):
    import joblib
    import server as db
    from signal_processing import PROFILE

    if metadata.get("feature_profile") != PROFILE:
        raise ValueError("현재 방식으로 다시 학습하세요.")
    mid = metadata["model_id"]
    if len(mid) != 32 or any(c not in "0123456789abcdef" for c in mid):
        raise ValueError("모델 ID 오류")
    model = joblib.load(db.MODELS / f"{mid}.joblib")["model"]
    memory = io.BytesIO()
    np.savez_compressed(memory, **model.weights, input_scale=model.scale)
    root = Path(__file__).parent
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        clean = {
            k: v
            for k, v in metadata.items()
            if k not in ("model_path", "training_records", "fingerprint")
        }
        clean["labels"] = list(map(str, model.classes_))
        archive.writestr(
            "model/model.json", json.dumps(clean, ensure_ascii=False, indent=2)
        )
        archive.writestr("model/weights.npz", memory.getvalue())
        for name in (
            "edge_runtime.py",
            "core.py",
            "radio.py",
            "live_timing.py",
            "signal_pipeline.py",
            "cnn_runtime.py",
            "signal_processing/__init__.py",
            "PI-사용방법.md",
            "LICENSE",
            "NOTICE.md",
            "THIRD_PARTY_NOTICES.txt",
            "LICENSE-C6.txt",
            "firmware/ESP-IDF-LICENSE.txt",
        ):
            archive.writestr(name, (root / name).read_bytes())
        archive.writestr(
            "requirements.txt",
            "numpy>=2.0,<3\nscipy>=1.14,<2\nscikit-learn>=1.5,<2\nPyWavelets>=1.6,<2\npyserial==3.5\n",
        )
