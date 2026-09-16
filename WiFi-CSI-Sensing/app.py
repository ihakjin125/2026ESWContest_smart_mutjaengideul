"""WifiSensing 2.0 — collect, choose records, recognize. Native desktop only."""

import argparse
from collections import Counter
from datetime import datetime
import json
import multiprocessing
from pathlib import Path
import sys
import time
import uuid

import numpy as np
from PySide6 import QtCore as C, QtGui as G, QtWidgets as W
import pyqtgraph as pg

import server as db
import teaching
import services
from core import SUBCARRIERS, inspect_signal, signal_quality
from data_management import move_records, trashed_records
from recognition import Recognition
from signal_pipeline import latest_signal, signal_windows
from signal_processing import PROFILE

STYLE = """
QWidget { font-family:'Malgun Gothic'; font-size:13px; color:#192d40; }
QMainWindow, QDialog { background:#f3f6fa; }
QFrame#sidebar { background:#152b37; border:0; }
QLabel#brand { color:white; font-size:23px; font-weight:700; }
QLabel#sideNote { color:#a8c4cf; font-size:12px; }
QPushButton#nav { background:transparent; color:#b9cbd4; text-align:left; border:0; padding:16px 12px; font-size:15px; }
QPushButton#nav:checked { background:#254c54; color:white; border-left:4px solid #7ee0c1; }
QFrame#card { background:white; border:1px solid #dce4ed; border-radius:12px; }
QLabel#title { font-size:26px; font-weight:700; color:#142c3b; }
QLabel#section { font-size:17px; font-weight:700; }
QLabel#muted { color:#627489; }
QLabel#pill { background:#e6f2ef; color:#126657; border-radius:14px; padding:8px 13px; font-weight:700; }
QLabel#hero { font-size:52px; font-weight:700; color:#147b68; }
QLabel#notice { background:#eaf3f7; border-radius:6px; padding:10px; color:#355d73; }
QPushButton { background:white; border:1px solid #ced9e4; border-radius:7px; padding:9px 13px; min-height:20px; }
QPushButton:hover { background:#edf5f7; border-color:#9cb8bd; }
QPushButton:disabled { color:#98a4b2; background:#edf1f5; border-color:#e0e7ee; }
QPushButton#primary { background:#147d6b; color:white; border:0; font-weight:700; }
QPushButton#primary:hover { background:#096653; }
QPushButton#primary:disabled { background:#b6d1cb; color:#f4f8f7; }
QPushButton#category { font-size:16px; min-height:32px; }
QPushButton#category:checked { background:#e5f4ef; color:#0e725e; border:2px solid #239781; font-weight:700; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox { border:1px solid #cdd9e4; border-radius:6px; padding:7px; background:white; min-height:19px; }
QComboBox QAbstractItemView { background:white; selection-background-color:#d7eee7; selection-color:#183d34; }
QCheckBox { spacing:8px; }
QCheckBox::indicator { width:17px; height:17px; }
QTableWidget { background:white; border:1px solid #e0e7ef; gridline-color:#ecf0f5; selection-background-color:#e8f3f1; selection-color:#173b32; }
QTableWidget::indicator { width:18px; height:18px; }
QHeaderView::section { background:#f1f5f9; border:0; padding:10px 6px; font-weight:700; color:#596c7e; }
QTableWidget::item { padding:4px; }
QProgressBar { border:0; background:#e7edf3; border-radius:5px; min-height:9px; text-align:center; }
QProgressBar::chunk { background:#38a28b; border-radius:5px; }
QScrollArea { border:0; background:transparent; }
QScrollBar:vertical { background:#edf1f5; width:10px; }
QScrollBar::handle:vertical { background:#bdcdd8; border-radius:5px; min-height:24px; }
QStatusBar { background:#f3f6fa; color:#64788c; font-size:12px; }
QToolTip { background:#183a49; color:white; border:0; padding:6px; }
"""


def text(value="", style=None):
    widget = W.QLabel(value)
    widget.setWordWrap(True)
    if style:
        widget.setObjectName(style)
    return widget


def button(value, fn, primary=False):
    widget = W.QPushButton(value)
    widget.setCursor(C.Qt.CursorShape.PointingHandCursor)
    widget.clicked.connect(fn)
    if primary:
        widget.setObjectName("primary")
    return widget


def horizontal(*widgets):
    layout = W.QHBoxLayout()
    layout.setSpacing(10)
    for item in widgets:
        if isinstance(item, W.QWidget):
            layout.addWidget(item)
        else:
            layout.addStretch(item)
    return layout


def card():
    widget = W.QFrame()
    widget.setObjectName("card")
    layout = W.QVBoxLayout(widget)
    layout.setContentsMargins(18, 16, 18, 16)
    layout.setSpacing(12)
    return widget, layout


def stage_controls(layout):
    row = W.QHBoxLayout()
    checks = {}
    for key, label in (
        ("denoise", "정규화·DWT"),
        ("pca", "PCA · 3성분"),
        ("lowpass", "저역 통과 · 8Hz"),
    ):
        check = W.QCheckBox(label)
        check.setChecked(True)
        checks[key] = check
        row.addWidget(check)
    row.addStretch()
    row.addWidget(text("모두 켠 파형으로 학습합니다.", "muted"))
    layout.addLayout(row)
    return checks


def plot(title, height=180):
    widget = pg.PlotWidget(background="white")
    widget.setMinimumHeight(height)
    widget.setTitle(title, color="#60778a", size="10pt")
    widget.setLabel("bottom", "시간", units="s")
    widget.setLabel("left", "진폭")
    widget.showGrid(x=True, y=True, alpha=0.12)
    widget.setMenuEnabled(False)
    widget.getPlotItem().hideButtons()
    widget.setMouseEnabled(x=False, y=False)
    return widget


class Signals(C.QObject):
    result = C.Signal(object)
    error = C.Signal(str)
    finished = C.Signal()


class Worker(C.QRunnable):
    def __init__(self, fn):
        super().__init__()
        self.fn, self.signals = fn, Signals()

    def run(self):
        try:
            self.signals.result.emit(self.fn())
        except Exception as exc:
            self.signals.error.emit(str(exc))
        finally:
            self.signals.finished.emit()


