from core.action_executor import ActionResult, ActionExecutor
from core.device_control_message import build_device_control_message
from core.shortcut_manager import ShortcutManager
from device_control_publisher import DeviceControlPublisher


class SignShortcutController:
    def __init__(
        self,
        shortcut_manager: ShortcutManager,
        action_executor: ActionExecutor,
        publisher: DeviceControlPublisher,
    ):
        self._shortcut_manager = shortcut_manager
        self._action_executor = action_executor
        self._publisher = publisher

    def handle_sign(self, sign: str) -> ActionResult | None:
        clean_sign = sign.strip()

        if not clean_sign:
            return None

        # 인식된 수어에 등록된 단축키가 있는지 조회
        shortcut = self._shortcut_manager.find_by_sign(clean_sign)

        if shortcut is None:
            return None

        # 등록된 기기 동작 실행
        result = self._action_executor.execute(shortcut)

        if not result.success:
            return result

        # 실행 결과를 실제 기기 제어 MQTT 메시지로 변환
        message = build_device_control_message(result)

        # MQTT publish
        self._publisher.publish(message)

        return result