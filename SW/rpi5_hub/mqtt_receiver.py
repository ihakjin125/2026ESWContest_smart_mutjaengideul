import json

import paho.mqtt.client as mqtt

from core.event_manager import EventManager
from sign_shortcut.core.shortcut_manager import ShortcutManager
from sign_shortcut.core.shortcut_registration_handler import (
    ShortcutRegistrationHandler,
)
from sign_shortcut.core.shortcut_store import ShortcutStore
from sign_shortcut.core.sign_shortcut_controller import (
    SignShortcutController,
)


BEDROOM_TOPIC = "safehub/csi/bedroom/event"
BATHROOM_TOPIC = "safehub/csi/bathroom/event"

SIGN_TRANSLATION_TOPIC = "safehub/vision/livingroom/translation"
SHORTCUT_COMMAND_TOPIC = "safehub/config/sign_shortcut/command"


SUBSCRIPTIONS = (
    (BEDROOM_TOPIC, 1),
    (BATHROOM_TOPIC, 1),
    (SIGN_TRANSLATION_TOPIC, 0),
    (SHORTCUT_COMMAND_TOPIC, 1),
)


class MessageRouter:
    def __init__(
        self,
        event_manager: EventManager,
        shortcut_manager: ShortcutManager,
        registration_handler: ShortcutRegistrationHandler,
        sign_shortcut_controller: SignShortcutController,
        shortcut_store: ShortcutStore,
    ):
        self._event_manager = event_manager
        self._shortcut_manager = shortcut_manager
        self._registration_handler = registration_handler
        self._sign_shortcut_controller = sign_shortcut_controller
        self._shortcut_store = shortcut_store

    def route(
        self,
        topic: str,
        payload: bytes,
    ) -> None:
        text_payload = payload.decode("utf-8")

        if topic in (BEDROOM_TOPIC, BATHROOM_TOPIC):
            self._route_csi(text_payload)
            return

        if topic == SIGN_TRANSLATION_TOPIC:
            self._route_sign(text_payload)
            return

        if topic == SHORTCUT_COMMAND_TOPIC:
            self._route_shortcut_command(text_payload)
            return

        print(f"알 수 없는 MQTT 토픽: {topic}")

    def _route_csi(self, payload: str) -> None:
        event = json.loads(payload)

        if not isinstance(event, dict):
            raise ValueError(
                "CSI 이벤트 메시지는 JSON 객체여야 합니다."
            )

        event_name = event.get("event")

        if not isinstance(event_name, str) or not event_name.strip():
            raise ValueError(
                "CSI 이벤트 메시지에 유효한 event가 없습니다."
            )

        self._event_manager.add_event(event)

        print(
            f"수신: {event_name} "
            f"(priority={event['priority']})"
        )

    def _route_sign(self, payload: str) -> None:
        data = json.loads(payload)

        if not isinstance(data, dict):
            raise ValueError(
                "수어 번역 메시지는 JSON 객체여야 합니다."
            )

        sign_text = data.get("text")

        if (
            not isinstance(sign_text, str)
            or not sign_text.strip()
        ):
            raise ValueError(
                "수어 번역 메시지에 유효한 text가 없습니다."
            )

        result = self._sign_shortcut_controller.handle_sign(
            sign_text
        )

        if result is None:
            print(
                f"등록된 단축키가 없거나 cooldown 중: "
                f"{sign_text.strip()}"
            )
            return

        print(result.message)

    def _route_shortcut_command(
        self,
        payload: str,
    ) -> None:
        result = self._registration_handler.handle_payload(
            payload
        )

        if result.success:
            self._shortcut_store.save(
                self._shortcut_manager.get_all()
            )

        print(result.message)


def on_connect(
    client,
    userdata,
    flags,
    reason_code,
    properties,
):
    if reason_code.is_failure:
        print(f"MQTT 연결 실패: {reason_code}")
        return

    print("MQTT Broker 연결 성공")

    for topic, qos in SUBSCRIPTIONS:
        client.subscribe(
            topic,
            qos=qos,
        )


def on_message(
    client,
    userdata,
    msg,
):
    router = userdata

    if not isinstance(router, MessageRouter):
        print(
            "잘못된 MQTT 설정: "
            "MessageRouter가 등록되지 않았습니다."
        )
        return

    try:
        router.route(
            topic=msg.topic,
            payload=msg.payload,
        )

    except Exception as error:
        # 잘못된 MQTT 메시지 하나 때문에
        # Paho MQTT network loop 전체가 종료되지 않게 한다.
        print(
            f"잘못된 MQTT 메시지 "
            f"(topic={msg.topic}): {error}"
        )


def configure_callbacks(
    client: mqtt.Client,
    router: MessageRouter,
) -> None:
    client.user_data_set(router)
    client.on_connect = on_connect
    client.on_message = on_message


def create_client(
    client_id: str | None = None,
) -> mqtt.Client:
    return mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=client_id or "",
    )