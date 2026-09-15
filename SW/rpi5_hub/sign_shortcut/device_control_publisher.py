import paho.mqtt.client as mqtt

from core.device_control_message import DeviceControlMessage


class DeviceControlPublisher:
    def __init__(self, client: mqtt.Client):
        self._client = client

    def publish(self, message: DeviceControlMessage) -> None:
        result = self._client.publish(
            topic=message.topic,
            payload=message.payload,
            qos=1,
            retain=False,
        )

        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            raise RuntimeError(
                f"기기 제어 MQTT publish 실패: rc={result.rc}"
            )