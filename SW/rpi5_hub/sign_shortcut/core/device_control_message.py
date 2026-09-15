import json
from dataclasses import dataclass

from core.action_executor import ActionResult


@dataclass(frozen=True)
class DeviceControlMessage:
    topic: str
    payload: str


def build_device_control_message(
    result: ActionResult,
    source: str = "sign_shortcut",
) -> DeviceControlMessage:
    if not result.success:
        raise ValueError(
            "실패한 ActionResult로 기기 제어 메시지를 만들 수 없습니다."
        )

    if result.power_on is None:
        raise ValueError(
            "전원 상태가 없는 ActionResult는 아직 MQTT 제어를 지원하지 않습니다."
        )

    room = result.room.strip()
    device = result.device.strip()
    clean_source = source.strip()

    if not room:
        raise ValueError("공간은 비어 있을 수 없습니다.")

    if not device:
        raise ValueError("기기는 비어 있을 수 없습니다.")

    if not clean_source:
        raise ValueError("제어 요청 출처는 비어 있을 수 없습니다.")

    topic = f"safehub/control/{room}/{device}/command"

    payload_data = {
        "source": clean_source,
        "action": "set_power",
        "power_on": result.power_on,
    }

    payload = json.dumps(
        payload_data,
        ensure_ascii=False,
        separators=(",", ":"),
    )

    return DeviceControlMessage(
        topic=topic,
        payload=payload,
    )