import os
from dataclasses import dataclass
from pathlib import Path

import paho.mqtt.client as mqtt

from core.event_manager import EventManager
from mqtt_receiver import (
    MessageRouter,
    configure_callbacks,
    create_client,
)
from sign_shortcut.core.action_executor import ActionExecutor
from sign_shortcut.core.shortcut_manager import ShortcutManager
from sign_shortcut.core.shortcut_registration_handler import (
    ShortcutRegistrationHandler,
)
from sign_shortcut.core.shortcut_store import ShortcutStore
from sign_shortcut.core.sign_shortcut_controller import (
    SignShortcutController,
)
from sign_shortcut.device_control_publisher import DeviceControlPublisher


DEFAULT_BROKER_HOST = "raspberrypi5.local"
DEFAULT_BROKER_PORT = 1883
DEFAULT_KEEPALIVE = 60
DEFAULT_SIGN_COOLDOWN_SEC = 2.5

DEFAULT_SHORTCUT_STORE_PATH = (
    Path(__file__).resolve().parent
    / "sign_shortcut"
    / "shortcuts.json"
)


@dataclass(frozen=True)
class AppConfig:
    broker_host: str
    broker_port: int
    keepalive: int
    client_id: str | None
    shortcut_store_path: Path
    sign_cooldown_sec: float


@dataclass
class Application:
    config: AppConfig
    event_manager: EventManager
    shortcut_manager: ShortcutManager
    shortcut_store: ShortcutStore
    registration_handler: ShortcutRegistrationHandler
    action_executor: ActionExecutor
    client: mqtt.Client
    device_control_publisher: DeviceControlPublisher
    sign_shortcut_controller: SignShortcutController
    router: MessageRouter


def _read_positive_int(
    env_name: str,
    default: int,
) -> int:
    raw_value = os.getenv(env_name)

    if raw_value is None:
        return default

    try:
        value = int(raw_value)
    except ValueError as error:
        raise ValueError(
            f"{env_name}은 정수여야 합니다."
        ) from error

    if value <= 0:
        raise ValueError(
            f"{env_name}은 1 이상이어야 합니다."
        )

    return value


def _read_non_negative_float(
    env_name: str,
    default: float,
) -> float:
    raw_value = os.getenv(env_name)

    if raw_value is None:
        return default

    try:
        value = float(raw_value)
    except ValueError as error:
        raise ValueError(
            f"{env_name}은 숫자여야 합니다."
        ) from error

    if value < 0:
        raise ValueError(
            f"{env_name}은 0 이상이어야 합니다."
        )

    return value


def load_config() -> AppConfig:
    broker_host = os.getenv(
        "MQTT_BROKER_HOST",
        DEFAULT_BROKER_HOST,
    ).strip()

    if not broker_host:
        raise ValueError(
            "MQTT_BROKER_HOST는 비어 있을 수 없습니다."
        )

    client_id = os.getenv(
        "MQTT_CLIENT_ID",
        "",
    ).strip()

    shortcut_store_value = os.getenv(
        "SIGN_SHORTCUT_STORE_PATH",
        str(DEFAULT_SHORTCUT_STORE_PATH),
    ).strip()

    if not shortcut_store_value:
        raise ValueError(
            "SIGN_SHORTCUT_STORE_PATH는 비어 있을 수 없습니다."
        )

    return AppConfig(
        broker_host=broker_host,
        broker_port=_read_positive_int(
            "MQTT_BROKER_PORT",
            DEFAULT_BROKER_PORT,
        ),
        keepalive=_read_positive_int(
            "MQTT_KEEPALIVE",
            DEFAULT_KEEPALIVE,
        ),
        client_id=client_id or None,
        shortcut_store_path=Path(
            shortcut_store_value
        ),
        sign_cooldown_sec=_read_non_negative_float(
            "SIGN_COOLDOWN_SEC",
            DEFAULT_SIGN_COOLDOWN_SEC,
        ),
    )


def load_shortcuts(
    shortcut_store: ShortcutStore,
    shortcut_manager: ShortcutManager,
) -> None:
    shortcuts = shortcut_store.load()

    for shortcut in shortcuts:
        shortcut_manager.register(
            sign=shortcut.sign,
            room=shortcut.room,
            device=shortcut.device,
            action=shortcut.action,
        )

    print(
        f"수어 단축키 {len(shortcuts)}개를 불러왔습니다."
    )


def build_application(
    config: AppConfig | None = None,
    client: mqtt.Client | None = None,
) -> Application:
    app_config = config or load_config()

    event_manager = EventManager()
    shortcut_manager = ShortcutManager()
    shortcut_store = ShortcutStore(
        app_config.shortcut_store_path
    )

    load_shortcuts(
        shortcut_store=shortcut_store,
        shortcut_manager=shortcut_manager,
    )

    mqtt_client = client or create_client(
        client_id=app_config.client_id,
    )

    action_executor = ActionExecutor()

    device_control_publisher = DeviceControlPublisher(
        mqtt_client
    )

    sign_shortcut_controller = SignShortcutController(
        shortcut_manager=shortcut_manager,
        action_executor=action_executor,
        publisher=device_control_publisher,
        cooldown_sec=app_config.sign_cooldown_sec,
    )

    registration_handler = ShortcutRegistrationHandler(
        shortcut_manager
    )

    router = MessageRouter(
        event_manager=event_manager,
        shortcut_manager=shortcut_manager,
        registration_handler=registration_handler,
        sign_shortcut_controller=sign_shortcut_controller,
        shortcut_store=shortcut_store,
    )

    configure_callbacks(
        client=mqtt_client,
        router=router,
    )

    return Application(
        config=app_config,
        event_manager=event_manager,
        shortcut_manager=shortcut_manager,
        shortcut_store=shortcut_store,
        registration_handler=registration_handler,
        action_executor=action_executor,
        client=mqtt_client,
        device_control_publisher=device_control_publisher,
        sign_shortcut_controller=sign_shortcut_controller,
        router=router,
    )


def run() -> int:
    application = None

    try:
        application = build_application()

        print(
            "MQTT Broker 연결 시도: "
            f"{application.config.broker_host}:"
            f"{application.config.broker_port}"
        )

        application.client.connect(
            application.config.broker_host,
            application.config.broker_port,
            application.config.keepalive,
        )

        application.client.loop_forever()

        return 0

    except KeyboardInterrupt:
        print("사용자 요청으로 SafeHub RPi5 Hub를 종료합니다.")
        return 0

    except Exception as error:
        print(
            f"SafeHub RPi5 Hub 실행 오류: {error}"
        )
        return 1

    finally:
        if application is not None:
            try:
                application.client.disconnect()
            except Exception as error:
                print(
                    f"MQTT 연결 종료 중 오류: {error}"
                )


if __name__ == "__main__":
    raise SystemExit(run())