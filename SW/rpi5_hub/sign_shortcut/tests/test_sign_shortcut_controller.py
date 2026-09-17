import json

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
)


# 1. 사용할 수어 단축키 등록
shortcut_manager.register(
    sign="에어컨",
    room="livingroom",
    device="aircon",
    action="toggle",
)

print("PASS | 01 shortcut registered")


# 2. 에어컨 수어 처리: OFF -> ON
result_on = controller.handle_sign("에어컨")

assert result_on is not None
assert result_on.success is True
assert result_on.power_on is True

assert len(fake_client.calls) == 1

first_publish = fake_client.calls[0]

assert (
    first_publish["topic"]
    == "safehub/control/livingroom/aircon/command"
)

assert json.loads(first_publish["payload"]) == {
    "source": "sign_shortcut",
    "action": "set_power",
    "power_on": True,
}

assert first_publish["qos"] == 1
assert first_publish["retain"] is False

print("PASS | 02 sign controller OFF -> ON publish")


# 3. 같은 수어를 다시 처리: ON -> OFF
result_off = controller.handle_sign("에어컨")

assert result_off is not None
assert result_off.success is True
assert result_off.power_on is False

assert len(fake_client.calls) == 2

second_publish = fake_client.calls[1]

assert json.loads(second_publish["payload"]) == {
    "source": "sign_shortcut",
    "action": "set_power",
    "power_on": False,
}

print("PASS | 03 repeated sign ON -> OFF publish")


# 4. 등록되지 않은 수어는 아무것도 실행하지 않음
before_count = len(fake_client.calls)

unknown_result = controller.handle_sign("감사")

assert unknown_result is None
assert len(fake_client.calls) == before_count
assert action_executor.livingroom_aircon_power_on is False

print("PASS | 04 unregistered sign ignored")


# 5. 빈 문자열도 아무것도 실행하지 않음
before_count = len(fake_client.calls)

empty_result = controller.handle_sign("   ")

assert empty_result is None
assert len(fake_client.calls) == before_count

print("PASS | 05 empty sign ignored")


# 6. 등록은 되어 있지만 아직 지원하지 않는 동작
shortcut_manager.register(
    sign="덥다",
    room="livingroom",
    device="aircon",
    action="temperature_down",
)

before_count = len(fake_client.calls)

unsupported_result = controller.handle_sign("덥다")

assert unsupported_result is not None
assert unsupported_result.success is False
assert len(fake_client.calls) == before_count

print("PASS | 06 unsupported action publishes nothing")


print()
print("PASS | SignShortcutController all tests passed")