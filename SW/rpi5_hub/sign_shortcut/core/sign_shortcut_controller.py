import time

from .action_executor import ActionResult, ActionExecutor
from .device_control_message import build_device_control_message
from .shortcut_manager import ShortcutManager
from ..device_control_publisher import DeviceControlPublisher


class SignShortcutController:
    def __init__(
        self,
        shortcut_manager: ShortcutManager,
        action_executor: ActionExecutor,
        publisher: DeviceControlPublisher,
        cooldown_sec: float = 0.0,
    ):
        if cooldown_sec < 0:
            raise ValueError(
                "수어 단축키 cooldown은 0 이상이어야 합니다."
            )

        self._shortcut_manager = shortcut_manager
        self._action_executor = action_executor
        self._publisher = publisher
        self._cooldown_sec = cooldown_sec
        self._last_executed_at: dict[str, float] = {}

    def handle_sign(self, sign: str) -> ActionResult | None:
        clean_sign = sign.strip()

        if not clean_sign:
            return None

        # 인식된 수어에 등록된 단축키가 있는지 조회
        shortcut = self._shortcut_manager.find_by_sign(clean_sign)

        if shortcut is None:
            return None

        # 같은 수어가 짧은 시간 안에 반복 인식되면 무시
        now = time.monotonic()
        last_executed_at = self._last_executed_at.get(clean_sign)

        if (
            last_executed_at is not None
            and now - last_executed_at < self._cooldown_sec
        ):
            return None

        # 등록된 기기 동작 실행
        result = self._action_executor.execute(shortcut)

        if not result.success:
            return result

        # 실행 결과를 실제 기기 제어 MQTT 메시지로 변환
        message = build_device_control_message(result)

        # MQTT publish
        self._publisher.publish(message)

        # 실제 실행 및 publish에 성공한 경우에만
        # 마지막 실행 시간을 기록
        self._last_executed_at[clean_sign] = now

        return result