class ConnectionDialog(W.QDialog):
    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.last_event = -1
        self.pending = None
        self.setWindowTitle("WifiSensing 2.0 · 보드 연결")
        self.resize(650, 590)
        layout = W.QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(14)
        layout.addWidget(text("보드에서 신호를 받아볼까요?", "title"))
        layout.addWidget(
            text(
                "공유기+ESP32 또는 C6 송신·수신 보드를 연결합니다. C6 두 대는 공유기 없이 전용 신호를 주고받습니다.",
                "muted",
            )
        )
        self.ports = W.QComboBox()
        self.usb = button("USB 연결", self.toggle_usb, True)
        layout.addWidget(text("1. USB 보드 연결", "section"))
        layout.addLayout(
            horizontal(
                self.ports, button("포트 검색", self.refresh_ports), self.usb
            )
        )
        self.usb_text = text("", "muted")
        layout.addWidget(self.usb_text)
        layout.addWidget(button("C6 송신·수신 펌웨어 설치", self.install_c6))
        self.pair_channel = W.QComboBox()
        for ch in (1, 6, 11):
            self.pair_channel.addItem(f"C6 무선 채널 {ch}", ch)
        self.pair_channel.setCurrentIndex(2)
        self.pair_apply = button(
            "채널 적용",
            lambda: self.command(
                {
                    "cmd": "configure",
                    "channel": self.pair_channel.currentData(),
                },
                "양쪽 보드에 같은 채널을 적용하세요.",
            ),
        )
        self.pair_calibrate = button(
            "수신 이득 다시 측정",
            lambda: self.command(
                {"cmd": "calibrate"},
                "보드와 주변을 고정하고 약 2초 기다리세요.",
            ),
        )
        layout.addLayout(
            horizontal(self.pair_channel, self.pair_apply, self.pair_calibrate)
        )
        self.wifi_heading = text("2. ESP32가 사용할 Wi-Fi", "section")
        layout.addWidget(self.wifi_heading)
        self.networks = W.QComboBox()
        self.networks.currentIndexChanged.connect(self.select_network)
        self.scan = button("Wi-Fi 검색", self.scan_wifi)
        layout.addLayout(horizontal(self.networks, self.scan))
        self.ssid = W.QLineEdit()
        self.ssid.setPlaceholderText("2.4GHz Wi-Fi 이름")
        self.password = W.QLineEdit()
        self.password.setPlaceholderText("비밀번호 · 파일에 저장하지 않습니다")
        self.password.setEchoMode(W.QLineEdit.EchoMode.Password)
        layout.addWidget(self.ssid)
        layout.addWidget(self.password)
        self.join = button("이 Wi-Fi에 연결", self.join_wifi, True)
        self.leave = button("Wi-Fi 연결 해제", self.leave_wifi)
        layout.addLayout(horizontal(self.join, self.leave))
        self.message = text("USB를 연결한 뒤 Wi-Fi를 검색하세요.", "notice")
        self.message.setMinimumHeight(68)
        layout.addWidget(self.message)
        layout.addWidget(
            text(
                "같은 보드는 두 앱이 동시에 사용할 수 없습니다. 기존 WifiSensing에서 USB 연결을 종료한 뒤 연결하세요.",
                "muted",
            )
        )
        layout.addStretch()
        layout.addWidget(button("완료 · 수집 화면으로", self.accept, True))
        self.refresh_ports()
        self.timer = C.QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(250)
        self.refresh()

    def refresh_ports(self):
        from serial.tools import list_ports

        current = self.ports.currentData()
        self.ports.clear()
        self.port_bauds = {}
        for port in list_ports.comports():
            self.ports.addItem(
                f"{port.device} · {port.description}", port.device
            )
            self.port_bauds[port.device] = services.baud_for_port(port.vid)
        if not self.ports.count():
            self.ports.addItem("보드를 데이터 USB 케이블로 연결하세요.", None)
        if self.ports.findData(current) >= 0:
            self.ports.setCurrentIndex(self.ports.findData(current))

    def install_c6(self):
        if self.host.busy:
            self.message.setText("수집·학습이 끝난 뒤 설치하세요.")
            return
        from firmware_ui import FirmwareDialog

        self.host.stop_recognition()
        db.LIVE.disconnect()
        FirmwareDialog(self).exec()
        self.refresh_ports()

    def toggle_usb(self):
        if self.host.busy:
            self.message.setText("수집·학습이 끝난 뒤 연결을 변경하세요.")
            return
        self.host.stop_recognition()
        try:
            if db.LIVE.status()["connected"]:
                db.LIVE.disconnect()
            else:
                port = self.ports.currentData()
                if not port:
                    raise ValueError("USB 보드를 먼저 연결하세요.")
                db.LIVE.connect(port, self.port_bauds.get(port, 115200))
                db.LIVE.command({"cmd": "status"})
                self.message.setText("보드 응답을 기다리고 있습니다.")
                self.pending = time.perf_counter() + 8
        except Exception as exc:
            self.message.setText(
                "USB 연결 실패. 기존 WifiSensing의 USB 연결을 종료하고 다시 시도하세요.\n"
                + str(exc)
            )
        self.refresh()

    def command(self, payload, message, wait=15):
        if self.host.busy:
            self.message.setText("수집·학습이 끝난 뒤 Wi-Fi를 변경하세요.")
            return
        self.host.stop_recognition()
        try:
            db.LIVE.command(payload)
            self.message.setText(message)
            self.pending = time.perf_counter() + wait
        except Exception as exc:
            self.message.setText(str(exc))

    def scan_wifi(self):
        if db.LIVE.board_status().get("state") == "connected":
            self.message.setText(
                "다른 Wi-Fi를 찾으려면 먼저 Wi-Fi 연결을 해제하세요."
            )
            return
        self.command(
            {"cmd": "scan"}, "보드가 주변 2.4GHz Wi-Fi를 찾고 있습니다."
        )

    def select_network(self, *_):
        n = self.networks.currentData()
        if n:
            self.ssid.setText(n["ssid"])

    def join_wifi(self):
        ssid, password = self.ssid.text(), self.password.text()
        if (
            not 1 <= len(ssid.encode("utf-8")) <= 32
            or len(password.encode("utf-8")) > 63
        ):
            self.message.setText("Wi-Fi 이름과 비밀번호 길이를 확인하세요.")
            return
        payload = {"cmd": "connect", "ssid": ssid, "password": password}
        n = self.networks.currentData()
        if n and n["ssid"] == ssid:
            payload["bssid"] = n["bssid"]
        self.command(payload, "Wi-Fi에 연결하고 있습니다.", 25)
        self.password.clear()

    def leave_wifi(self):
        self.command({"cmd": "disconnect"}, "Wi-Fi 연결을 해제하고 있습니다.")

    def refresh(self):
        live, board = db.LIVE.status(), db.LIVE.board_status()
        pair = board.get("mode") == "espnow" and board.get("chip") == "esp32c6"
        self.wifi_heading.setVisible(not pair)
        self.usb.setText("USB 연결 종료" if live["connected"] else "USB 연결")
        self.usb_text.setText(
            f"{live['port'] or 'USB 미연결'} · {board.get('chip', '보드 정보 대기')}"
        )
        for w in (
            self.networks,
            self.scan,
            self.ssid,
            self.password,
            self.join,
            self.leave,
        ):
            w.setVisible(not pair)
            w.setEnabled(live["connected"] and not self.host.busy and not pair)
        for w in (self.pair_channel, self.pair_apply, self.pair_calibrate):
            w.setVisible(pair)
            w.setEnabled(pair and live["connected"] and not self.host.busy)
        if board["event_seq"] != self.last_event:
            self.last_event = board["event_seq"]
            if board["last_event"] == "scan":
                self.networks.clear()
                for n in board["networks"]:
                    self.networks.addItem(f"{n['ssid']} · {n['rssi']} dBm", n)
                self.select_network()
                self.message.setText(
                    f"Wi-Fi {len(board['networks'])}개를 찾았습니다. 이름을 고르고 비밀번호를 입력하세요."
                )
                self.pending = None
            elif board["last_event"] == "status":
                state = board.get("state")
                if state == "connected":
                    self.message.setText(
                        "Wi-Fi 연결 완료 · 새 CSI 신호를 기다립니다."
                    )
                elif state == "ready":
                    self.message.setText(
                        "보드 준비 완료 · 사용할 Wi-Fi를 연결하세요."
                    )
                elif state == "disconnected":
                    self.message.setText(
                        f"Wi-Fi 연결이 끊겼습니다. 이름·비밀번호·2.4GHz 설정을 확인하세요. (코드 {board.get('reason')})"
                    )
                self.pending = None
        if self.pending and time.perf_counter() > self.pending:
            self.pending = None
            self.message.setText(
                "보드 응답이 없습니다. 이 보드에 맞는 WifiSensing 수집 펌웨어가 설치되어 있는지 확인하세요."
                if not board.get("chip")
                else "응답을 받지 못했습니다. USB 연결과 2.4GHz Wi-Fi를 확인하세요."
            )
        if self.host.fresh_frames():
            self.message.setText(
                "신호 수신 중입니다. 완료를 눌러 수집을 시작하세요."
            )
        if pair:
            role = board.get("role")
            detail = (
                "송신 중 · 수집하려면 수신 보드의 USB를 선택하세요."
                if role == "transmitter"
                else "송신 보드 대기 · 양쪽 전원과 채널을 확인하세요."
                if board.get("state") == "waiting_sender"
                else "수신 이득 측정 중 · 보드와 주변을 잠시 고정하세요."
                if not board.get("gain_ready")
                else "수신 준비 완료 · 새 신호가 들어오면 수집할 수 있습니다."
            )
            self.message.setText(
                f"C6 전용 연결 · 채널 {board.get('channel')} · 목표 60 Hz\n{detail}"
            )


class RecordDialog(W.QDialog):
    def __init__(self, host, record):
        super().__init__(host)
        self.host, self.record = host, record
        self.setWindowTitle("기록 미리보기 · 필요한 구간 고르기")
        self.resize(960, 610)
        layout = W.QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.addWidget(text(record["label"] + " · 신호 구간 편집", "title"))
        layout.addWidget(
            text(
                "전체 기록을 확인하거나, 초록색 경계로 필요한 시간만 골라 새 기록으로 저장하세요.",
                "muted",
            )
        )
        self.stages = stage_controls(layout)
        self.graph = plot("최종 전처리 신호 · 학습 입력", 250)
        frames = record["frames"]
        self.record_line = self.graph.plot(
            pen=pg.mkPen("#188772", width=1.5), connect="finite"
        )
        self.record_aux = [
            self.graph.plot(pen=pg.mkPen(c, width=1.3), connect="finite")
            for c in ("#238bb4", "#db9852")
        ]
        for check in self.stages.values():
            check.toggled.connect(self.refresh_signal)
            check.setEnabled(record["representation"] == "raw_iq_52")
        self.refresh_signal()
        self.region = pg.LinearRegionItem(
            [frames[0]["t"], frames[-1]["t"]],
            bounds=(frames[0]["t"], frames[-1]["t"]),
            brush=(50, 165, 135, 35),
        )
        self.graph.addItem(self.region)
        layout.addWidget(self.graph, 1)
        self.start, self.end = W.QDoubleSpinBox(), W.QDoubleSpinBox()
        for spin in (self.start, self.end):
            spin.setDecimals(3)
            spin.setRange(frames[0]["t"], frames[-1]["t"])
            spin.setSuffix(" 초")
        self.start.setValue(frames[0]["t"])
        self.end.setValue(frames[-1]["t"])
        self.region.sigRegionChanged.connect(self.from_region)
        self.start.valueChanged.connect(self.to_region)
        self.end.valueChanged.connect(self.to_region)
        self.label = W.QLineEdit(record["label"])
        layout.addLayout(
            horizontal(
                text("시작"),
                self.start,
                text("끝"),
                self.end,
                text("행동"),
                self.label,
            )
        )
        q = signal_quality(frames, record["representation"])
        info = f"{len(frames):,}프레임 · 평균 {q['rate_hz']:.1f} Hz · 최대 공백 {q['max_gap_seconds']:.3f}초"
        info += (
            "\n수신 검사 통과 · 행동 라벨은 직접 확인해주세요."
            if q["transport_ok"]
            else "\n주의: " + ", ".join(q["issues"])
        )
        layout.addWidget(text(info, "notice"))
        layout.addLayout(
            horizontal(
                button("이 기록 라벨 수정", self.relabel),
                button("이 기록 삭제", self.delete),
                1,
                button("선택 구간을 새 기록으로 저장", self.save_clip, True),
                button("닫기", self.reject),
            )
        )

    def refresh_signal(self):
        MainWindow.set_aux(self.record_aux, [], None)
        options = {
            key: check.isChecked() for key, check in self.stages.items()
        }
        frames, seconds = self.record["frames"], self.host.window.currentData()
        if (
            not any(options.values())
            and self.record["representation"] == "raw_iq_52"
        ):
            self.record_line.setData(
                [f["t"] for f in frames], [f["amp"][0] for f in frames]
            )
            self.graph.setTitle(
                "원본 진폭 · 전처리 모두 꺼짐", color="#60778a", size="10pt"
            )
            return
        try:
            windows = signal_windows(
                frames, self.record["representation"], seconds, options
            )
            if not windows:
                raise ValueError(f"{seconds}초 이상의 기록이 필요합니다.")
            x, y = [], []
            for window in windows:
                x.extend(window["time"] + [float("nan")])
                y.extend(window["signal"] + [float("nan")])
            self.record_line.setData(x, y)
            matrix = np.concatenate(
                [
                    np.vstack(
                        [
                            np.asarray(w["components"]),
                            np.full((1, len(w["components"][0])), np.nan),
                        ]
                    )
                    for w in windows
                ]
            )
            MainWindow.set_aux(self.record_aux, x, matrix)
            mode = (
                "최종 전처리 · 학습 입력"
                if all(options.values())
                else "단계 비교 · 학습은 모든 단계 적용"
            )
            self.graph.setTitle(
                f"{mode} · 완전한 {seconds}초 구간",
                color="#60778a",
                size="10pt",
            )
        except ValueError as exc:
            self.record_line.clear()
            self.graph.setTitle(str(exc), color="#9b6b10", size="10pt")

    def from_region(self):
        start, end = self.region.getRegion()
        for spin, value in ((self.start, start), (self.end, end)):
            spin.blockSignals(True)
            spin.setValue(value)
            spin.blockSignals(False)

    def to_region(self):
        self.region.setRegion((self.start.value(), self.end.value()))

    def relabel(self):
        if not self.label.text().strip():
            return
        self.record["label"] = self.label.text().strip()[:80]
        db.write_json(db.SEGMENTS / f"{self.record['id']}.json", self.record)
        self.host.reload_records()
        self.accept()

    def save_clip(self):
        try:
            result = services.clip_record(
                self.record,
                self.start.value(),
                self.end.value(),
                self.label.text(),
            )
            self.host.selected_ids.discard(self.record["id"])
            self.host.selected_ids.add(result["id"])
            self.host.reload_records()
            self.host.statusBar().showMessage(
                "선택 구간을 저장했습니다. 원본 대신 새 구간에 학습 체크했습니다."
            )
            self.accept()
        except Exception as exc:
            self.host.error(str(exc))

    def delete(self):
        move_records([self.record["id"]])
        self.host.selected_ids.discard(self.record["id"])
        self.host.reload_records()
        self.host.statusBar().showMessage(
            "기록을 휴지통으로 옮겼습니다. 복원할 수 있습니다."
        )
        self.accept()


