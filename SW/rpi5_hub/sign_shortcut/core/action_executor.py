from dataclasses import dataclass

from .shortcut_manager import SignShortcut


@dataclass(frozen=True)
class ActionResult:
    success: bool
    room: str
    device: str
    action: str
    power_on: bool | None
    message: str


class ActionExecutor:
    def __init__(self):
        # V1에서는 RPi5 Hub가 거실 에어컨의 논리적 전원 상태를 관리한다.
        # 실제 IoT 기기의 상태 피드백이 연결되면 이후 동기화할 수 있다.
        self._livingroom_aircon_power_on = False

    @property
    def livingroom_aircon_power_on(self) -> bool:
        return self._livingroom_aircon_power_on

    def execute(self, shortcut: SignShortcut) -> ActionResult:
        # V1 지원 기능:
        # 거실 에어컨 전원 ON/OFF Toggle
        if (
            shortcut.room == "livingroom"
            and shortcut.device == "aircon"
            and shortcut.action == "toggle"
        ):
            self._livingroom_aircon_power_on = (
                not self._livingroom_aircon_power_on
            )

            if self._livingroom_aircon_power_on:
                message = "거실 에어컨이 켜졌습니다."
            else:
                message = "거실 에어컨이 꺼졌습니다."

            return ActionResult(
                success=True,
                room=shortcut.room,
                device=shortcut.device,
                action=shortcut.action,
                power_on=self._livingroom_aircon_power_on,
                message=message,
            )

        return ActionResult(
            success=False,
            room=shortcut.room,
            device=shortcut.device,
            action=shortcut.action,
            power_on=None,
            message="아직 지원하지 않는 기기 제어 기능입니다.",
        )