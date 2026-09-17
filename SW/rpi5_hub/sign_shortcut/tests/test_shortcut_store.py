import json
import tempfile
from pathlib import Path

from sign_shortcut.core.shortcut_manager import SignShortcut
from sign_shortcut.core.shortcut_store import ShortcutStore


with tempfile.TemporaryDirectory() as temp_dir:
    store_path = Path(temp_dir) / "config" / "shortcuts.json"
    store = ShortcutStore(store_path)

    # 1. 아직 저장 파일이 없으면 빈 목록 반환
    loaded = store.load()

    assert loaded == []

    print("PASS | 01 missing shortcut file returns empty list")


    # 2. 단축키 저장
    shortcuts = [
        SignShortcut(
            sign="에어컨",
            room="livingroom",
            device="aircon",
            action="toggle",
        )
    ]

    store.save(shortcuts)

    assert store_path.exists()

    print("PASS | 02 shortcut JSON file created")


    # 3. 저장된 JSON 내용 확인
    saved_data = json.loads(
        store_path.read_text(encoding="utf-8")
    )

    assert saved_data == [
        {
            "sign": "에어컨",
            "room": "livingroom",
            "device": "aircon",
            "action": "toggle",
        }
    ]

    print("PASS | 03 shortcut JSON content")


    # 4. 저장된 단축키 다시 로드
    loaded_shortcuts = store.load()

    assert len(loaded_shortcuts) == 1
    assert loaded_shortcuts[0].sign == "에어컨"
    assert loaded_shortcuts[0].room == "livingroom"
    assert loaded_shortcuts[0].device == "aircon"
    assert loaded_shortcuts[0].action == "toggle"

    print("PASS | 04 shortcut restored from JSON")


    # 5. 여러 단축키 저장 후 다시 로드
    multiple_shortcuts = [
        SignShortcut(
            sign="에어컨",
            room="livingroom",
            device="aircon",
            action="toggle",
        ),
        SignShortcut(
            sign="점등",
            room="livingroom",
            device="light",
            action="turn_on",
        ),
    ]

    store.save(multiple_shortcuts)

    reloaded = store.load()

    assert reloaded == multiple_shortcuts

    print("PASS | 05 multiple shortcuts round-trip")


    # 6. 잘못된 JSON은 거부
    store_path.write_text(
        "{ invalid json",
        encoding="utf-8",
    )

    try:
        store.load()
        raise AssertionError("잘못된 JSON이 허용되었습니다.")

    except ValueError:
        pass

    print("PASS | 06 invalid JSON rejected")


    # 7. JSON 배열이 아니면 거부
    store_path.write_text(
        json.dumps(
            {
                "sign": "에어컨",
                "room": "livingroom",
                "device": "aircon",
                "action": "toggle",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    try:
        store.load()
        raise AssertionError("JSON 객체가 최상위 데이터로 허용되었습니다.")

    except ValueError:
        pass

    print("PASS | 07 non-list JSON rejected")


    # 8. 필수 필드가 빠진 단축키는 거부
    store_path.write_text(
        json.dumps(
            [
                {
                    "sign": "에어컨",
                    "room": "livingroom",
                    "device": "aircon",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    try:
        store.load()
        raise AssertionError("필수 필드가 없는 단축키가 허용되었습니다.")

    except ValueError:
        pass

    print("PASS | 08 incomplete shortcut rejected")


print()
print("PASS | ShortcutStore all tests passed")