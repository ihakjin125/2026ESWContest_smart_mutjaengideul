from unittest.mock import patch

import paho.mqtt.client as mqtt

from sign_shortcut.core.action_executor import ActionExecutor
from sign_shortcut.core.shortcut_manager import ShortcutManager
from sign_shortcut.core.sign_shortcut_controller import SignShortcutController
from sign_shortcut.device_control_publisher import DeviceControlPublisher


class FakePublishResult:
    def __init__(self, rc):
        self.rc = rc


class FakeMqttClient:
    def __init__(self):
        self.calls = []

    def publish(
        self,
        topic,
        payload,
        qos,
        retain,
    ):
        self.calls.append(
            {
                "topic": topic,
                "payload": payload,
                "qos": qos,
                "retain": retain,
            }
        )

        return FakePublishResult(mqtt.MQTT_ERR_SUCCESS)


shortcut_manager = ShortcutManager()
action_executor = ActionExecutor()
fake_client = FakeMqttClient()
publisher = DeviceControlPublisher(fake_client)

controller = SignShortcutController(
    shortcut_manager=shortcut_manager,
    action_executor=action_executor,
    publisher=publisher,
    cooldown_sec=2.5,
)

shortcut_manager.register(
    sign="에어컨",
    room="livingroom",
    device="aircon",
    action="toggle",
)


# monotonic 시간을 직접 제어해서 실제 대기 없이 cooldown 검증
with patch(
    "sign_shortcut.core.sign_shortcut_controller.time.monotonic",
    side_effect=[
        100.0,
        100.1,
        100.2,
        102.5,
    ],
):
    # 1. 첫 인식은 정상 실행
    first_result = controller.handle_sign("에어컨")

    assert first_result is not None
    assert first_result.success is True
    assert first_result.power_on is True
    assert len(fake_client.calls) == 1

    print("PASS | 01 first sign executes")


    # 2. 0.1초 뒤 동일 수어 -> cooldown으로 무시
    second_result = controller.handle_sign("에어컨")

    assert second_result is None
    assert len(fake_client.calls) == 1
    assert action_executor.livingroom_aircon_power_on is True

    print("PASS | 02 rapid duplicate ignored")


    # 3. 0.2초 뒤 동일 수어 -> 역시 무시
    third_result = controller.handle_sign("에어컨")

    assert third_result is None
    assert len(fake_client.calls) == 1
    assert action_executor.livingroom_aircon_power_on is True

    print("PASS | 03 three rapid signs produce one command")


    # 4. 정확히 2.5초가 지나면 다시 실행 가능
    after_cooldown_result = controller.handle_sign("에어컨")

    assert after_cooldown_result is not None
    assert after_cooldown_result.success is True
    assert after_cooldown_result.power_on is False
    assert len(fake_client.calls) == 2
    assert action_executor.livingroom_aircon_power_on is False

    print("PASS | 04 sign executes after cooldown")


# 5. 음수 cooldown은 설정할 수 없음
try:
    SignShortcutController(
        shortcut_manager=ShortcutManager(),
        action_executor=ActionExecutor(),
        publisher=publisher,
        cooldown_sec=-1.0,
    )

    raise AssertionError("음수 cooldown이 허용되었습니다.")

except ValueError:
    pass

print("PASS | 05 negative cooldown rejected")


print()
print("PASS | SignShortcutController cooldown all tests passed")