import json
from dataclasses import dataclass

from core.shortcut_manager import SignShortcut, ShortcutManager


@dataclass(frozen=True)
class ShortcutRegistrationResult:
    success: bool
    operation: str
    sign: str
    shortcut: SignShortcut | None
    message: str


class ShortcutRegistrationHandler:
    def __init__(self, shortcut_manager: ShortcutManager):
        self._shortcut_manager = shortcut_manager

    def handle_payload(
        self,
        payload: str,
    ) -> ShortcutRegistrationResult:
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as error:
            raise ValueError(
                "단축키 등록 메시지가 올바른 JSON 형식이 아닙니다."
            ) from error

        if not isinstance(data, dict):
            raise ValueError(
                "단축키 등록 메시지는 JSON 객체여야 합니다."
            )

        operation = str(data.get("operation", "")).strip()

        if operation == "register":
            return self._handle_register(data)

        if operation == "remove":
            return self._handle_remove(data)

        raise ValueError(
            f"지원하지 않는 단축키 작업입니다: {operation}"
        )

    def _handle_register(
        self,
        data: dict,
    ) -> ShortcutRegistrationResult:
        sign = str(data.get("sign", "")).strip()
        room = str(data.get("room", "")).strip()
        device = str(data.get("device", "")).strip()
        action = str(data.get("action", "")).strip()

        shortcut = self._shortcut_manager.register(
            sign=sign,
            room=room,
            device=device,
            action=action,
        )

        return ShortcutRegistrationResult(
            success=True,
            operation="register",
            sign=shortcut.sign,
            shortcut=shortcut,
            message="수어 단축키가 등록되었습니다.",
        )

    def _handle_remove(
        self,
        data: dict,
    ) -> ShortcutRegistrationResult:
        sign = str(data.get("sign", "")).strip()

        if not sign:
            raise ValueError(
                "삭제할 수어 이름은 비어 있을 수 없습니다."
            )

        removed = self._shortcut_manager.remove(sign)

        if not removed:
            return ShortcutRegistrationResult(
                success=False,
                operation="remove",
                sign=sign,
                shortcut=None,
                message="등록된 수어 단축키가 없습니다.",
            )

        return ShortcutRegistrationResult(
            success=True,
            operation="remove",
            sign=sign,
            shortcut=None,
            message="수어 단축키가 삭제되었습니다.",
        )