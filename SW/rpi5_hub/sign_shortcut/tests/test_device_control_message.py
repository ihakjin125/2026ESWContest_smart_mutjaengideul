import json

from core.action_executor import ActionResult
from core.device_control_message import build_device_control_message


# 1. 에어컨 ON 제어 메시지 생성
result_on = ActionResult(
    success=True,
    room="livingroom",
    device="aircon",
    action="toggle",
    power_on=True,
    message="거실 에어컨이 켜졌습니다.",
)

message_on = build_device_control_message(result_on)

assert message_on.topic == "safehub/control/livingroom/aircon/command"

payload_on = json.loads(message_on.payload)

assert payload_on == {
    "source": "sign_shortcut",
    "action": "set_power",
    "power_on": True,
}

print("PASS | 01 aircon ON control message")


# 2. 에어컨 OFF 제어 메시지 생성
result_off = ActionResult(
    success=True,
    room="livingroom",
    device="aircon",
    action="toggle",
    power_on=False,
    message="거실 에어컨이 꺼졌습니다.",
)

message_off = build_device_control_message(result_off)

assert message_off.topic == "safehub/control/livingroom/aircon/command"

payload_off = json.loads(message_off.payload)

assert payload_off == {
    "source": "sign_shortcut",
    "action": "set_power",
    "power_on": False,
}

print("PASS | 02 aircon OFF control message")


# 3. 사용자 지정 source 확인
message_custom_source = build_device_control_message(
    result_on,
    source="test_source",
)

payload_custom_source = json.loads(message_custom_source.payload)

assert payload_custom_source["source"] == "test_source"

print("PASS | 03 custom control source")


# 4. 실패한 ActionResult는 제어 메시지를 만들 수 없음
failed_result = ActionResult(
    success=False,
    room="livingroom",
    device="aircon",
    action="temperature_down",
    power_on=None,
    message="지원하지 않는 기능입니다.",
)

try:
    build_device_control_message(failed_result)
    raise AssertionError(
        "실패한 ActionResult로 MQTT 메시지가 생성되었습니다."
    )

except ValueError:
    pass

print("PASS | 04 failed action rejected")


# 5. 전원 상태가 없는 성공 결과도 현재 V1에서는 거부
missing_power_result = ActionResult(
    success=True,
    room="livingroom",
    device="aircon",
    action="toggle",
    power_on=None,
    message="",
)

try:
    build_device_control_message(missing_power_result)
    raise AssertionError(
        "power_on이 없는 ActionResult가 허용되었습니다."
    )

except ValueError:
    pass

print("PASS | 05 missing power state rejected")


print()
print("PASS | DeviceControlMessage all tests passed")