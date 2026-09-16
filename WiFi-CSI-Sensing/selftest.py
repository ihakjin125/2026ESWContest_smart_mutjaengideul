"""Isolated functional checks. Generated test signals are never loaded in the normal UI."""

from collections import deque
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
import uuid
from unittest.mock import patch


def run(application, screenshots=None):
    import app
    import server as db
    import services
    import teaching
    from core import read_signal, inspect_signal
    from data_management import move_records
    from live_timing import LiveClock
    from recognition import Recognition

    checks = []

    def check(condition, name):
        if not condition:
            raise AssertionError(name)
        checks.append(name)

    from c6_selftest import run as check_c6

    check_c6(check)

    check(
        services.hardware_for_chip("esp32") == "router_esp32"
        and services.hardware_for_chip("esp32c3") == "router_c3",
        "ESP32 and C3 are assigned different verified-chip collection profiles",
    )
    check(
        services.baud_for_port(0x1A86) == 921600
        and services.baud_for_port(0x303A) == 115200,
        "CH340 uses high-speed UART and native Espressif USB preserves its line rate",
    )

    def drain(window):
        end = time.perf_counter() + 60
        while (
            window.busy or window.predicting or window.workers
        ) and time.perf_counter() < end:
            application.processEvents()
            time.sleep(0.01)
        application.processEvents()
        check(
            not window.busy and not window.predicting and not window.workers,
            "background operation completed",
        )

    if not app.G.QFontDatabase.families():
        for font in ("malgun.ttf", "malgunbd.ttf"):
            app.G.QFontDatabase.addApplicationFont(
                str(Path(os.environ["WINDIR"]) / "Fonts" / font)
            )
    if screenshots:
        screenshots = Path(screenshots)
        screenshots.mkdir(parents=True, exist_ok=True)

    def shot(window, name):
        if screenshots:
            application.processEvents()
            window.grab().save(str(screenshots / f"{name}.png"))

    original = db.DATA, db.SESSIONS, db.SEGMENTS, db.MODELS, db.LIVE
    check(
        "WifiSensing-data" not in str(db.DATA),
        "V2 uses an independent data directory",
    )
    with tempfile.TemporaryDirectory(prefix="WifiSensing2-QA-") as tmp:
        db.DATA = Path(tmp) / "v2"
        db.SESSIONS, db.SEGMENTS, db.MODELS = [
            db.DATA / n for n in ("sessions", "segments", "models")
        ]
        for folder in (db.SESSIONS, db.SEGMENTS, db.MODELS):
            folder.mkdir(parents=True)
        services.save_settings({"behavior": "호흡"})
        w = app.MainWindow()
        w.timer.stop()
        w.resize(1280, 740)
        w.show()
        application.processEvents()
        check(
            w.pages.count() == 3
            and not w.records
            and not w.selected_ids
            and w.model is None,
            "three screens, empty records, no automatic example or model",
        )
        check(
            not w.inference_button.isEnabled()
            and not w.train_button.isEnabled()
            and not w.delete_selected_button.isEnabled(),
            "unready actions are disabled",
        )
        errors = []
        w.error = errors.append
        for i in range(3):
            w.go(i)
            shot(w, f"empty-{i + 1}")

        check(
            [b.text() for b in w.categories] == ["정지", "낙상"]
            and w.behavior.currentText() == "정지",
            "old presets migrate to two permanent defaults without auto-registering the old selection",
        )
        with patch.object(
            app.W.QMessageBox,
            "exec",
            side_effect=AssertionError(
                "default action deletion dialog must not open"
            ),
        ):
            for default in ("정지", "낙상"):
                w.behavior.setCurrentText(default)
                check(
                    not w.delete_behavior_button.isEnabled()
                    and not w.remove_behavior(),
                    f"permanent action {default} cannot be deleted from UI or handler",
                )
        w.new_behavior.setText("  ")
        w.save_behavior_button.click()
        check(
            not w.custom_behaviors and "이름을 입력" in w.behavior_hint.text(),
            "empty action names cannot be saved",
        )
        for name in ("시험 A", "시험 B"):
            w.new_behavior.setText(name)
            w.save_behavior_button.click()
        check(
            w.custom_behaviors == ["시험 A", "시험 B"]
            and w.behavior.currentText() == "시험 B"
            and services.load_settings()["custom_behaviors"]
            == w.custom_behaviors,
            "Save creates selected action buttons and persists them immediately",
        )
        w.new_behavior.setText("  시험   A  ")
        w.new_behavior.returnPressed.emit()
        check(
            w.custom_behaviors == ["시험 A", "시험 B"]
            and w.behavior.currentText() == "시험 A",
            "Enter selects duplicate normalized names without adding a duplicate button",
        )
        w.new_behavior.setText("저장 실패 시험")
        with patch.object(
            services,
            "save_settings",
            side_effect=OSError("QA read-only settings"),
        ):
            w.save_behavior_button.click()
        check(
            errors
            and w.custom_behaviors == ["시험 A", "시험 B"]
            and w.behavior.currentText() == "시험 A"
            and w.new_behavior.text() == "저장 실패 시험",
            "settings write failure restores prior buttons and selection while retaining typed input",
        )
        errors.clear()
        for name in (
            "호흡",
            "걷기",
            "앉기",
            "일어서기",
            "뒤척임",
            "누워 있기",
            "가" * 80,
        ):
            w.new_behavior.setText(name)
            w.save_behavior_button.click()
        w.go(0)
        application.processEvents()
        check(
            w.category_scroll.height() <= 92
            and w.category_scroll.verticalScrollBar().maximum() > 0
            and w.category_scroll.verticalScrollBar().value() > 0
            and w.width() == 1280
            and w.categories[-1].toolTip() == "가" * 80,
            "many saved actions and an 80-character name fit a scrollable category area",
        )
        shot(w, "custom-actions-many")
        w.set_busy(True)
        w.new_behavior.setText("수집 중 변경")
        check(
            not w.add_behavior()
            and "수집 중 변경" not in w.custom_behaviors
            and not w.save_behavior_button.isEnabled(),
            "action editing is blocked during collection or training",
        )
        check(
            not w.delete_behavior_button.isEnabled()
            and not w.remove_behavior(),
            "action deletion cannot change categories while collection or training is busy",
        )
        w.new_behavior.clear()
        w.set_busy(False)

        from synthetic_fixture import csi_csv

        frames, kind, quality = read_signal(csi_csv(), "synthetic-csi.csv")
        check(
            kind == "raw_iq_52" and len(frames[0]["iq"]) >= 128,
            "synthetic CSI parser preserves signed I/Q",
        )
        records = []
        for i in range(6):
            # Generated signals exercise software only; this is not an accuracy experiment.
            chunk = [
                dict(f)
                for f in frames
                if (i % 4) * 5 <= f["t"] <= (i % 4) * 5 + 4.1
            ]
            origin = chunk[0]["t"]
            chunk = [dict(f, t=f["t"] - origin) for f in chunk]
            record = dict(
                id=uuid.uuid4().hex,
                frames=chunk,
                representation=kind,
                label="시험 A" if i % 2 == 0 else "시험 B",
                experiment_id=f"test-round-{i // 2}",
                source_id=uuid.uuid4().hex,
                name="합성 CSI로 검사한 기능 시험용 기록",
                created_at=f"2026-01-01T00:00:{i:02d}+00:00",
                collection=dict(
                    dataset="QA only", mode="live", hardware="router_s3"
                ),
            )
            db.write_json(db.SEGMENTS / f"{record['id']}.json", record)
            records.append(record)
        check(
            services.selection_state(records, 2)[0],
            "independent rounds and two classes are ready",
        )
        invalid = dict(
            records[0],
            id=uuid.uuid4().hex,
            label="선택하지 않은 기록",
            frames=[dict(f, t=f["t"] * 20) for f in records[0]["frames"]],
        )
        db.write_json(db.SEGMENTS / f"{invalid['id']}.json", invalid)
        check(
            not services.selection_state(records + [invalid], 2)[0],
            "transport failure blocks selected records",
        )
        check(
            not services.selection_state(records[:2], 2)[0],
            "one round cannot masquerade as independent evaluation",
        )
        mixed = dict(
            records[0], collection=dict(mode="live", hardware="router_c3")
        )
        check(
            not services.selection_state(records + [mixed], 2)[0],
            "mixed boards cannot enter one model",
        )
        check(
            not services.selection_state(records, 8)[0],
            "window longer than records is rejected",
        )

        # Import copies only explicit JSON/ZIP records, retaining identity/groups.
        import_source = Path(tmp) / "v1-source.json"
        db.write_json(import_source, records[0])
        before = hashlib.sha256(import_source.read_bytes()).hexdigest()
        imported = services.import_records([import_source])
        check(
            len(imported) == 1
            and services.import_records([import_source]) == [],
            "import is idempotent",
        )
        check(
            hashlib.sha256(import_source.read_bytes()).hexdigest() == before,
            "import never changes original file",
        )
        copied = json.loads(
            (db.SEGMENTS / f"{imported[0]}.json").read_text(encoding="utf-8")
        )
        check(
            copied["experiment_id"] == records[0]["experiment_id"],
            "import keeps evaluation group",
        )
        archive = Path(tmp) / "selected.zip"
        services.export_records([records[0]], archive)
        check(
            services.import_records([archive]) == [],
            "ZIP imports preserve the same identity",
        )
        move_records(imported)
        check(
            services.import_records([import_source]) == [],
            "reimport cannot silently revive deleted records",
        )
        move_records(imported, restore=True)
        check(
            (db.SEGMENTS / f"{imported[0]}.json").exists(),
            "deleted records can be restored",
        )
        move_records(imported)

        # Exercise actual checkbox signals and asynchronous training used by UI.
        w.reload_records()
        for row, record in enumerate(w.records):
            if record["id"] in {r["id"] for r in records}:
                w.table.item(row, 0).setCheckState(app.C.Qt.CheckState.Checked)
        w.filter.setCurrentIndex(w.filter.findData("시험 A"))
        check(
            "필터 밖" in w.selection_summary.text(),
            "hidden selected records remain explicitly visible in summary",
        )
        check(
            w.train_button.isEnabled() and len(w.selected_records()) == 6,
            "only six explicitly checked records are selected",
        )
        w.model_name.setText("기능 검증용 모델")
        w.train_button.click()
        drain(w)
        check(
            not errors and w.model is not None and w.model_matches(),
            "UI train button creates a matching model",
        )
        record_bytes = {
            p.name: p.read_bytes() for p in db.SEGMENTS.glob("*.json")
        }
        w.new_behavior.setText("손 흔들기")
        w.save_behavior_button.click()
        check(
            w.model_matches()
            and {p.name: p.read_bytes() for p in db.SEGMENTS.glob("*.json")}
            == record_bytes,
            "adding an action preserves every existing record and the explicitly selected model",
        )
        w.go(0)
        w.behavior.setCurrentText("시험 A")
        check(
            w.delete_behavior_button.isEnabled(),
            "a selected custom action enables its delete button",
        )
        selected_before = set(w.selected_ids)
        model_bytes = {
            p.name: p.read_bytes() for p in db.MODELS.iterdir() if p.is_file()
        }
        settings_before = services.settings_path().read_bytes()

        def answer_action_delete(approve):
            def answer():
                modal = application.activeModalWidget()
                check(
                    isinstance(modal, app.W.QMessageBox)
                    and "시험 A" in modal.text()
                    and "기록과 학습 모델은 그대로 유지"
                    in modal.informativeText(),
                    "action deletion identifies the selected category and promises record/model preservation",
                )
                shot(modal, "action-delete-confirmation")
                role = (
                    app.W.QMessageBox.ButtonRole.AcceptRole
                    if approve
                    else app.W.QMessageBox.ButtonRole.RejectRole
                )
                next(
                    b for b in modal.buttons() if modal.buttonRole(b) == role
                ).click()

            app.C.QTimer.singleShot(0, answer)
            w.delete_behavior_button.click()

        answer_action_delete(False)
        check(
            "시험 A" in w.custom_behaviors
            and w.behavior.currentText() == "시험 A"
            and services.settings_path().read_bytes() == settings_before,
            "cancelling action deletion preserves the list, current action and saved settings",
        )
        with patch.object(
            services,
            "save_settings",
            side_effect=OSError("QA locked settings"),
        ):
            answer_action_delete(True)
        check(
            errors
            and "시험 A" in w.custom_behaviors
            and w.behavior.currentText() == "시험 A"
            and w.delete_behavior_button.isEnabled()
            and services.settings_path().read_bytes() == settings_before,
            "failed deletion persistence rolls back category buttons and selection",
        )
        errors.clear()
        w.new_behavior.setText("시험 A")
        answer_action_delete(True)
        check(
            "시험 A" not in w.custom_behaviors
            and "시험 A" not in services.load_settings()["custom_behaviors"]
            and w.behavior.currentText() == "정지"
            and not w.new_behavior.text()
            and not w.delete_behavior_button.isEnabled(),
            "confirmed deletion removes the chosen category persistently and selects a remaining default",
        )
        check(
            w.model_matches()
            and w.selected_ids == selected_before
            and {p.name: p.read_bytes() for p in db.SEGMENTS.glob("*.json")}
            == record_bytes
            and {
                p.name: p.read_bytes()
                for p in db.MODELS.iterdir()
                if p.is_file()
            }
            == model_bytes,
            "deleting a trained category preserves every record, model and training selection byte for byte",
        )
        shot(w, "after-action-delete")
        model = dict(w.model)
        check(
            set(model["segment_ids"]) == {r["id"] for r in records}
            and invalid["id"] not in model["segment_ids"],
            "unchecked record excluded from training and evaluation",
        )
        check(
            set(model["train_groups"]).isdisjoint(model["test_groups"]),
            "held-out evaluation has no shared measurement rounds",
        )
        check(
            model["record_count"] == 6
            and model["schema"] == "wifisensing-v2-model",
            "model records exact selection and V2 schema",
        )
        check(
            model["representation"] == "raw_iq_52",
            "original CSI records remain the reusable stored source",
        )
        from pipeline_selftest import run as check_pipeline

        check_pipeline(check, records, model)
        prediction = teaching.predict_frames(model, records[0]["frames"], kind)
        check(
            set(prediction["scores"]) == {"시험 A", "시험 B"}
            and abs(sum(prediction["scores"].values()) - 1) < 1e-6,
            "saved model predicts class scores on an input window",
        )
        w.filter.setCurrentIndex(0)
        w.go(1)
        shot(w, "selected-trained")

        def inspect_evaluation(dialog):
            table = dialog.findChild(app.W.QTableWidget)
            check(
                table.columnCount() == len(model["labels"]) + 1,
                "evaluation shows a separate per-action recall column",
            )
            for i, row in enumerate(model["confusion_matrix"]):
                check(
                    f"{row[i]} / {sum(row)}"
                    in table.item(i, len(model["labels"])).text(),
                    f"evaluation action {i} exposes correct and total held-out window counts",
                )
            dialog.show()
            shot(dialog, "evaluation-details")
            dialog.close()
            return 0

        with patch.object(app.W.QDialog, "exec", inspect_evaluation):
            w.evaluation_button.click()

        # Generated signals on a controllable clock test software behavior.
        # These samples do not represent a physical action experiment.
        class InputClock:
            def __init__(self):
                self.now = 5.0
                self.sid = "qa-port"
                self.frames = deque(
                    [
                        dict(f, t=5 - 4.1 + f["t"], stream_epoch=0)
                        for f in records[0]["frames"]
                    ]
                )
                self.connected = True

            def elapsed(self):
                return self.now

            def status(self):
                return dict(
                    connected=self.connected,
                    id=self.sid,
                    port="QA INPUT",
                    synchronizing=False,
                )

            def board_status(self):
                return dict(chip="esp32s3")

            def disconnect(self):
                self.connected = False

            def snapshot(self):
                return dict(
                    id=self.sid, frames=list(self.frames), representation=kind
                )

        input_clock = InputClock()
        db.LIVE = input_clock
        w.new_behavior.setText("시험 수집")
        w.start_capture()
        check(
            w.job is not None
            and w.job.label == "시험 수집"
            and "시험 수집" in services.load_settings()["custom_behaviors"],
            "collecting a newly typed action saves and uses its label instead of the prior selection",
        )
        w.cancel_capture()
        w.go(2)
        w.inference_button.click()
        check(
            w.recognition.running and w.recognition.result is None,
            "recognition starts by clearing old results",
        )
        w.advance_recognition(list(input_clock.frames))
        check(
            w.recognition.result is None and not w.predicting,
            "buffer from before Start cannot be recognized",
        )
        input_clock.now = 9.2
        input_clock.frames = deque(
            dict(f, t=5.1 + f["t"], stream_epoch=0)
            for f in records[0]["frames"]
        )
        w.advance_recognition(list(input_clock.frames))
        drain(w)
        check(
            w.recognition.result is not None
            and w.current_action.text() == w.recognition.result["label"],
            "fresh input after Start produces a visible action through the saved model",
        )
        check(
            list(w.live_line.getData()[1])
            == w.recognition.result["input_signal"]["signal"],
            "recognition graph displays the exact final signal used for the accepted prediction",
        )
        w.update_preview(list(input_clock.frames))
        drain(w)
        check(
            w.capture_line.getData()[1] is not None,
            "default collection preview displays final processed input",
        )
        from live_preview_selftest import run as check_live_preview

        check_live_preview(check, w, input_clock, drain, shot)
        shot(w, "recognizing-qa-input")
        input_clock.now += 2
        w.advance_recognition([])
        check(
            w.recognition.result is None
            and all(bar.value() == 0 for bar in w.score_bars.values()),
            "stale input removes action and every score bar",
        )
        w.stop_recognition()
        check(
            w.current_action.text() == "인식 대기"
            and w.recognition.result is None,
            "Stop clears the current action",
        )
        input_clock.connected = False
        w.tick()
        check(
            w.capture_line.getData()[0] is None,
            "disconnected graph clears instead of replaying a sample",
        )

        # Delayed background replies cannot restore old predictions.
        state = Recognition()
        state.begin("s", 0, "m", 10)
        ticket = state.generation
        check(
            state.accept(ticket, "m", prediction, 12, 12.1),
            "current prediction accepted",
        )
        state.stop()
        check(
            not state.accept(ticket, "m", prediction, 12, 12.2),
            "late reply rejected after Stop",
        )
        state.begin("s", 0, "m", 13)
        ticket = state.generation
        state.observe(True, "s", 1, 13.1, 13.2)
        check(
            not state.accept(ticket, "m", prediction, 13.1, 13.2),
            "late reply rejected after clock resynchronization",
        )
        state.begin("s", 1, "new", 14)
        check(
            not state.accept(state.generation, "m", prediction, 14, 14.1),
            "reply for another model rejected",
        )
        state.observe(False, "s", 1, 14.1, 14.2)
        check(
            not state.running and state.result is None,
            "disconnect stops and clears recognition",
        )

        # Capture and save use complete real I/Q frames, independent of GUI clock.
        source = dict(id="qa-capture-source", representation=kind)
        context = dict(
            mode="live",
            hardware="router_s3",
            dataset="QA",
            round_id="qa-round",
            note="test only",
        )
        job = teaching.TimedCapture(
            source, w.behavior.currentText(), 2, 1, 0, context
        )
        stream = [dict(f, t=1 + f["t"]) for f in records[0]["frames"]]
        check(
            job.update(0.5, stream) == "preparing" and not job.frames,
            "preparation does not record",
        )
        check(
            job.update(3, stream) == "complete",
            "timed capture completes at configured duration",
        )
        saved = teaching.save_capture(job)
        check(
            saved["label"] == "시험 수집",
            "saved CSI record retains the user-created action label",
        )
        check(
            saved["frames"][0]["iq"] == stream[0]["iq"]
            and saved["experiment_id"] == "qa-round",
            "capture preserves raw I/Q and measurement round",
        )
        cancelled = teaching.TimedCapture(
            source, "시험 취소", 2, 0, 0, context
        )
        cancelled.cancel()
        check(
            cancelled.update(2, stream) == "cancelled",
            "cancelled capture does not resume",
        )

        w.reload_records()
        check(
            w.model_matches() and saved["id"] not in w.selected_ids,
            "new capture is unselected and does not invalidate existing model",
        )

        # Batch deletion exercises the real button and modal, only in this temp store.
        checked = set(w.selected_ids)
        before_delete = {
            p.name: p.read_bytes() for p in db.SEGMENTS.glob("*.json")
        }
        w.filter.setCurrentIndex(w.filter.findData("시험 A"))

        def answer_delete(approve):
            def answer():
                modal = application.activeModalWidget()
                check(
                    isinstance(modal, app.W.QMessageBox),
                    "bulk deletion presents its exact scope before moving files",
                )
                check(
                    "필터 밖의 체크한 기록 3개" in modal.informativeText()
                    and "6개" in modal.text(),
                    "bulk confirmation includes checked records hidden by the current filter",
                )
                shot(modal, "bulk-delete-confirmation")
                role = (
                    app.W.QMessageBox.ButtonRole.AcceptRole
                    if approve
                    else app.W.QMessageBox.ButtonRole.RejectRole
                )
                next(
                    b for b in modal.buttons() if modal.buttonRole(b) == role
                ).click()

            app.C.QTimer.singleShot(0, answer)
            w.delete_selected_button.click()

        w.set_busy(True)
        w.delete_selected()
        check(
            not w.delete_selected_button.isEnabled()
            and w.selected_ids == checked,
            "capture/training busy state blocks bulk deletion",
        )
        w.set_busy(False)
        answer_delete(False)
        check(
            w.selected_ids == checked
            and {p.name: p.read_bytes() for p in db.SEGMENTS.glob("*.json")}
            == before_delete,
            "cancelling bulk deletion preserves all files and training selection",
        )
        with patch.object(
            app, "move_records", side_effect=OSError("QA locked file")
        ):
            answer_delete(True)
        check(
            errors
            and w.selected_ids == checked
            and w.model_matches()
            and {p.name: p.read_bytes() for p in db.SEGMENTS.glob("*.json")}
            == before_delete,
            "failed deletion reports the error and preserves the selection and model",
        )
        errors.clear()

        original_rename = Path.rename
        failed_id = sorted(checked)[1]

        def fail_second_move(path, destination):
            if path == db.SEGMENTS / f"{failed_id}.json":
                raise OSError("QA second file locked")
            return original_rename(path, destination)

        with patch.object(Path, "rename", fail_second_move):
            try:
                move_records(sorted(checked))
            except OSError:
                pass
            else:
                raise AssertionError("expected batch move failure")
        check(
            {p.name: p.read_bytes() for p in db.SEGMENTS.glob("*.json")}
            == before_delete,
            "mid-batch move failure rolls back previously moved records",
        )

        answer_delete(True)
        check(
            not w.selected_ids
            and not w.delete_selected_button.isEnabled()
            and all(
                not (db.SEGMENTS / f"{sid}.json").exists() for sid in checked
            ),
            "one bulk action removes every checked record including hidden ones",
        )
        check(
            {p.name: p.read_bytes() for p in db.SEGMENTS.glob("*.json")}
            == {
                name: blob
                for name, blob in before_delete.items()
                if Path(name).stem not in checked
            },
            "bulk deletion preserves every unchecked record byte for byte",
        )
        check(
            not w.model_matches()
            and not w.score_bars
            and w.recognition.result is None,
            "bulk deletion invalidates the selection model and clears prediction scores",
        )
        shot(w, "after-bulk-delete")
        move_records(checked, restore=True)
        w.selected_ids = checked
        w.reload_records()
        check(
            w.model_matches()
            and {p.name: p.read_bytes() for p in db.SEGMENTS.glob("*.json")}
            == before_delete,
            "all deleted records restore together without changing data or model identity",
        )
        w.filter.setCurrentIndex(0)
        w.window.setCurrentIndex(1)
        check(
            not w.model_matches() and not w.inference_button.isEnabled(),
            "changed judgment window disables old model",
        )
        w.window.setCurrentIndex(0)
        w.clear_selection()
        check(
            not w.model_matches() and not w.score_bars,
            "changed selection clears model scores and blocks inference",
        )
        w.selected_ids = {r["id"] for r in records}
        w.reload_records()
        w.save_settings()
        w.close()

        second = app.MainWindow()
        second.timer.stop()
        check(
            second.custom_behaviors == w.custom_behaviors
            and second.behavior.currentText() == "시험 수집"
            and [b.text() for b in second.categories]
            == ["정지", "낙상", *w.custom_behaviors],
            "restart restores all custom action buttons, both defaults and the chosen action",
        )
        check(
            second.model_matches()
            and second.selected_ids == {r["id"] for r in records},
            "restart restores exact selection and trained model without starting inference",
        )
        check(
            not second.recognition.running
            and second.recognition.result is None,
            "restart never restores a live prediction",
        )
        check(
            "시험 A" not in [b.text() for b in second.categories]
            and second.model_matches(),
            "a deleted category remains absent after restart while its trained model still works",
        )
        second.new_behavior.setText("시험 A")
        second.save_behavior_button.click()
        check(
            second.custom_behaviors.count("시험 A") == 1
            and second.model_matches()
            and len([r for r in second.records if r["label"] == "시험 A"])
            == 3,
            "a deleted action can be re-added once without duplicating or relabeling existing records",
        )
        dialog = app.RecordDialog(second, records[0])
        for toggle in dialog.stages.values():
            toggle.setChecked(False)
        check(
            list(dialog.record_line.getData()[1])
            == [f["amp"][0] for f in records[0]["frames"]],
            "record stage switches reveal original amplitudes when all are off",
        )
        for toggle in dialog.stages.values():
            toggle.setChecked(True)
        check(
            dialog.record_line.getData()[1] is not None,
            "record stage switches restore the final training waveform",
        )
        shot(dialog, "record-stage-controls")
        dialog.region.setRegion((0.2, 2.6))
        dialog.label.setText("시험 A")
        dialog.save_clip()
        check(
            records[0]["id"] not in second.selected_ids
            and len(second.selected_ids) == 6,
            "crop replaces parent in checked selection",
        )
        new_id = next(iter(second.selected_ids - {r["id"] for r in records}))
        clipped = next(r for r in second.records if r["id"] == new_id)
        check(
            clipped["experiment_id"] == records[0]["experiment_id"]
            and clipped["frames"][0]["t"] == 0,
            "crop preserves evaluation group and resets relative time",
        )
        check(
            not second.model_matches(),
            "crop invalidates an existing selection model",
        )
        app.RecordDialog(second, clipped).delete()
        check(
            new_id not in second.selected_ids
            and not (db.SEGMENTS / f"{new_id}.json").exists(),
            "record deletion immediately removes it from training selection",
        )
        second.close()

        viewed = inspect_signal(records[0]["frames"], kind)
        check(
            len(viewed["processed"]) > 0 and len(viewed["heatmap"][0]) == 50,
            "50-channel and preprocessing inspection works",
        )
        clock = LiveClock()
        check(
            all(
                clock.map_time(i * 0.02, i * 0.001) is None for i in range(100)
            ),
            "serial backlog is not exposed as live data",
        )
        values = [
            clock.map_time(20 + i * 0.02, 3 + i * 0.02) for i in range(150)
        ]
        check(
            values[-1] is not None and clock.ready,
            "paced device stream becomes live after synchronization",
        )
        db.DATA, db.SESSIONS, db.SEGMENTS, db.MODELS, db.LIVE = original
        db.CACHE.clear()

    return dict(
        status="PASS",
        checks=checks,
        check_count=len(checks),
        fixture="Deterministic synthetic CSI and artificial labels; software checks only",
        live_hardware_test=False,
        user_data_read_or_modified=False,
    )
