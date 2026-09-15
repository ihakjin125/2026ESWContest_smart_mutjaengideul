import paho.mqtt.client as mqtt

from core.device_control_message import DeviceControlMessage
from device_control_publisher import DeviceControlPublisher


class FakePublishResult:
    def __init__(self, rc):
        self.rc = rc


class FakeMqttClient:
    def __init__(self):
        self.calls = []
        self.next_rc = mqtt.MQTT_ERR_SUCCESS

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

        return FakePublishResult(self.next_rc)


fake_client = FakeMqttClient()
publisher = DeviceControlPublisher(fake_client)


# 1. 에어컨 ON 메시지 publish
message_on = DeviceControlMessage(
    topic="safehub/control/livingroom/aircon/command",
    payload=(
        '{"source":"sign_shortcut",'
        '"action":"set_power",'
        '"power_on":true}'
    ),
)

publisher.publish(message_on)

assert len(fake_client.calls) == 1

first_call = fake_client.calls[0]

assert (
    first_call["topic"]
    == "safehub/control/livingroom/aircon/command"
)
assert first_call["payload"] == message_on.payload
assert first_call["qos"] == 1
assert first_call["retain"] is False

print("PASS | 01 device control MQTT publish")


# 2. OFF 메시지도 동일한 토픽으로 publish
message_off = DeviceControlMessage(
    topic="safehub/control/livingroom/aircon/command",
    payload=(
        '{"source":"sign_shortcut",'
        '"action":"set_power",'
        '"power_on":false}'
    ),
)

publisher.publish(message_off)

assert len(fake_client.calls) == 2

second_call = fake_client.calls[1]

assert second_call["topic"] == message_off.topic
assert second_call["payload"] == message_off.payload
assert second_call["qos"] == 1
assert second_call["retain"] is False

print("PASS | 02 OFF command MQTT publish")


# 3. MQTT publish 실패 감지
fake_client.next_rc = mqtt.MQTT_ERR_NO_CONN

failed_message = DeviceControlMessage(
    topic="safehub/control/livingroom/aircon/command",
    payload=(
        '{"source":"sign_shortcut",'
        '"action":"set_power",'
        '"power_on":true}'
    ),
)

try:
    publisher.publish(failed_message)

    raise AssertionError(
        "MQTT publish 실패가 감지되지 않았습니다."
    )

except RuntimeError:
    pass

print("PASS | 03 MQTT publish failure detected")


print()
print("PASS | DeviceControlPublisher all tests passed")