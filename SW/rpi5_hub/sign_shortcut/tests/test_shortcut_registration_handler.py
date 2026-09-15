from core.shortcut_manager import ShortcutManager
from core.shortcut_registration_handler import ShortcutRegistrationHandler


shortcut_manager = ShortcutManager()
handler = ShortcutRegistrationHandler(shortcut_manager)


# 1. 수어 단축키 등록
register_payload = """
{
    "operation": "register",
    "sign": "에어컨",
    "room": "livingroom",
    "device": "aircon",
    "action": "toggle"
}
"""

register_result = handler.handle_payload(register_payload)

assert register_result.success is True
assert register_result.operation == "register"
assert register_result.sign == "에어컨"
assert register_result.shortcut is not None

registered = shortcut_manager.find_by_sign("에어컨")

assert registered is not None
assert registered.room == "livingroom"
assert registered.device == "aircon"
assert registered.action == "toggle"

print("PASS | 01 shortcut registration payload")


# 2. 같은 수어의 등록 내용을 변경
replace_payload = """
{
    "operation": "register",
    "sign": "에어컨",
    "room": "livingroom",
    "device": "aircon",
    "action": "temperature_down"
}
"""

replace_result = handler.handle_payload(replace_payload)

assert replace_result.success is True

replaced = shortcut_manager.find_by_sign("에어컨")

assert replaced is not None
assert replaced.action == "temperature_down"

# 같은 수어이므로 등록 개수는 1개 유지
assert len(shortcut_manager) == 1

print("PASS | 02 existing shortcut replacement")


# 3. 단축키 삭제
remove_payload = """
{
    "operation": "remove",
    "sign": "에어컨"
}
"""

remove_result = handler.handle_payload(remove_payload)

assert remove_result.success is True
assert remove_result.operation == "remove"
assert remove_result.sign == "에어컨"
assert shortcut_manager.find_by_sign("에어컨") is None

print("PASS | 03 shortcut removal")


# 4. 존재하지 않는 단축키 삭제
remove_missing_payload = """
{
    "operation": "remove",
    "sign": "에어컨"
}
"""

remove_missing_result = handler.handle_payload(
    remove_missing_payload
)

assert remove_missing_result.success is False
assert remove_missing_result.operation == "remove"

print("PASS | 04 missing shortcut removal handled")


# 5. 잘못된 JSON 거부
try:
    handler.handle_payload(
        '{"operation":"register","sign":"에어컨"'
    )

    raise AssertionError(
        "잘못된 JSON 메시지가 허용되었습니다."
    )

except ValueError:
    pass

print("PASS | 05 invalid JSON rejected")


# 6. JSON 객체가 아닌 메시지 거부
try:
    handler.handle_payload(
        '["register", "에어컨"]'
    )

    raise AssertionError(
        "JSON 객체가 아닌 메시지가 허용되었습니다."
    )

except ValueError:
    pass

print("PASS | 06 non-object JSON rejected")


# 7. 지원하지 않는 operation 거부
try:
    handler.handle_payload(
        """
        {
            "operation": "unknown",
            "sign": "에어컨"
        }
        """
    )

    raise AssertionError(
        "지원하지 않는 operation이 허용되었습니다."
    )

except ValueError:
    pass

print("PASS | 07 unsupported operation rejected")


# 8. 필수 등록 정보 누락 거부
try:
    handler.handle_payload(
        """
        {
            "operation": "register",
            "sign": "에어컨",
            "room": "livingroom",
            "device": "",
            "action": "toggle"
        }
        """
    )

    raise AssertionError(
        "필수 정보가 없는 단축키가 등록되었습니다."
    )

except ValueError:
    pass

print("PASS | 08 incomplete registration rejected")


print()
print("PASS | ShortcutRegistrationHandler all tests passed")