from core.shortcut_manager import ShortcutManager


manager = ShortcutManager()


# 1. 최초 등록
shortcut = manager.register(
    sign="에어컨",
    room="livingroom",
    device="aircon",
    action="toggle",
)

assert shortcut.sign == "에어컨"
assert shortcut.room == "livingroom"
assert shortcut.device == "aircon"
assert shortcut.action == "toggle"
assert len(manager) == 1

print("PASS | 01 shortcut registration")


# 2. 등록된 수어 조회
found = manager.find_by_sign("에어컨")

assert found is not None
assert found.sign == "에어컨"
assert found.room == "livingroom"
assert found.device == "aircon"
assert found.action == "toggle"

print("PASS | 02 shortcut lookup")


# 3. 앞뒤 공백 제거 확인
found_with_spaces = manager.find_by_sign("  에어컨  ")

assert found_with_spaces is not None
assert found_with_spaces == found

print("PASS | 03 sign whitespace normalization")


# 4. 등록되지 않은 수어 조회
not_found = manager.find_by_sign("덥다")

assert not_found is None
assert manager.contains("덥다") is False

print("PASS | 04 unregistered sign")


# 5. 같은 수어를 다시 등록하면 기존 설정 교체
manager.register(
    sign="에어컨",
    room="bedroom",
    device="light",
    action="turn_on",
)

replaced = manager.find_by_sign("에어컨")

assert replaced is not None
assert replaced.room == "bedroom"
assert replaced.device == "light"
assert replaced.action == "turn_on"
assert len(manager) == 1

print("PASS | 05 duplicate sign replacement")


# 6. 삭제 확인
removed = manager.remove("에어컨")

assert removed is True
assert manager.find_by_sign("에어컨") is None
assert len(manager) == 0

print("PASS | 06 shortcut removal")


# 7. 빈 수어 등록 거부
try:
    manager.register(
        sign="   ",
        room="livingroom",
        device="aircon",
        action="toggle",
    )

    raise AssertionError("빈 수어 등록이 허용되었습니다.")

except ValueError:
    pass

print("PASS | 07 empty sign rejection")


# 8. 빈 공간 등록 거부
try:
    manager.register(
        sign="에어컨",
        room="",
        device="aircon",
        action="toggle",
    )

    raise AssertionError("빈 공간 등록이 허용되었습니다.")

except ValueError:
    pass

print("PASS | 08 empty room rejection")


# 9. 빈 기기 등록 거부
try:
    manager.register(
        sign="에어컨",
        room="livingroom",
        device="",
        action="toggle",
    )

    raise AssertionError("빈 기기 등록이 허용되었습니다.")

except ValueError:
    pass

print("PASS | 09 empty device rejection")


# 10. 빈 동작 등록 거부
try:
    manager.register(
        sign="에어컨",
        room="livingroom",
        device="aircon",
        action="",
    )

    raise AssertionError("빈 동작 등록이 허용되었습니다.")

except ValueError:
    pass

print("PASS | 10 empty action rejection")


print()
print("PASS | ShortcutManager all tests passed")