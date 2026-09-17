"""Live stage switching, including stale workers and unchanged training inputs."""

from itertools import product
from unittest.mock import patch
import numpy as np


def run(check, window, clock, drain, shot):
    import server as db
    from signal_pipeline import latest_signal

    w = window
    saved_files = {
        str(p): p.read_bytes()
        for folder in (db.SEGMENTS, db.MODELS)
        for p in folder.iterdir()
        if p.is_file()
    }
    settings = (db.DATA / "workspace.json").read_bytes()
    selection = set(w.selected_ids)
    frames = list(clock.frames)
    seconds = w.window.currentData()
    w.go(0)
    check(
        all(c.isChecked() for c in w.capture_stages.values())
        and w.channel.currentData() is None,
        "live collection exposes all three enabled stages and the 50-channel PCA view",
    )
    w.axis_lock.setChecked(True)
    for flags in product((False, True), repeat=3):
        for control, enabled in zip(w.capture_stages.values(), flags):
            control.setChecked(enabled)
        drain(w)
        values = w.capture_line.getData()[1]
        if any(flags):
            expected = latest_signal(
                frames, "raw_iq_52", seconds, w.preview_options()
            )["signal"]
        else:
            expected = [
                f["amp"][w.preview_subcarrier]
                for f in frames
                if frames[-1]["t"] - f["t"] <= seconds
            ]
        check(
            np.array_equal(values, expected),
            f"live buttons immediately display correct stages {flags}",
        )
        if flags[1]:
            matrix = np.asarray(
                latest_signal(
                    frames, "raw_iq_52", seconds, w.preview_options()
                )["components"]
            )
            check(
                all(
                    np.array_equal(line.getData()[1], matrix[:, i])
                    for i, line in enumerate(w.capture_aux_lines, 1)
                ),
                f"PC2 and PC3 are also live and identical to model components {flags}",
            )
        else:
            check(
                all(line.getData()[1] is None for line in w.capture_aux_lines),
                f"auxiliary curves cleared when PCA is off {flags}",
            )
        low, high = w.capture_plot.getViewBox().viewRange()[1]
        check(
            low <= min(values) <= max(values) <= high,
            f"stage change fits new units even with a locked vertical axis {flags}",
        )
        check(
            (w.channel.currentData() is None) == flags[1],
            "PCA checkbox and channel choice agree",
        )

    # Explicit channel selection disables PCA, retaining the other stages.
    w.channel.setCurrentIndex(w.channel.findData(12))
    drain(w)
    check(
        not w.capture_stages["pca"].isChecked()
        and w.preview_subcarrier == 12
        and w.capture_stages["denoise"].isChecked()
        and w.capture_stages["lowpass"].isChecked(),
        "choosing an individual live channel disables only PCA",
    )
    for c in w.capture_stages.values():
        c.setChecked(False)
    drain(w)
    check(
        np.array_equal(
            w.capture_line.getData()[1],
            [
                f["amp"][12]
                for f in frames
                if frames[-1]["t"] - f["t"] <= seconds
            ],
        ),
        "all-off live preview shows the selected subcarrier original samples",
    )
    shot(w, "live-stages-all-off")
    w.channel.setCurrentIndex(0)
    drain(w)
    check(
        w.capture_stages["pca"].isChecked(),
        "choosing the representative waveform enables PCA",
    )

    # Capture the deferred callbacks, not an actual sleep, to force the race.
    for c in w.capture_stages.values():
        c.setChecked(True)
    drain(w)
    pending = []
    with patch.object(
        w,
        "background",
        side_effect=lambda fn, done, fail: pending.append((fn, done, fail)),
    ):
        w.update_preview(frames)
        w.capture_stages["lowpass"].setChecked(False)
        w.capture_stages["pca"].setChecked(False)
        old_job = pending.pop(0)
        old_job[1](old_job[0]())
        check(
            len(pending) == 1 and w.capture_line.getData()[1] is None,
            "late old-stage result stays hidden and immediately schedules the latest controls",
        )
        new_job = pending.pop(0)
        new_job[1](new_job[0]())
        check(
            np.array_equal(
                w.capture_line.getData()[1],
                latest_signal(
                    frames, "raw_iq_52", seconds, w.preview_options()
                )["signal"],
            ),
            "rapid live toggles settle on the newest options without another full-window wait",
        )

        # A disconnect while the calculation runs must never restore a wave.
        w.update_preview(frames)
        old_job = pending.pop(0)
        clock.connected = False
        w.update_preview([])
        old_job[1](old_job[0]())
        check(
            w.capture_line.getData()[1] is None and not pending,
            "disconnected live preview rejects a delayed stage result",
        )
        clock.connected = True

    for c in w.capture_stages.values():
        c.setChecked(True)
    drain(w)
    before = w.capture_line.getData()[1].copy()
    clock.now += 0.2
    clock.frames = type(clock.frames)(
        dict(
            f, t=f["t"] + 0.2, amp=[v * 1.01 + (i % 9) * 0.3 for v in f["amp"]]
        )
        for i, f in enumerate(frames)
    )
    w.update_preview(list(clock.frames))
    drain(w)
    check(
        not np.array_equal(before, w.capture_line.getData()[1]),
        "enabled stages continue updating as fresh input changes",
    )
    shot(w, "live-stages-all-on")
    check(
        w.model_matches()
        and w.selected_ids == selection
        and (db.DATA / "workspace.json").read_bytes() == settings
        and all(
            __import__("pathlib").Path(p).read_bytes() == data
            for p, data in saved_files.items()
        ),
        "live stage toggles preserve saved records, model, training selection and settings",
    )
    clock.now -= 0.2
    clock.frames = type(clock.frames)(frames)
    w.axis_lock.setChecked(False)
    w.go(2)
