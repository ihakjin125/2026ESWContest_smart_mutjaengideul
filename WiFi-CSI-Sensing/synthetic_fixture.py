"""Deterministic software-test input, not captured RF or an action dataset."""

import csv
import io
import json

import numpy as np


def csi_csv(seconds=30, rate=60):
    """Generate signed I/Q in the explicit legacy LLTF layout."""
    rng = np.random.default_rng(20260914)
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["timestamp", "data", "layout", "rssi"])
    tones = np.arange(64)
    active = (tones <= 27) | (tones >= 37)
    for index in range(round(seconds * rate) + 1):
        t = index / rate
        magnitude = 28 + 6 * np.sin(2 * np.pi * 0.7 * t + tones * 0.17)
        magnitude += 3 * np.cos(2 * np.pi * 2.3 * t + tones * 0.41)
        magnitude += rng.normal(0, 0.5, 64)
        phase = tones * 0.13 + 0.08 * np.sin(t * 2.1 + tones * 0.37)
        iq = np.stack(
            [magnitude * np.sin(phase), magnitude * np.cos(phase)], axis=1
        )
        iq[~active] = 0
        iq = np.clip(np.rint(iq), -128, 127).astype(int).ravel().tolist()
        writer.writerow([t, json.dumps(iq), "esp_lltf64", -45])
    return output.getvalue().encode("utf-8")
