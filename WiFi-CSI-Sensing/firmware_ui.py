from pathlib import Path
import sys
import time
from PySide6 import QtWidgets as W, QtCore as C
import server as db


class FirmwareDialog(W.QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("C6 두 대 준비")
        self.resize(640, 520)
        layout = W.QVBoxLayout(self)
        hint = W.QLabel(
            "보드를 한 대씩 설치하세요. 송신기는 전원만, 수신기는 PC·라즈베리파이에 USB로 연결합니다.\n기본 무선 채널은 양쪽 모두 11입니다. 아직 실제 C6 보드에서 검증하지 않은 개발용 펌웨어입니다."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        from serial.tools import list_ports

        self.port = W.QComboBox()
        for p in list_ports.comports():
            self.port.addItem(f"{p.device} · {p.description}", p.device)
        layout.addWidget(self.port)
        self.role = W.QComboBox()
        self.role.addItem("수신기 · PC/Pi에 연결", "receiver")
        self.role.addItem("송신기 · 전원만 연결", "transmitter")
        layout.addWidget(self.role)
        self.consent = W.QCheckBox(
            "선택한 보드의 기존 펌웨어를 백업한 뒤 교체합니다."
        )
        layout.addWidget(self.consent)
        self.start = W.QPushButton("선택한 C6에 설치")
        self.start.clicked.connect(self.install)
        layout.addWidget(self.start)
        self.log = W.QPlainTextEdit()
        self.log.setReadOnly(True)
        layout.addWidget(self.log)
        self.close_button = W.QPushButton("닫기")
        self.close_button.clicked.connect(self.accept)
        layout.addWidget(self.close_button)
        self.process = None
        self.timer = C.QTimer(self)
        self.timer.timeout.connect(self.refresh)

    def install(self):
        if not self.consent.isChecked() or not self.port.currentData():
            self.log.setPlainText("설치할 보드와 교체 확인란을 선택하세요.")
            return
        self.log_path = db.DATA / f"c6-install-{time.time_ns()}.log"
        args = [
            "--flash-c6",
            self.port.currentData(),
            "--role",
            self.role.currentData(),
            "--backup",
            str(db.DATA / "board-backups"),
            "--flash-log",
            str(self.log_path),
        ]
        if not getattr(sys, "frozen", False):
            args.insert(0, str(Path(__file__).with_name("app.py")))
        self.process = C.QProcess(self)
        self.process.finished.connect(self.finished)
        self.process.errorOccurred.connect(self.process_error)
        for widget in (
            self.start,
            self.close_button,
            self.port,
            self.role,
            self.consent,
        ):
            widget.setEnabled(False)
        self.process.start(sys.executable, args)
        self.timer.start(500)

    def refresh(self):
        if self.log_path.exists():
            self.log.setPlainText(
                self.log_path.read_text(encoding="utf-8", errors="replace")[
                    -9000:
                ]
            )
            self.log.verticalScrollBar().setValue(
                self.log.verticalScrollBar().maximum()
            )

    def process_error(self, error):
        self.log.setPlainText(self.process.errorString())
        if error == C.QProcess.ProcessError.FailedToStart:
            self.finished(-1, None)

    def finished(self, code, status):
        self.refresh()
        self.timer.stop()
        self.log.appendPlainText(
            "\n설치 완료"
            if code == 0
            else "\n설치 실패 · 위 오류를 확인하세요. 임의로 다른 보드용 펌웨어를 쓰지 않습니다."
        )
        for widget in (
            self.start,
            self.close_button,
            self.port,
            self.role,
            self.consent,
        ):
            widget.setEnabled(True)

    def reject(self):
        if (
            self.process
            and self.process.state() != C.QProcess.ProcessState.NotRunning
        ):
            return
        super().reject()

    def closeEvent(self, event):
        if (
            self.process
            and self.process.state() != C.QProcess.ProcessState.NotRunning
        ):
            event.ignore()
        else:
            super().closeEvent(event)
