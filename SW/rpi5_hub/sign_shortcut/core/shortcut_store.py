import json
from pathlib import Path

from .shortcut_manager import SignShortcut


class ShortcutStore:
    def __init__(self, file_path: str | Path):
        self._file_path = Path(file_path)

    def load(self) -> list[SignShortcut]:
        if not self._file_path.exists():
            return []

        try:
            raw_data = self._file_path.read_text(encoding="utf-8")
            data = json.loads(raw_data)
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(
                f"단축키 저장 파일을 읽을 수 없습니다: {self._file_path}"
            ) from exc

        if not isinstance(data, list):
            raise ValueError("단축키 저장 데이터는 JSON 배열이어야 합니다.")

        shortcuts = []

        for item in data:
            if not isinstance(item, dict):
                raise ValueError("각 단축키 항목은 JSON 객체여야 합니다.")

            try:
                shortcut = SignShortcut(
                    sign=item["sign"],
                    room=item["room"],
                    device=item["device"],
                    action=item["action"],
                )
            except KeyError as exc:
                raise ValueError(
                    f"단축키 항목에 필수 필드가 없습니다: {exc.args[0]}"
                ) from exc

            shortcuts.append(shortcut)

        return shortcuts

    def save(self, shortcuts: list[SignShortcut]) -> None:
        data = [
            {
                "sign": shortcut.sign,
                "room": shortcut.room,
                "device": shortcut.device,
                "action": shortcut.action,
            }
            for shortcut in shortcuts
        ]

        self._file_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        try:
            self._file_path.write_text(
                json.dumps(
                    data,
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        except OSError as exc:
            raise ValueError(
                f"단축키 저장 파일을 쓸 수 없습니다: {self._file_path}"
            ) from exc