from dataclasses import dataclass


@dataclass(frozen=True)
class SignShortcut:
    sign: str
    room: str
    device: str
    action: str


class ShortcutManager:
    def __init__(self):
        self._shortcuts: dict[str, SignShortcut] = {}

    def register(
        self,
        sign: str,
        room: str,
        device: str,
        action: str,
    ) -> SignShortcut:
        clean_sign = sign.strip()
        clean_room = room.strip()
        clean_device = device.strip()
        clean_action = action.strip()

        if not clean_sign:
            raise ValueError("수어 이름은 비어 있을 수 없습니다.")

        if not clean_room:
            raise ValueError("공간은 비어 있을 수 없습니다.")

        if not clean_device:
            raise ValueError("기기는 비어 있을 수 없습니다.")

        if not clean_action:
            raise ValueError("동작은 비어 있을 수 없습니다.")

        shortcut = SignShortcut(
            sign=clean_sign,
            room=clean_room,
            device=clean_device,
            action=clean_action,
        )

        self._shortcuts[clean_sign] = shortcut

        return shortcut

    def find_by_sign(self, sign: str) -> SignShortcut | None:
        clean_sign = sign.strip()

        if not clean_sign:
            return None

        return self._shortcuts.get(clean_sign)

    def remove(self, sign: str) -> bool:
        clean_sign = sign.strip()

        if not clean_sign:
            return False

        return self._shortcuts.pop(clean_sign, None) is not None

    def get_all(self) -> list[SignShortcut]:
        return list(self._shortcuts.values())

    def contains(self, sign: str) -> bool:
        return self.find_by_sign(sign) is not None

    def __len__(self) -> int:
        return len(self._shortcuts)