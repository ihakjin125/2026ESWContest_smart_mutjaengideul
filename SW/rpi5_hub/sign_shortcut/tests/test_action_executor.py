from sign_shortcut.core.action_executor import ActionExecutor
from sign_shortcut.core.shortcut_manager import SignShortcut


executor = ActionExecutor()


# 1. 초기 에어컨 상태는 OFF
assert executor.livingroom_aircon_power_on is False

print("PASS | 01 initial aircon power is OFF")


# 테스트용 단축키
aircon_toggle = SignShortcut(
    sign="에어컨",
    room="livingroom",
    device="aircon",
    action="toggle",
)


# 2. 첫 번째 Toggle: OFF -> ON
result_on = executor.execute(aircon_toggle)

assert result_on.success is True
assert result_on.room == "livingroom"
assert result_on.device == "aircon"
assert result_on.action == "toggle"
assert result_on.power_on is True
assert executor.livingroom_aircon_power_on is True

print("PASS | 02 aircon toggle OFF -> ON")


# 3. 두 번째 Toggle: ON -> OFF
result_off = executor.execute(aircon_toggle)

assert result_off.success is True
assert result_off.power_on is False
assert executor.livingroom_aircon_power_on is False

print("PASS | 03 aircon toggle ON -> OFF")


# 4. 세 번째 Toggle: OFF -> ON
result_on_again = executor.execute(aircon_toggle)

assert result_on_again.success is True
assert result_on_again.power_on is True
assert executor.livingroom_aircon_power_on is True

print("PASS | 04 repeated aircon toggle OFF -> ON")


# 5. 아직 지원하지 않는 동작은 실행하지 않음
unsupported_action = SignShortcut(
    sign="덥다",
    room="livingroom",
    device="aircon",
    action="temperature_down",
)

result_unsupported = executor.execute(unsupported_action)

assert result_unsupported.success is False
assert result_unsupported.power_on is None

# 실패한 명령 때문에 기존 전원 상태가 바뀌면 안 됨
assert executor.livingroom_aircon_power_on is True

print("PASS | 05 unsupported action rejected without state change")


# 6. 다른 기기도 현재는 실행하지 않음
unsupported_device = SignShortcut(
    sign="점등",
    room="livingroom",
    device="light",
    action="turn_on",
)

result_device = executor.execute(unsupported_device)

assert result_device.success is False
assert result_device.power_on is None
assert executor.livingroom_aircon_power_on is True

print("PASS | 06 unsupported device rejected without state change")


print()
print("PASS | ActionExecutor all tests passed")