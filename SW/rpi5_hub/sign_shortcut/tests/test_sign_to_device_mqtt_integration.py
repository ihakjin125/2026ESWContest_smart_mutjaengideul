import json

import paho.mqtt.client as mqtt

from core.action_executor import ActionExecutor
from core.device_control_message import build_device_control_message
from core.shortcut_manager import ShortcutManager
from device_control_publisher import DeviceControlPublisher


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


# 1. 사용자가 수어 단축키를 등록했다고 가정
shortcut_manager.register(
    sign="에어컨",
    room="livingroom",
    device="aircon",
    action="toggle",
)

print("PASS | 01 sign shortcut registered")


# 2. 수어 인식 결과 "에어컨" 수신
recognized_sign = "에어컨"

shortcut = shortcut_manager.find_by_sign(recognized_sign)

assert shortcut is not None

print("PASS | 02 recognized sign resolved")


# 3. 등록된 동작 실행: OFF -> ON
result_on = action_executor.execute(shortcut)

assert result_on.success is True
assert result_on.power_on is True

print("PASS | 03 shortcut action OFF -> ON")


# 4. ActionResult를 Device Control MQTT 메시지로 변환
message_on = build_device_control_message(result_on)

assert (
    message_on.topic
    == "safehub/control/livingroom/aircon/command"
)

payload_on = json.loads(message_on.payload)

assert payload_on == {
    "source": "sign_shortcut",
    "action": "set_power",
    "power_on": True,
}

print("PASS | 04 ON device control message built")


# 5. MQTT publish
publisher.publish(message_on)

assert len(fake_client.calls) == 1

first_publish = fake_client.calls[0]

assert (
    first_publish["topic"]
    == "safehub/control/livingroom/aircon/command"
)
assert json.loads(first_publish["payload"])["power_on"] is True
assert first_publish["qos"] == 1
assert first_publish["retain"] is False

print("PASS | 05 ON command published")


# 6. 같은 수어가 다시 인식되면 ON -> OFF
shortcut_again = shortcut_manager.find_by_sign("에어컨")

assert shortcut_again is not None

result_off = action_executor.execute(shortcut_again)

assert result_off.success is True
assert result_off.power_on is False

message_off = build_device_control_message(result_off)
publisher.publish(message_off)

assert len(fake_client.calls) == 2

second_publish = fake_client.calls[1]

assert json.loads(second_publish["payload"]) == {
    "source": "sign_shortcut",
    "action": "set_power",
    "power_on": False,
}

print("PASS | 06 repeated sign publishes OFF command")


# 7. 등록되지 않은 수어는 MQTT 명령을 만들지 않음
before_count = len(fake_client.calls)

unknown_shortcut = shortcut_manager.find_by_sign("감사")

assert unknown_shortcut is None
assert len(fake_client.calls) == before_count

print("PASS | 07 unregistered sign publishes nothing")


print()
print("PASS | Sign -> Device MQTT integration all tests passed")