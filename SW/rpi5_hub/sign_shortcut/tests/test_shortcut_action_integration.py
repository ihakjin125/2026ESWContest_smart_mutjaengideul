from core.action_executor import ActionExecutor
from core.shortcut_manager import ShortcutManager


shortcut_manager = ShortcutManager()
action_executor = ActionExecutor()


# 1. 사용자가 "에어컨" 수어에 거실 에어컨 Toggle 기능을 등록했다고 가정
shortcut_manager.register(
    sign="에어컨",
    room="livingroom",
    device="aircon",
    action="toggle",
)

print("PASS | 01 aircon shortcut registered")


# 2. 수어 인식 결과 "에어컨"이 들어옴
recognized_sign = "에어컨"

shortcut = shortcut_manager.find_by_sign(recognized_sign)

assert shortcut is not None
assert shortcut.room == "livingroom"
assert shortcut.device == "aircon"
assert shortcut.action == "toggle"

print("PASS | 02 recognized sign resolved to shortcut")


# 3. 등록된 기능 실행: OFF -> ON
result_on = action_executor.execute(shortcut)

assert result_on.success is True
assert result_on.power_on is True
assert action_executor.livingroom_aircon_power_on is True

print("PASS | 03 recognized sign toggles aircon OFF -> ON")


# 4. 같은 수어가 다시 인식됨
shortcut_again = shortcut_manager.find_by_sign("에어컨")

assert shortcut_again is not None

result_off = action_executor.execute(shortcut_again)

assert result_off.success is True
assert result_off.power_on is False
assert action_executor.livingroom_aircon_power_on is False

print("PASS | 04 repeated sign toggles aircon ON -> OFF")


# 5. 등록되지 않은 수어는 실행되지 않음
unknown_shortcut = shortcut_manager.find_by_sign("감사")

assert unknown_shortcut is None
assert action_executor.livingroom_aircon_power_on is False

print("PASS | 05 unregistered sign does not execute action")


# 6. 같은 수어의 등록 기능을 다른 동작으로 변경 가능
shortcut_manager.register(
    sign="에어컨",
    room="livingroom",
    device="aircon",
    action="temperature_down",
)

changed_shortcut = shortcut_manager.find_by_sign("에어컨")

assert changed_shortcut is not None
assert changed_shortcut.action == "temperature_down"

changed_result = action_executor.execute(changed_shortcut)

# temperature_down은 아직 V1에서 구현하지 않았으므로 실행 거부
assert changed_result.success is False
assert action_executor.livingroom_aircon_power_on is False

print("PASS | 06 shortcut mapping can change without changing sign engine")


print()
print("PASS | Shortcut -> Action integration all tests passed")