class MainWindow(W.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("WifiSensing 2.0 · 수집에서 인식까지")
        icon = Path(__file__).parent / "app.ico"
        if icon.exists():
            self.setWindowIcon(G.QIcon(str(icon)))
        self.settings = services.load_settings()
        self.custom_behaviors = services.custom_behaviors(self.settings)
        self.selected_ids = set(self.settings.get("selected_ids", []))
        if self.settings.get("processing_profile") != PROFILE:
            self.selected_ids.clear()
        self.model = services.read_model(self.settings.get("model_id"))
        self.round_id = self.settings.get("round_id") or uuid.uuid4().hex
        self.round_number = int(self.settings.get("round_number", 1))
        self.records = []
        self.job = None
        self.busy = self.predicting = False
        self.recognition = Recognition()
        self.workers = set()
        self.pool = C.QThreadPool(self)
        self.pool.setMaxThreadCount(2)
        self.last_plot = self.last_predict = 0.0
        self.previewing = False
        self.preview_generation = 0
        self.preview_subcarrier = 0
        self.preview_autoscale = True
        self.build_ui()
        self.reload_records()
        self.timer = C.QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(100)
        self.setMinimumSize(1100, 690)
        screen = W.QApplication.primaryScreen().availableGeometry()
        self.resize(
            min(1320, screen.width() - 24), min(840, screen.height() - 50)
        )

    def build_ui(self):
        central = W.QWidget()
        self.setCentralWidget(central)
        shell = W.QHBoxLayout(central)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        side = W.QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(185)
        sl = W.QVBoxLayout(side)
        sl.setContentsMargins(12, 28, 12, 20)
        sl.setSpacing(10)
        sl.addWidget(text("WifiSensing", "brand"))
        sl.addWidget(text("2.0   SIGNAL STUDIO", "sideNote"))
        sl.addSpacing(32)
        self.nav = []
        for i, name in enumerate(
            ("01  신호 수집", "02  기록 선택·학습", "03  실시간 인식")
        ):
            b = button(name, lambda checked=False, n=i: self.go(n))
            b.setObjectName("nav")
            b.setCheckable(True)
            sl.addWidget(b)
            self.nav.append(b)
        sl.addStretch()
        sl.addWidget(
            text("내 기록으로 학습하고\n새 신호로 확인하세요.", "sideNote")
        )
        sl.addSpacing(14)
        sl.addWidget(
            button(
                "2.0 저장 폴더",
                lambda: G.QDesktopServices.openUrl(
                    C.QUrl.fromLocalFile(str(db.DATA))
                ),
            )
        )
        sl.addWidget(text("기존 버전과 별도 저장", "sideNote"))
        shell.addWidget(side)
        main = W.QVBoxLayout()
        main.setContentsMargins(24, 22, 24, 8)
        main.setSpacing(15)
        header = W.QHBoxLayout()
        titles = W.QVBoxLayout()
        self.heading = text("", "title")
        self.subtitle = text("", "muted")
        titles.addWidget(self.heading)
        titles.addWidget(self.subtitle)
        header.addLayout(titles, 1)
        self.connection_status = text("보드 미연결", "pill")
        header.addWidget(self.connection_status)
        self.connection_button = button("보드 연결", self.open_connection)
        header.addWidget(self.connection_button)
        main.addLayout(header)
        self.pages = W.QStackedWidget()
        main.addWidget(self.pages, 1)
        shell.addLayout(main, 1)
        self.build_capture()
        self.build_training()
        self.build_recognition()
        self.go(0)

    def page(self):
        content = W.QWidget()
        layout = W.QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        scroll = W.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        self.pages.addWidget(scroll)
        return layout

    def build_capture(self):
        layout = self.page()
        upper = W.QHBoxLayout()
        collect, cl = card()
        self.collect_box = collect
        cl.setSpacing(8)
        self.behavior = W.QComboBox()
        self.behavior.setAccessibleName("기록할 행동")
        self.behavior.setSizeAdjustPolicy(
            W.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.behavior.setMinimumContentsLength(8)
        self.behavior.setMaximumWidth(200)
        self.delete_behavior_button = button(
            "선택 행동 삭제", self.remove_behavior
        )
        self.delete_behavior_button.setToolTip(
            "선택한 사용자 행동을 목록에서 삭제합니다. 수집 기록과 모델은 유지됩니다."
        )
        behavior_title = text("어떤 행동을 기록할까요?", "section")
        behavior_title.setWordWrap(False)
        cl.addLayout(horizontal(behavior_title, 1, self.behavior))
        self.category_scroll = W.QScrollArea()
        self.category_scroll.setWidgetResizable(True)
        self.category_scroll.setHorizontalScrollBarPolicy(
            C.Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        category_content = W.QWidget()
        self.category_grid = W.QGridLayout(category_content)
        self.category_grid.setContentsMargins(0, 0, 0, 0)
        self.category_grid.setSpacing(8)
        self.category_grid.setAlignment(C.Qt.AlignmentFlag.AlignTop)
        for column in range(3):
            self.category_grid.setColumnStretch(column, 1)
        self.category_scroll.setWidget(category_content)
        cl.addWidget(self.category_scroll)
        self.categories = []
        self.rebuild_behaviors(self.settings.get("behavior", "정지"))
        self.behavior.currentTextChanged.connect(self.sync_behavior)
        self.new_behavior = W.QLineEdit()
        self.new_behavior.setMaxLength(80)
        self.new_behavior.setPlaceholderText(
            "새 행동 이름 · 예: 걷기, 호흡, 앉기"
        )
        self.new_behavior.setAccessibleName("추가할 행동 이름")
        self.new_behavior.setClearButtonEnabled(True)
        self.save_behavior_button = button("행동 저장", self.add_behavior)
        self.new_behavior.returnPressed.connect(self.add_behavior)
        cl.addLayout(
            horizontal(
                self.new_behavior,
                self.save_behavior_button,
                self.delete_behavior_button,
            )
        )
        self.behavior_hint = text(
            "정지·낙상은 기본 항목입니다. 저장한 행동은 다음 실행에도 남습니다.",
            "muted",
        )
        cl.addWidget(self.behavior_hint)
        self.sync_behavior()
        self.prepare, self.seconds = W.QSpinBox(), W.QSpinBox()
        self.prepare.setRange(0, 30)
        self.prepare.setValue(int(self.settings.get("prepare", 3)))
        self.seconds.setRange(2, 120)
        self.seconds.setValue(int(self.settings.get("seconds", 12)))
        for spin in (self.prepare, self.seconds):
            spin.setSuffix(" 초")
        cl.addLayout(
            horizontal(
                text("준비"), self.prepare, text("기록 길이"), self.seconds
            )
        )
        self.note = W.QLineEdit()
        self.note.setPlaceholderText("실험 메모 · 예: 책상 옆에서 천천히 걷기")
        cl.addWidget(self.note)
        self.round_label = text(f"측정 {self.round_number}회차", "muted")
        cl.addLayout(
            horizontal(
                self.round_label, button("다음 측정 회차", self.next_round)
            )
        )
        cl.addWidget(
            text(
                "한 회차에 학습할 행동들을 각각 기록하고 다음 회차로 반복하세요. 준비 시간이 끝난 뒤 선택한 행동을 수행합니다.",
                "muted",
            )
        )
        upper.addWidget(collect, 3)
        progress, pl = card()
        pl.addWidget(text("기록 상태", "section"))
        self.capture_status = text("수집 준비", "hero")
        self.capture_status.setStyleSheet(
            "font-size:30px; font-weight:700; color:#167b68;"
        )
        pl.addWidget(self.capture_status)
        self.capture_hint = text("위의 보드 연결부터 시작하세요.", "muted")
        pl.addWidget(self.capture_hint)
        self.capture_progress = W.QProgressBar()
        self.capture_progress.setRange(0, 1000)
        self.capture_progress.setValue(0)
        self.capture_progress.setTextVisible(False)
        pl.addWidget(self.capture_progress)
        pl.addStretch()
        self.capture_button = button(
            "선택한 행동 수집 시작", self.start_capture, True
        )
        self.cancel_button = button("이번 수집 취소", self.cancel_capture)
        self.cancel_button.setEnabled(False)
        pl.addWidget(self.capture_button)
        pl.addWidget(self.cancel_button)
        self.saved_count = text("", "muted")
        pl.addWidget(self.saved_count)
        pl.addWidget(button("기록을 골라 학습하기 →", lambda: self.go(1)))
        upper.addWidget(progress, 2)
        layout.addLayout(upper)
        signal, vl = card()
        vl.setSpacing(8)
        top = horizontal(text("들어오는 신호", "section"), 1)
        self.channel = W.QComboBox()
        self.channel.setAccessibleName("실시간 파형 채널")
        self.channel.addItem("50채널 · PC1·PC2·PC3", None)
        for i, number in enumerate(SUBCARRIERS):
            self.channel.addItem(f"채널 {number}", i)
        self.channel.setToolTip(
            "개별 채널을 고르면 PCA가 꺼집니다. 전처리를 모두 끄면 해당 채널의 원본 진폭을 봅니다."
        )
        self.axis_lock = W.QCheckBox("세로축 고정")
        self.axis_lock.setToolTip(
            "현재 단계에서 세로축을 유지합니다. 단계나 채널을 바꾸면 새 값의 크기에 한 번 맞춥니다."
        )
        top.addWidget(self.channel)
        top.addWidget(self.axis_lock)
        top.addWidget(button("50채널 상세 비교", self.signal_details))
        vl.addLayout(top)
        self.capture_stages = stage_controls(vl)
        for check in self.capture_stages.values():
            check.setAccessibleName("실시간 " + check.text())
            check.setToolTip(
                "누르면 현재 신호에 즉시 적용하고 계속 갱신합니다. 저장·학습·행동 판단에는 모든 단계를 적용합니다."
            )
        self.capture_plot = plot(
            "새 신호 대기 · 최종 전처리 파형을 표시합니다", 155
        )
        self.capture_plot.setFixedHeight(160)
        self.capture_line = self.capture_plot.plot(
            pen=pg.mkPen("#168971", width=1.6)
        )
        self.capture_aux_lines = [
            self.capture_plot.plot(pen=pg.mkPen(c, width=1.3))
            for c in ("#238bb4", "#db9852")
        ]
        self.channel.currentIndexChanged.connect(self.preview_channel_changed)
        for check in self.capture_stages.values():
            check.toggled.connect(self.preview_controls_changed)
        vl.addWidget(self.capture_plot, 1)
        self.signal_status = text(
            "보드와 송신 연결이 준비되면 신호가 들어옵니다.", "muted"
        )
        vl.addWidget(self.signal_status)
        layout.addWidget(signal, 1)

    def build_training(self):
        layout = self.page()
        tools = W.QHBoxLayout()
        self.filter = W.QComboBox()
        self.filter.addItem("모든 행동", None)
        self.filter.currentIndexChanged.connect(self.filter_records)
        tools.addWidget(self.filter)
        tools.addWidget(button("보이는 기록 모두 선택", self.select_visible))
        tools.addWidget(button("모두 해제", self.clear_selection))
        tools.addStretch()
        self.import_button = button("기록 가져오기", self.import_dialog)
        tools.addWidget(self.import_button)
        tools.addWidget(button("선택 기록 내보내기", self.export_dialog))
        tools.addWidget(button("휴지통", self.trash_dialog))
        layout.addLayout(tools)
        body = W.QHBoxLayout()
        records, rl = card()
        rl.addWidget(text("학습에 쓸 기록만 체크하세요", "section"))
        rl.addWidget(
            text(
                "행을 더블클릭하면 파형 확인·구간 선택·라벨 수정·삭제를 할 수 있습니다.",
                "muted",
            )
        )
        self.table = W.QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["학습", "행동", "길이", "수집 시각", "회차", "수신"]
        )
        self.table.setEditTriggers(
            W.QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.table.setSelectionBehavior(
            W.QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.table.setSelectionMode(
            W.QAbstractItemView.SelectionMode.SingleSelection
        )
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(
            W.QHeaderView.ResizeMode.Stretch
        )
        self.table.horizontalHeader().setSectionResizeMode(
            0, W.QHeaderView.ResizeMode.Fixed
        )
        self.table.setColumnWidth(0, 48)
        self.table.verticalHeader().setDefaultSectionSize(39)
        self.table.itemChanged.connect(self.item_changed)
        self.table.cellDoubleClicked.connect(self.open_record)
        self.table.setMinimumHeight(220)
        rl.addWidget(self.table, 1)
        self.selection_summary = text("", "notice")
        rl.addWidget(self.selection_summary)
        self.delete_selected_button = button(
            "체크한 기록 삭제 (0)", self.delete_selected
        )
        self.delete_selected_button.setToolTip(
            "필터 밖의 체크한 기록도 포함합니다. 삭제 후 휴지통에서 복원할 수 있습니다."
        )
        rl.addLayout(
            horizontal(
                button("선택한 행의 파형·구간 편집", self.open_record),
                self.delete_selected_button,
            )
        )
        body.addWidget(records, 3)
        train, tl = card()
        train.setMaximumWidth(380)
        tl.addWidget(text("체크한 기록으로 모델 만들기", "section"))
        self.model_name = W.QLineEdit(
            self.settings.get("model_name", "정지·걷기 모델")
        )
        self.model_name.setMaxLength(80)
        self.model_name.setPlaceholderText("모델 이름")
        tl.addWidget(self.model_name)
        self.window = W.QComboBox()
        for seconds in (2, 4, 8, 16):
            self.window.addItem(f"최근 {seconds}초를 보고 판단", seconds)
        self.window.setCurrentIndex(
            max(0, self.window.findData(self.settings.get("window", 2)))
        )
        self.window.currentIndexChanged.connect(self.selection_changed)
        tl.addWidget(self.window)
        tl.addWidget(
            text(
                "학습과 실시간 인식에 같은 길이를 사용합니다. 설정을 바꾸면 다시 학습하세요.",
                "muted",
            )
        )
        self.training_ready = text("", "notice")
        tl.addWidget(self.training_ready)
        self.train_button = button(
            "체크한 기록만 학습", self.start_training, True
        )
        tl.addWidget(self.train_button)
        self.train_progress = W.QProgressBar()
        self.train_progress.setRange(0, 0)
        self.train_progress.hide()
        tl.addWidget(self.train_progress)
        self.model_summary = text("아직 학습한 모델이 없습니다.", "muted")
        self.model_summary.setToolTip(
            "균형 정확도 = 평가 기록에서 행동별로 맞힌 비율의 평균. 현재 행동의 확률이 아닙니다."
        )
        tl.addWidget(self.model_summary)
        tl.addWidget(
            text(
                "정규화·DWT → PCA 3성분 → 8Hz 저역 통과\n초록·파랑·주황의 최종 파형 3개를 모두 학습합니다. 행동별 3회차 이상 필요합니다.",
                "muted",
            )
        )
        self.evaluation_button = button(
            "평가 결과 · 사용한 기록", self.show_evaluation
        )
        tl.addWidget(self.evaluation_button)
        tl.addWidget(button("라즈베리파이 모델 내보내기", self.export_edge))
        tl.addStretch()
        self.to_recognition = button(
            "이 모델로 인식하러 가기 →", lambda: self.go(2), True
        )
        tl.addWidget(self.to_recognition)
        body.addWidget(train, 2)
        layout.addLayout(body, 1)

    def build_recognition(self):
        layout = self.page()
        self.active_model = text("", "notice")
        layout.addWidget(self.active_model)
        body = W.QHBoxLayout()
        result, rl = card()
        rl.addWidget(text("현재 행동", "section"))
        self.inference_badge = text("인식 꺼짐", "pill")
        rl.addWidget(self.inference_badge, 0, C.Qt.AlignmentFlag.AlignLeft)
        self.current_action = text("인식 대기", "hero")
        self.current_action.setAlignment(C.Qt.AlignmentFlag.AlignCenter)
        rl.addWidget(self.current_action, 1)
        self.inference_reason = text(
            "2단계에서 기록을 선택하고 모델을 학습하세요.", "muted"
        )
        self.inference_reason.setAlignment(C.Qt.AlignmentFlag.AlignCenter)
        rl.addWidget(self.inference_reason)
        self.inference_button = button(
            "실시간 인식 시작", self.toggle_recognition, True
        )
        self.inference_button.setMinimumHeight(34)
        rl.addWidget(self.inference_button)
        self.freshness = text("신호를 새로 받은 뒤에만 판단합니다.", "muted")
        rl.addWidget(self.freshness)
        body.addWidget(result, 3)
        scores, sc = card()
        sc.addWidget(text("행동별 모델 점수", "section"))
        sc.addWidget(
            text(
                "학습한 행동 중 어느 쪽으로 판단하는지 보여줍니다. 실제 정답 확률은 아닙니다.",
                "muted",
            )
        )
        self.score_rows = W.QVBoxLayout()
        sc.addLayout(self.score_rows)
        self.score_bars = {}
        sc.addStretch()
        sc.addWidget(
            text(
                "최고 점수 65% 미만 또는 1·2위 차이 15%p 미만이면 보류합니다. 학습하지 않은 행동의 자동 탐지는 보장하지 않습니다.",
                "muted",
            )
        )
        body.addWidget(scores, 2)
        layout.addLayout(body, 3)
        live, ll = card()
        signal_title = text("판단에 들어오는 실제 신호", "section")
        signal_title.setWordWrap(False)
        fixed_hint = text("송신기·수신기는 고정하세요.", "muted")
        fixed_hint.setWordWrap(False)
        ll.addLayout(horizontal(signal_title, 1, fixed_hint))
        self.live_plot = plot("판단에 사용한 최종 전처리 신호", 135)
        self.live_plot.setFixedHeight(160)
        self.live_line = self.live_plot.plot(
            pen=pg.mkPen("#238bb4", width=1.4)
        )
        self.live_line.setPen(pg.mkPen("#168971", width=1.6))
        self.live_aux_lines = [
            self.live_plot.plot(pen=pg.mkPen(c, width=1.3))
            for c in ("#238bb4", "#db9852")
        ]
        ll.addWidget(self.live_plot)
        ll.addWidget(
            text(
                "정지 → 걷기 → 정지를 반복하며 확인하세요. 이 화면에서는 행동 범주를 직접 선택하지 않습니다.",
                "muted",
            )
        )
        layout.addWidget(live, 2)

    def go(self, index):
        self.pages.setCurrentIndex(index)
        for i, b in enumerate(self.nav):
            b.setChecked(i == index)
        titles = [
            (
                "신호를 모아보세요",
                "행동을 정하고 시작하면, 정해진 시간만큼 기록합니다.",
            ),
            (
                "필요한 기록만 골라 학습하세요",
                "체크한 기록 → 모델 생성 → 새 신호에서 확인",
            ),
            (
                "지금 어떤 행동을 하고 있나요?",
                "학습한 모델이 새로 들어오는 신호를 판단합니다.",
            ),
        ]
        self.heading.setText(titles[index][0])
        self.subtitle.setText(titles[index][1])

    def error(self, message):
        W.QMessageBox.information(self, "WifiSensing 2.0", message)

    def background(self, fn, success, failure=None):
        worker = Worker(fn)
        self.workers.add(worker)
        worker.signals.result.connect(success)
        worker.signals.error.connect(failure or self.error)
        worker.signals.finished.connect(lambda: self.workers.discard(worker))
        self.pool.start(worker)

    def save_settings(self):
        services.save_settings(
            {
                "selected_ids": sorted(self.selected_ids),
                "model_id": self.model.get("model_id") if self.model else None,
                "window": self.window.currentData(),
                "model_name": self.model_name.text(),
                "round_id": self.round_id,
                "round_number": self.round_number,
                "behavior": self.behavior.currentText(),
                "prepare": self.prepare.value(),
                "seconds": self.seconds.value(),
                "custom_behaviors": list(self.custom_behaviors),
                "processing_profile": PROFILE,
            }
        )

    def set_busy(self, value):
        self.busy = value
        for w in (
            self.collect_box,
            self.table,
            self.window,
            self.model_name,
            self.import_button,
            self.connection_button,
        ):
            w.setEnabled(not value)
        self.capture_button.setEnabled(not value)
        self.train_button.setEnabled(
            not value
            and services.selection_state(
                self.selected_records(), self.window.currentData()
            )[0]
        )
        self.cancel_button.setEnabled(value and self.job is not None)
        self.to_recognition.setEnabled(not value and self.model_matches())
        self.delete_selected_button.setEnabled(
            not value and bool(self.selected_records())
        )
        self.render_recognition()

    def sync_behavior(self, *_):
        for b in self.categories:
            b.setChecked(b.text() == self.behavior.currentText())
        self.behavior.setToolTip(self.behavior.currentText())
        self.delete_behavior_button.setEnabled(
            not self.busy
            and self.behavior.currentText() in self.custom_behaviors
        )
        C.QTimer.singleShot(0, self.reveal_behavior)

    def reveal_behavior(self):
        chosen = next(
            (
                b
                for b in self.categories
                if b.text() == self.behavior.currentText()
            ),
            None,
        )
        if chosen is not None:
            self.category_scroll.ensureWidgetVisible(chosen)

    def rebuild_behaviors(self, selected):
        names = [*services.DEFAULT_BEHAVIORS, *self.custom_behaviors]
        blocker = C.QSignalBlocker(self.behavior)
        self.behavior.clear()
        self.behavior.addItems(names)
        self.behavior.setCurrentText(
            selected if selected in names else names[0]
        )
        del blocker
        while self.category_grid.count():
            widget = self.category_grid.takeAt(0).widget()
            widget.hide()
            widget.deleteLater()
        self.categories = []
        for i, name in enumerate(names):
            b = button(
                name,
                lambda checked=False, n=name: self.behavior.setCurrentText(n),
            )
            b.setObjectName("category")
            b.setStyleSheet("min-height:24px; padding:7px;")
            b.setFixedHeight(42)
            b.setSizePolicy(
                W.QSizePolicy.Policy.Ignored, W.QSizePolicy.Policy.Fixed
            )
            b.setToolTip(name)
            b.setCheckable(True)
            self.categories.append(b)
            self.category_grid.addWidget(b, i // 3, i % 3)
        # Keep signal/capture controls in reach even with many saved actions.
        self.category_scroll.setFixedHeight(
            min(92, ((len(names) + 2) // 3) * 50 - 8)
        )
        self.sync_behavior()

    def add_behavior(self, *_):
        if self.busy:
            return False
        try:
            name = services.behavior_name(self.new_behavior.text())
        except ValueError as exc:
            self.behavior_hint.setText(str(exc))
            self.new_behavior.setFocus()
            return False
        old_names, old_selection = (
            list(self.custom_behaviors),
            self.behavior.currentText(),
        )
        exists = name in (*services.DEFAULT_BEHAVIORS, *self.custom_behaviors)
        if not exists:
            self.custom_behaviors.append(name)
        self.rebuild_behaviors(name)
        try:
            self.save_settings()
        except OSError as exc:
            self.custom_behaviors = old_names
            self.rebuild_behaviors(old_selection)
            self.behavior_hint.setText(
                "저장하지 못했습니다. 입력한 이름은 남아 있습니다. 다시 저장하세요."
            )
            self.error(str(exc))
            return False
        self.new_behavior.clear()
        self.behavior_hint.setText(
            "이미 저장된 행동을 선택했습니다."
            if exists
            else "행동을 저장했습니다. 지금 선택한 행동으로 수집할 수 있습니다."
        )
        return True

    def remove_behavior(self, *_):
        name = self.behavior.currentText()
        if self.busy or name not in self.custom_behaviors:
            return False
        confirm = W.QMessageBox(self)
        confirm.setWindowTitle("행동 항목 삭제")
        confirm.setTextFormat(C.Qt.TextFormat.PlainText)
        confirm.setText(f"‘{name}’ 행동 항목을 삭제할까요?")
        confirm.setInformativeText(
            "수집 화면의 버튼과 목록에서 제거합니다.\n"
            "이 행동으로 수집한 기록과 학습 모델은 그대로 유지됩니다.\n"
            "같은 이름을 다시 저장하면 항목을 다시 추가할 수 있습니다."
        )
        delete = confirm.addButton(
            "행동 항목 삭제", W.QMessageBox.ButtonRole.AcceptRole
        )
        cancel = confirm.addButton("취소", W.QMessageBox.ButtonRole.RejectRole)
        confirm.setDefaultButton(cancel)
        confirm.setEscapeButton(cancel)
        confirm.exec()
        if (
            confirm.clickedButton() != delete
            or self.busy
            or name not in self.custom_behaviors
        ):
            return False
        old_names, old_selection = (
            list(self.custom_behaviors),
            self.behavior.currentText(),
        )
        self.custom_behaviors.remove(name)
        self.rebuild_behaviors(old_selection)
        try:
            self.save_settings()
        except OSError as exc:
            self.custom_behaviors = old_names
            self.rebuild_behaviors(old_selection)
            self.behavior_hint.setText(
                "삭제 내용을 저장하지 못했습니다. 기존 행동 항목을 유지했습니다."
            )
            self.error(str(exc))
            return False
        try:
            if services.behavior_name(self.new_behavior.text()) == name:
                self.new_behavior.clear()
        except ValueError:
            pass
        self.behavior_hint.setText(
            "행동 항목을 삭제했습니다. 기존 기록과 학습 모델은 그대로입니다."
        )
        return True

    def next_round(self):
        self.round_id, self.round_number = (
            uuid.uuid4().hex,
            self.round_number + 1,
        )
        self.round_label.setText(f"측정 {self.round_number}회차")
        self.save_settings()

    def open_connection(self):
        if not self.busy:
            ConnectionDialog(self).exec()

    def fresh_frames(self):
        with db.LOCK:
            status = db.LIVE.status()
            frames = list(db.LIVE.frames)
        if (
            not status["connected"]
            or not frames
            or db.LIVE.elapsed() - frames[-1]["t"] > 0.75
            or status.get("synchronizing")
        ):
            return []
        return frames

    def start_capture(self):
        if self.busy:
            return
        # A typed new label must not accidentally record under the prior selection.
        if self.new_behavior.text().strip() and not self.add_behavior():
            return
        frames = self.fresh_frames()
        if len(frames) < 4:
            self.capture_hint.setText(
                "먼저 보드 연결에서 USB와 송신·수신 상태를 확인하세요. 새 신호가 들어오면 시작할 수 있습니다."
            )
            self.open_connection()
            return
        self.stop_recognition(
            "신호를 수집하고 있습니다. 인식 결과는 표시하지 않습니다."
        )
        try:
            source = db.LIVE.snapshot()
            chip = db.LIVE.board_status().get("chip")
            if not chip:
                raise ValueError(
                    "보드 정보를 확인 중입니다. 보드 연결에서 USB를 다시 연결하세요."
                )
            hardware = services.hardware_for_chip(chip, db.LIVE.board_status())
            if not hardware:
                raise ValueError(
                    "수신용 보드를 연결하세요. C6는 WifiSensing C6 수신 펌웨어가 필요합니다."
                )
            context = {
                "mode": "live",
                "hardware": hardware,
                "dataset": "WifiSensing 2.0",
                "round_id": self.round_id,
                "note": self.note.text(),
            }
            self.job = teaching.TimedCapture(
                source,
                self.behavior.currentText(),
                self.seconds.value(),
                self.prepare.value(),
                db.LIVE.elapsed(),
                context,
            )
            self.set_busy(True)
            self.capture_progress.setValue(0)
            self.save_settings()
        except Exception as exc:
            self.capture_hint.setText(str(exc))

    def cancel_capture(self):
        if self.job:
            self.job.cancel()
            self.job = None
            self.set_busy(False)
            self.capture_status.setText("수집 취소")
            self.capture_hint.setText(
                "이번 구간은 학습 기록에 저장하지 않았습니다."
            )

    def advance_capture(self):
        job = self.job
        if not job:
            return
        with db.LOCK:
            frames = list(db.LIVE.frames)
        status, now = db.LIVE.status(), db.LIVE.elapsed()
        state = job.update(
            now,
            frames,
            status["connected"] and status["id"] == job.source["id"],
        )
        if state == "preparing":
            self.capture_status.setText(
                f"준비 {max(0, int(np.ceil(job.start - now)))}초"
            )
            self.capture_hint.setText(
                f"곧 {job.label} 동작을 {job.seconds:g}초 동안 기록합니다."
            )
        elif state == "recording":
            self.capture_status.setText(f"{job.label} 수집 중")
            self.capture_hint.setText(
                f"{now - job.start:.1f} / {job.seconds:g}초 · {len(job.frames):,}프레임"
            )
            self.capture_progress.setValue(
                int(min(1000, (now - job.start) / job.seconds * 1000))
            )
        elif state in ("complete", "failed"):
            self.job = None
            if state == "failed":
                self.set_busy(False)
                self.capture_status.setText("저장하지 못했어요")
                self.capture_hint.setText(job.error)
            else:
                self.cancel_button.setEnabled(False)
                self.capture_status.setText("기록 저장 중")
                self.background(
                    lambda: teaching.save_capture(job),
                    self.capture_saved,
                    self.capture_failed,
                )

    def capture_saved(self, record):
        self.set_busy(False)
        self.reload_records()
        self.capture_progress.setValue(1000)
        self.capture_status.setText(f"{record['label']} 저장 완료")
        self.capture_hint.setText(
            "다음 행동을 기록하거나, 2단계에서 학습할 기록에 체크하세요."
        )

    def capture_failed(self, message):
        self.set_busy(False)
        self.capture_status.setText("저장 실패")
        self.capture_hint.setText(message)

    def reload_records(self):
        self.records = sorted(
            db.saved_segments(),
            key=lambda r: r.get("created_at", ""),
            reverse=True,
        )
        self.selected_ids.intersection_update(r["id"] for r in self.records)
        counts = Counter(r["label"] for r in self.records)
        self.saved_count.setText(
            "저장된 기록 "
            + str(len(self.records))
            + "개 · "
            + ", ".join(f"{k} {v}개" for k, v in counts.items())
        )
        old = self.filter.currentData()
        self.filter.blockSignals(True)
        self.filter.clear()
        self.filter.addItem("모든 행동", None)
        for name in sorted(counts):
            self.filter.addItem(name, name)
        self.filter.setCurrentIndex(max(0, self.filter.findData(old)))
        self.filter.blockSignals(False)
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.records))
        groups = {
            g: i + 1
            for i, g in enumerate(
                dict.fromkeys(
                    r["experiment_id"] for r in reversed(self.records)
                )
            )
        }
        for i, r in enumerate(self.records):
            item = W.QTableWidgetItem("")
            item.setFlags(
                C.Qt.ItemFlag.ItemIsEnabled | C.Qt.ItemFlag.ItemIsUserCheckable
            )
            item.setCheckState(
                C.Qt.CheckState.Checked
                if r["id"] in self.selected_ids
                else C.Qt.CheckState.Unchecked
            )
            item.setData(C.Qt.ItemDataRole.UserRole, r["id"])
            self.table.setItem(i, 0, item)
            try:
                date = (
                    datetime.fromisoformat(r.get("created_at", ""))
                    .astimezone()
                    .strftime("%m/%d %H:%M:%S")
                )
            except ValueError:
                date = "가져온 기록"
            q = signal_quality(r["frames"], r["representation"])
            values = [
                r["label"],
                f"{r['frames'][-1]['t'] - r['frames'][0]['t']:.1f}초",
                date,
                f"{groups[r['experiment_id']]}회차",
                "통과" if q["transport_ok"] else "확인 필요",
            ]
            for j, value in enumerate(values, 1):
                self.table.setItem(i, j, W.QTableWidgetItem(value))
        self.table.blockSignals(False)
        self.filter_records()
        self.selection_changed()

    def filter_records(self, *_):
        label = self.filter.currentData()
        for i, r in enumerate(self.records):
            self.table.setRowHidden(
                i, label is not None and r["label"] != label
            )
        self.update_selection_summary()

    def selected_records(self):
        return [r for r in self.records if r["id"] in self.selected_ids]

    def item_changed(self, item):
        if item.column() != 0:
            return
        sid = item.data(C.Qt.ItemDataRole.UserRole)
        if item.checkState() == C.Qt.CheckState.Checked:
            self.selected_ids.add(sid)
        else:
            self.selected_ids.discard(sid)
        self.selection_changed()

    def select_visible(self):
        if self.busy:
            return
        self.table.blockSignals(True)
        for i, record in enumerate(self.records):
            if not self.table.isRowHidden(i):
                self.selected_ids.add(record["id"])
                self.table.item(i, 0).setCheckState(C.Qt.CheckState.Checked)
        self.table.blockSignals(False)
        self.selection_changed()

    def clear_selection(self):
        if self.busy:
            return
        self.selected_ids.clear()
        self.table.blockSignals(True)
        for i in range(self.table.rowCount()):
            self.table.item(i, 0).setCheckState(C.Qt.CheckState.Unchecked)
        self.table.blockSignals(False)
        self.selection_changed()

    def update_selection_summary(self):
        records = self.selected_records()
        counts = Counter(r["label"] for r in records)
        hidden = sum(
            r["id"] in self.selected_ids and self.table.isRowHidden(i)
            for i, r in enumerate(self.records)
        )
        self.selection_summary.setText(
            f"학습 대상 {len(records)}개 · "
            + (
                ", ".join(f"{k} {v}개" for k, v in counts.items())
                or "선택된 기록 없음"
            )
            + (
                f"\n현재 필터 밖의 선택 기록 {hidden}개도 포함됩니다."
                if hidden
                else ""
            )
        )
        self.delete_selected_button.setText(
            f"체크한 기록 삭제 ({len(records)})"
        )
        self.delete_selected_button.setEnabled(bool(records) and not self.busy)

    def delete_selected(self):
        if self.busy:
            return
        records = self.selected_records()
        if not records:
            return
        ids = {r["id"] for r in records}
        counts = Counter(r["label"] for r in records)
        hidden = sum(
            r["id"] in ids and self.table.isRowHidden(i)
            for i, r in enumerate(self.records)
        )
        confirm = W.QMessageBox(self)
        confirm.setWindowTitle("체크한 기록 일괄 삭제")
        confirm.setTextFormat(C.Qt.TextFormat.PlainText)
        confirm.setText(f"체크한 기록 {len(ids)}개를 휴지통으로 옮길까요?")
        confirm.setInformativeText(
            ", ".join(f"{label} {count}개" for label, count in counts.items())
            + (
                f"\n현재 필터 밖의 체크한 기록 {hidden}개도 삭제됩니다."
                if hidden
                else ""
            )
            + "\n삭제한 기록은 휴지통에서 복원할 수 있습니다.\n이 기록을 사용한 모델은 다시 학습해야 사용할 수 있습니다."
        )
        delete = confirm.addButton(
            f"{len(ids)}개 휴지통으로 이동",
            W.QMessageBox.ButtonRole.AcceptRole,
        )
        cancel = confirm.addButton("취소", W.QMessageBox.ButtonRole.RejectRole)
        confirm.setDefaultButton(cancel)
        confirm.setEscapeButton(cancel)
        confirm.exec()
        if confirm.clickedButton() != delete:
            return
        try:
            count = move_records(ids)
        except (OSError, ValueError) as exc:
            self.error(f"기록을 삭제하지 못했습니다.\n{exc}")
            return
        self.selected_ids.difference_update(ids)
        self.reload_records()
        self.statusBar().showMessage(
            f"체크한 기록 {count}개를 휴지통으로 옮겼습니다. [휴지통]에서 함께 선택해 복원할 수 있습니다."
        )

    def model_matches(self):
        return bool(
            self.model
            and self.model.get("feature_profile") == PROFILE
            and self.model.get("fingerprint")
            == teaching.fingerprint(
                self.selected_records(), self.window.currentData()
            )
        )

    def selection_changed(self, *_):
        self.reset_preview()
        self.update_selection_summary()
        ready, message = services.selection_state(
            self.selected_records(), self.window.currentData()
        )
        self.training_ready.setText(message)
        self.train_button.setEnabled(ready and not self.busy)
        if not self.model_matches():
            self.stop_recognition(
                "선택 기록 또는 판단 구간이 바뀌었습니다. 2단계에서 학습하세요."
                if self.model
                else "2단계에서 기록을 선택하고 모델을 학습하세요."
            )
        self.update_model()
        self.save_settings()

    def open_record(self, *_):
        if self.busy:
            return
        index = self.table.currentRow()
        if 0 <= index < len(self.records) and not self.table.isRowHidden(
            index
        ):
            RecordDialog(self, self.records[index]).exec()
        else:
            self.statusBar().showMessage("미리 볼 기록의 행을 클릭하세요.")

    def import_dialog(self):
        if self.busy:
            return
        files, _ = W.QFileDialog.getOpenFileNames(
            self,
            "기록 복사해서 가져오기 · 원본은 변경하지 않습니다",
            "",
            "라벨 기록 (*.json *.zip)",
        )
        if not files:
            return
        self.set_busy(True)

        def done(ids):
            self.set_busy(False)
            self.reload_records()
            self.statusBar().showMessage(
                f"{len(ids)}개 기록을 2.0 폴더로 복사했습니다. 학습할 기록에 체크하세요."
            )

        def fail(message):
            self.set_busy(False)
            self.error(message)

        self.background(lambda: services.import_records(files), done, fail)

    def export_dialog(self):
        records = self.selected_records()
        if not records:
            return self.error("내보낼 기록에 체크하세요.")
        path, _ = W.QFileDialog.getSaveFileName(
            self,
            "체크한 기록 내보내기",
            str(db.DATA / "선택한-기록.zip"),
            "ZIP (*.zip)",
        )
        if path:
            self.background(
                lambda: services.export_records(records, path),
                lambda _: self.statusBar().showMessage(
                    "선택 기록을 내보냈습니다."
                ),
            )

    def trash_dialog(self):
        if self.busy:
            return
        dialog = W.QDialog(self)
        dialog.setWindowTitle("2.0 휴지통 · 기록 복원")
        dialog.resize(640, 360)
        layout = W.QVBoxLayout(dialog)
        listing = W.QListWidget()
        listing.setSelectionMode(
            W.QAbstractItemView.SelectionMode.ExtendedSelection
        )
        records = trashed_records()
        for r in records:
            listing.addItem(
                f"{r['label']} · {r['frames'][-1]['t'] - r['frames'][0]['t']:.1f}초 · {r.get('created_at', '')}"
            )
        layout.addWidget(
            text(
                "삭제한 기록은 학습에서 제외됩니다. 선택한 기록을 복원할 수 있습니다.",
                "muted",
            )
        )
        layout.addWidget(listing)

        def restore():
            ids = [
                records[listing.row(item)]["id"]
                for item in listing.selectedItems()
            ]
            if ids:
                move_records(ids, restore=True)
                self.reload_records()
                dialog.accept()

        layout.addLayout(
            horizontal(
                button("선택 복원", restore, True),
                button("닫기", dialog.reject),
            )
        )
        dialog.exec()

    def start_training(self):
        if self.busy:
            return
        records, seconds, name = (
            self.selected_records(),
            self.window.currentData(),
            self.model_name.text(),
        )
        ready, reason = services.selection_state(records, seconds)
        if not ready:
            self.training_ready.setText(reason)
            return
        self.stop_recognition("새 모델을 학습하고 있습니다.")
        self.set_busy(True)
        self.train_progress.show()
        self.training_ready.setText(
            f"선택한 {len(records)}개 기록만 학습·평가 중입니다…"
        )
        self.background(
            lambda: services.train_selected(records, seconds, name),
            self.trained,
            self.train_failed,
        )

    def trained(self, result):
        self.model = result
        self.train_progress.hide()
        self.set_busy(False)
        self.training_ready.setText(
            "학습 완료 · 아래 버튼으로 실시간 인식을 시작해보세요."
        )
        self.recognition.stop("실시간 인식 시작을 눌러 새 신호를 확인하세요.")
        self.update_model()
        self.render_recognition()
        self.save_settings()

    def train_failed(self, message):
        self.train_progress.hide()
        self.set_busy(False)
        self.training_ready.setText("학습을 완료하지 못했습니다.\n" + message)

    def update_model(self):
        matches = self.model_matches()
        self.to_recognition.setEnabled(matches and not self.busy)
        self.evaluation_button.setEnabled(bool(self.model))
        if self.model:
            m = self.model
            prefix = (
                "사용 준비 완료"
                if matches
                else "선택 변경 · 다시 학습 필요"
                if m.get("feature_profile") == PROFILE
                else "이전 방식 모델 · 새 기록으로 학습하세요"
            )
            if matches and m["balanced_accuracy"] < 0.7:
                prefix = "평가 낮음 · 추가 수집 권장"
            details = (
                f"{m.get('name', '나의 모델')} · {m['window_seconds']}초 판단\n"
                + ", ".join(m["labels"])
                + f" · 기록 {m.get('record_count', len(m['segment_ids']))}개"
            )
            self.model_summary.setText(
                f"{prefix}\n{details}\n균형 정확도 {m['balanced_accuracy'] * 100:.0f}% · 평가 {m['test_windows']}구간"
            )
            self.active_model.setText(f"{prefix}  |  {details}")
        else:
            self.model_summary.setText(
                "학습을 완료하면 사용한 기록 수와 평가 결과가 표시됩니다."
            )
            self.active_model.setText(
                "모델 없음 · 2단계에서 학습할 기록을 선택하세요."
            )
        labels = self.model["labels"] if matches else []
        if list(self.score_bars) != labels:
            while self.score_rows.count():
                item = self.score_rows.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            self.score_bars = {}
            for label in labels:
                self.score_rows.addWidget(text(label, "section"))
                bar = W.QProgressBar()
                bar.setRange(0, 100)
                bar.setFixedHeight(26)
                bar.setValue(0)
                bar.setFormat("대기")
                self.score_rows.addWidget(bar)
                self.score_bars[label] = bar
        self.render_recognition()

    def show_evaluation(self):
        if not self.model:
            return
        m = self.model
        dialog = W.QDialog(self)
        dialog.setWindowTitle("모델 평가 · 학습에 사용한 기록")
        dialog.resize(820, 640)
        layout = W.QVBoxLayout(dialog)
        layout.addWidget(text(m.get("name", "모델 평가"), "title"))
        layout.addWidget(
            text(
                f"균형 정확도 {m['balanced_accuracy'] * 100:.1f}% · 학습 {m['train_windows']} / 검증 {m.get('validation_windows', 0)} / 최종 평가 {m['test_windows']}구간\n검증으로 선택한 학습 단계 {m.get('best_epoch', '—')} · 수신 불량 제외 {m.get('discarded_windows', 0)}구간\n새 동작·사람·공간에서는 별도로 확인하세요.",
                "notice",
            )
        )
        layout.addWidget(
            text(
                "학습에 넣지 않은 측정 회차로 평가합니다. 행동별 정답률을 같은 비중으로 평균한 값이 균형 정확도입니다.\n학습 완료 때 계산하여 저장하며, 실시간 행동 점수와는 별개입니다.",
                "muted",
            )
        )
        table = W.QTableWidget(len(m["labels"]), len(m["labels"]) + 1)
        table.setHorizontalHeaderLabels(
            ["예측 " + name for name in m["labels"]] + ["행동별 정답률"]
        )
        table.setVerticalHeaderLabels(["실제 " + name for name in m["labels"]])
        table.setEditTriggers(W.QAbstractItemView.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(
            W.QHeaderView.ResizeMode.Stretch
        )
        for i, values in enumerate(m["confusion_matrix"]):
            for j, v in enumerate(values):
                table.setItem(i, j, W.QTableWidgetItem(str(v)))
            total = sum(values)
            recall = (
                f"{values[i]} / {total} = {values[i] / total * 100:.1f}%"
                if total
                else "평가 구간 없음"
            )
            table.setItem(i, len(m["labels"]), W.QTableWidgetItem(recall))
        table.horizontalHeader().setSectionResizeMode(
            len(m["labels"]), W.QHeaderView.ResizeMode.ResizeToContents
        )
        layout.addWidget(table)
        listing = W.QListWidget()
        for r in m.get("training_records", []):
            listing.addItem(f"{r['label']} · {r['name']} · {r['id'][:8]}")
        layout.addWidget(text("이 모델을 만드는 데 선택한 기록", "section"))
        layout.addWidget(listing)
        layout.addWidget(button("닫기", dialog.accept))
        dialog.exec()

    def toggle_recognition(self):
        if self.recognition.running:
            self.stop_recognition()
            return
        if self.busy or not self.model_matches():
            self.recognition.stop("2단계에서 현재 선택한 기록으로 학습하세요.")
        elif self.model["representation"] != "raw_iq_52":
            self.recognition.stop(
                "이 모델은 가져온 전처리 기록용입니다. 실측 원본 기록으로 학습하세요."
            )
        else:
            frames = self.fresh_frames()
            if not frames:
                self.recognition.stop(
                    "새 신호가 없습니다. 상단 보드 연결을 확인하세요."
                )
            else:
                chip = db.LIVE.board_status().get("chip")
                hardware = services.hardware_for_chip(
                    chip, db.LIVE.board_status()
                )
                if (
                    self.model.get("collection", {}).get("hardware")
                    != hardware
                ):
                    self.recognition.stop(
                        "현재 보드와 모델의 장치 구성이 다릅니다. 같은 장치의 기록으로 학습하세요."
                    )
                else:
                    self.recognition.begin(
                        db.LIVE.sid,
                        frames[-1].get("stream_epoch", 0),
                        self.model["model_id"],
                        db.LIVE.elapsed(),
                    )
                    self.last_predict = 0
        self.render_recognition()

    def stop_recognition(
        self,
        reason="인식이 중지되었습니다. 다시 시작하면 새 신호로 판단합니다.",
    ):
        self.recognition.stop(reason)
        if hasattr(self, "current_action"):
            self.render_recognition()

    def render_recognition(self):
        state = self.recognition
        self.inference_button.setText(
            "인식 중지" if state.running else "실시간 인식 시작"
        )
        self.inference_button.setEnabled(
            state.running
            or (bool(self.model) and self.model_matches() and not self.busy)
        )
        self.inference_badge.setText(
            "실시간 인식 중"
            if state.running and state.result
            else "신호 준비 중"
            if state.running
            else "인식 꺼짐"
        )
        if state.result:
            waveform = state.result["input_signal"]
            self.live_line.setData(
                np.asarray(waveform["time"]) - state.input_end,
                waveform["signal"],
            )
            self.set_aux(
                self.live_aux_lines,
                np.asarray(waveform["time"]) - state.input_end,
                waveform.get("components"),
            )
            self.current_action.setText(state.result["label"])
            self.current_action.setStyleSheet(
                "color:#9b6b10;"
                if state.result["label"] == "판단 보류"
                else "color:#147b68;"
            )
            self.inference_reason.setText(
                state.result.get("reason")
                or f"최근 {self.model['window_seconds']}초의 전처리 3성분을 분석했습니다."
            )
            self.freshness.setText(
                f"결과 갱신 {max(0, db.LIVE.elapsed() - state.updated_at):.1f}초 전 · 입력이 끊기면 결과를 지웁니다."
            )
            for label, bar in self.score_bars.items():
                bar.setValue(round(state.result["scores"].get(label, 0) * 100))
                bar.setFormat("%p%")
        else:
            self.live_line.clear()
            self.set_aux(self.live_aux_lines, [], None)
            self.current_action.setText(
                "신호 대기" if state.running else "인식 대기"
            )
            self.current_action.setStyleSheet("color:#708292;")
            self.inference_reason.setText(state.reason)
            self.freshness.setText("현재 행동을 판단한 최신 결과가 없습니다.")
            for bar in self.score_bars.values():
                bar.setValue(0)
                bar.setFormat("대기")

    def advance_recognition(self, frames):
        state = self.recognition
        now, status = db.LIVE.elapsed(), db.LIVE.status()
        epoch = frames[-1].get("stream_epoch", 0) if frames else state.epoch
        if not state.observe(
            status["connected"],
            status["id"],
            epoch,
            frames[-1]["t"] if frames else None,
            now,
        ):
            self.render_recognition()
            return
        recent = [
            f
            for f in frames
            if f["t"] >= state.start
            and frames[-1]["t"] - f["t"] <= self.model["window_seconds"] + 0.1
        ]
        if (
            not recent
            or recent[-1]["t"] - recent[0]["t"]
            < self.model["window_seconds"] - 0.025
        ):
            state.clear(
                f"새 신호 {self.model['window_seconds']}초를 모으고 있습니다."
            )
        elif (
            not self.predicting
            and time.perf_counter() - self.last_predict >= 0.6
        ):
            self.predicting = True
            self.last_predict = time.perf_counter()
            model, generation, end = (
                self.model,
                state.generation,
                recent[-1]["t"],
            )

            def done(result):
                self.predicting = False
                state.accept(
                    generation,
                    model["model_id"],
                    result,
                    end,
                    db.LIVE.elapsed(),
                )
                self.render_recognition()

            def fail(message):
                self.predicting = False
                if state.running and state.generation == generation:
                    state.clear(message)
                    self.render_recognition()

            self.background(
                lambda: teaching.predict_frames(model, recent, "raw_iq_52"),
                done,
                fail,
            )
        self.render_recognition()

    def reset_preview(self, *_):
        self.preview_generation += 1
        if hasattr(self, "capture_line"):
            self.capture_line.clear()
            self.set_aux(self.capture_aux_lines, [], None)

    def preview_options(self):
        return {
            key: check.isChecked()
            for key, check in self.capture_stages.items()
        } | {"subcarrier": self.preview_subcarrier}

    def preview_channel_changed(self, *_):
        channel = self.channel.currentData()
        if channel is not None:
            self.preview_subcarrier = channel
        with C.QSignalBlocker(self.capture_stages["pca"]):
            self.capture_stages["pca"].setChecked(channel is None)
        self.preview_controls_changed()

    def preview_controls_changed(self, *_):
        with C.QSignalBlocker(self.channel):
            self.channel.setCurrentIndex(
                0
                if self.capture_stages["pca"].isChecked()
                else self.channel.findData(self.preview_subcarrier)
            )
        self.reset_preview()
        self.preview_autoscale = True
        self.last_plot = 0.0
        self.update_preview(self.fresh_frames())

    @staticmethod
    def set_aux(lines, times, components):
        matrix = (
            np.asarray(components)
            if components is not None
            else np.empty((0, 1))
        )
        for i, line in enumerate(lines, 1):
            if matrix.ndim == 2 and matrix.shape[1] > i:
                line.setData(times, matrix[:, i])
            else:
                line.clear()

    def export_edge(self):
        if not self.model or not self.model_matches():
            return self.error("현재 선택한 기록으로 모델을 먼저 학습하세요.")
        path, _ = W.QFileDialog.getSaveFileName(
            self, "라즈베리파이 실행 묶음", "WifiSensing-Pi.zip", "ZIP (*.zip)"
        )
        if path:
            try:
                from edge_export import export_bundle

                export_bundle(self.model, path)
                self.statusBar().showMessage(
                    "모델·수집·추론 프로그램과 설명서를 내보냈습니다.", 8000
                )
            except Exception as exc:
                self.error(str(exc))

    def show_preview(self, times, values, title, raw=False, components=None):
        self.capture_line.setData(times, values)
        self.set_aux(self.capture_aux_lines, times, components)
        self.capture_plot.setTitle(title, color="#60778a", size="10pt")
        self.capture_plot.setLabel("left", "원본 진폭" if raw else "상대값")
        if self.preview_autoscale:
            # Stage changes also change units. Fit once even when the user
            # locks the axis, then retain that range for the live comparison.
            self.capture_plot.getViewBox().autoRange(
                items=[self.capture_line] + self.capture_aux_lines,
                padding=0.08,
            )
            self.preview_autoscale = False

    def update_preview(self, frames):
        seconds = self.window.currentData()
        if not frames:
            self.reset_preview()
            self.capture_plot.setTitle(
                "새 신호 대기 · 최종 전처리 파형", color="#60778a", size="10pt"
            )
            return
        end = frames[-1]["t"]
        options = self.preview_options()
        stages = {k: options[k] for k in self.capture_stages}
        if not any(stages.values()):
            recent = [f for f in frames if end - f["t"] <= seconds]
            self.show_preview(
                [f["t"] - end for f in recent],
                [f["amp"][options["subcarrier"]] for f in recent],
                f"실시간 원본 · 채널 {SUBCARRIERS[options['subcarrier']]} · 전처리 모두 꺼짐",
                raw=True,
            )
            return
        recent = [f for f in frames if end - f["t"] <= seconds + 0.05]
        if recent[-1]["t"] - recent[0]["t"] < seconds - 0.025:
            self.reset_preview()
            self.capture_plot.setTitle(
                f"실시간 전처리를 위해 {seconds}초 신호 수집 중",
                color="#60778a",
                size="10pt",
            )
            return
        if self.previewing:
            return
        self.previewing = True
        generation, sid = self.preview_generation, db.LIVE.sid
        epoch = recent[-1].get("stream_epoch", 0)

        def valid():
            current = self.fresh_frames()
            return (
                generation == self.preview_generation
                and self.preview_options() == options
                and self.window.currentData() == seconds
                and db.LIVE.sid == sid
                and current
                and current[-1].get("stream_epoch", 0) == epoch
                and db.LIVE.elapsed() - end <= 0.75
            )

        def done(result):
            self.previewing = False
            if valid():
                title = (
                    f"실시간 최종 전처리 · 최근 {seconds}초 · 학습과 같은 처리"
                    if all(stages.values())
                    else "실시간 단계 비교 · "
                    + " → ".join(
                        self.capture_stages[k].text()
                        for k, enabled in stages.items()
                        if enabled
                    )
                )
                self.show_preview(
                    np.asarray(result["time"]) - end,
                    result["signal"],
                    title,
                    components=result["components"],
                )
            elif generation != self.preview_generation:
                # Rapid clicks invalidate a pending result. Recompute the
                # latest settings immediately without waiting another window.
                self.update_preview(self.fresh_frames())

        def fail(message):
            self.previewing = False
            if valid():
                self.capture_line.clear()
                self.set_aux(self.capture_aux_lines, [], None)
                self.capture_plot.setTitle(
                    message, color="#9b6b10", size="10pt"
                )
            elif generation != self.preview_generation:
                self.update_preview(self.fresh_frames())

        self.background(
            lambda: latest_signal(recent, "raw_iq_52", seconds, options),
            done,
            fail,
        )

    def tick(self):
        frames = self.fresh_frames()
        status = db.LIVE.status()
        self.connection_status.setText(
            "신호 수신 중"
            if frames
            else "USB 연결 · 신호 대기"
            if status["connected"]
            else "보드 미연결"
        )
        self.connection_button.setText(
            "연결 설정" if status["connected"] else "보드 연결"
        )
        self.advance_capture()
        if self.recognition.running:
            self.advance_recognition(frames)
        now = time.perf_counter()
        if now - self.last_plot < 0.3:
            return
        self.last_plot = now
        self.update_preview(frames)
        self.capture_plot.enableAutoRange(
            axis="y", enable=not self.axis_lock.isChecked()
        )
        if frames:
            recent = [f for f in frames if frames[-1]["t"] - f["t"] <= 8]
            span = recent[-1]["t"] - recent[0]["t"]
            self.signal_status.setText(
                f"{status['port']} · 평균 {(len(recent) - 1) / max(span, 0.001):.1f} Hz · RSSI {recent[-1].get('rssi', '?')} dBm · 위 버튼으로 실시간 전처리를 비교하세요."
            )
        else:
            self.signal_status.setText(
                "시간 확인 중 · 재접속 버퍼 정리가 끝나면 표시합니다."
                if status.get("warmup_frames") and status.get("synchronizing")
                else "새 CSI 신호가 없습니다. 연결 설정에서 송신·수신 상태를 확인하세요."
            )

    def signal_details(self):
        frames = self.fresh_frames()
        seconds = self.window.currentData()
        if len(frames) < 4:
            return self.error("신호 수신 중에 열 수 있습니다.")
        frames = [
            f for f in frames if frames[-1]["t"] - f["t"] <= seconds + 0.05
        ]
        try:
            result = inspect_signal(frames, "raw_iq_52", {"seconds": seconds})
        except ValueError as exc:
            return self.error(str(exc))
        dialog = W.QDialog(self)
        dialog.setWindowTitle("전처리 단계 비교 · 열었을 때의 신호")
        dialog.resize(900, 700)
        layout = W.QVBoxLayout(dialog)
        layout.addWidget(
            text(f"최근 {seconds}초의 전처리를 비교합니다", "title")
        )
        layout.addWidget(
            text(
                "모두 켜면 학습·실시간 인식에 사용하는 최종 신호입니다. 모두 끄면 원본 진폭입니다.",
                "notice",
            )
        )
        stages = stage_controls(layout)
        heat = plot("50채널 원본 진폭", 170)
        image = pg.ImageItem(axisOrder="row-major")
        image.setImage(np.asarray(result["heatmap"]).T)
        image.setLookupTable(pg.colormap.get("viridis").getLookupTable())
        image.setRect(
            C.QRectF(
                result["heat_time"][0],
                0,
                result["heat_time"][-1] - result["heat_time"][0],
                50,
            )
        )
        heat.addItem(image)
        heat.setLabel("left", "채널 순서")
        layout.addWidget(heat)
        processed = plot("최종 전처리 신호 · 학습 입력", 150)
        processed.setLabel("left", "상대값")
        line = processed.plot(
            result["time"],
            result["processed"],
            pen=pg.mkPen("#db9852", width=2),
        )
        line.setPen(pg.mkPen("#168971", width=1.6))
        extra = [
            processed.plot(pen=pg.mkPen(c, width=1.3))
            for c in ("#238bb4", "#db9852")
        ]
        self.set_aux(extra, result["time"], result["components"])
        layout.addWidget(processed)

        def redraw():
            options = {key: check.isChecked() for key, check in stages.items()}
            options["seconds"] = seconds
            options["subcarrier"] = self.channel.currentData() or 0
            viewed = inspect_signal(frames, "raw_iq_52", options)
            line.setData(viewed["time"], viewed["processed"])
            self.set_aux(extra, viewed["time"], viewed["components"])
            title = (
                "최종 전처리 신호 · 학습 입력"
                if all(c.isChecked() for c in stages.values())
                else "단계 비교 · 학습에는 모든 단계 적용"
                if any(c.isChecked() for c in stages.values())
                else "원본 진폭 · 전처리 모두 꺼짐"
            )
            processed.setTitle(title, color="#60778a", size="10pt")

        for check in stages.values():
            check.toggled.connect(redraw)
        layout.addWidget(
            text(
                "초록 PC1 · 파랑 PC2 · 주황 PC3. 학습에는 항상 세 단계와 3개 성분을 모두 사용합니다.",
                "muted",
            )
        )
        layout.addWidget(button("닫기", dialog.accept))
        dialog.exec()

    def closeEvent(self, event):
        if self.busy:
            self.statusBar().showMessage(
                "수집은 취소하거나 완료한 뒤, 학습은 완료한 뒤 종료하세요."
            )
            event.ignore()
            return
        self.timer.stop()
        self.stop_recognition()
        self.pool.waitForDone(10000)
        self.save_settings()
        db.LIVE.disconnect()
        event.accept()


def main():
    multiprocessing.freeze_support()
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test")
    parser.add_argument("--flash-c6")
    parser.add_argument("--role")
    parser.add_argument("--backup")
    parser.add_argument("--flash-log")
    args = parser.parse_args()
    if args.flash_c6:
        from flash_c6 import worker

        return worker(args.flash_c6, args.role, args.backup, args.flash_log)
    application = W.QApplication(sys.argv[:1])
    application.setApplicationName("WifiSensing2.0")
    application.setOrganizationName("WifiSensing2")
    application.setStyle("Fusion")
    application.setStyleSheet(STYLE)
    application.setFont(G.QFont("Malgun Gothic", 10))
    pg.setConfigOptions(
        antialias=True, foreground="#65798a", background="white"
    )
    if args.self_test:
        import selftest
        import traceback

        try:
            report = selftest.run(
                application, Path(args.self_test).parent / "screenshots"
            )
        except Exception:
            Path(args.self_test).write_text(
                traceback.format_exc(), encoding="utf-8"
            )
            return 1
        Path(args.self_test).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return 0
    lock = C.QLockFile(str(db.DATA / "app-v2.lock"))
    if not lock.tryLock(100):
        W.QMessageBox.information(
            None,
            "WifiSensing 2.0",
            "2.0이 이미 실행 중입니다. 작업 표시줄에서 창을 여세요.",
        )
        return 0
    window = MainWindow()
    window.show()
    return application.exec()


if __name__ == "__main__":
    sys.exit(main())
