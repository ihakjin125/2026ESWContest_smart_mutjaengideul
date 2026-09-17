import json
from pathlib import Path

import paho.mqtt.client as mqtt

from core.event_manager import EventManager
from sign_shortcut.core.action_executor import (
    ActionExecutor,
    ActionResult,
)
from sign_shortcut.core.shortcut_manager import ShortcutManager
from sign_shortcut.core.shortcut_registration_handler import (
    ShortcutRegistrationHandler,
)
from sign_shortcut.core.shortcut_store import ShortcutStore
from sign_shortcut.core.sign_shortcut_controller import (
    SignShortcutController,
)
from sign_shortcut.device_control_publisher import DeviceControlPublisher


BROKER_HOST = "raspberrypi5.local"
BROKER_PORT = 1883

BEDROOM_TOPIC = "safehub/csi/bedroom/event"
BATHROOM_TOPIC = "safehub/csi/bathroom/event"

SIGN_TRANSLATION_TOPIC = "safehub/vision/livingroom/translation"

# 현재 팀 통합용으로 사용하는 수어 단축키 등록/삭제 토픽
SHORTCUT_COMMAND_TOPIC = "safehub/config/sign_shortcut/command"

# 동일 수어가 연속 인식될 때 중복 실행을 방지하는 시간
SIGN_COOLDOWN_SEC = 2.5

SHORTCUT_STORE_PATH = (
    Path(__file__).resolve().parent
    / "sign_shortcut"
    / "shortcuts.json"
)


# 기존 CSI 이벤트 관리자
event_manager = EventManager()

# 수어 단축키 관련 구성 요소
shortcut_manager = ShortcutManager()
action_executor = ActionExecutor()
shortcut_store = ShortcutStore(SHORTCUT_STORE_PATH)

registration_handler = ShortcutRegistrationHandler(
    shortcut_manager
)


# MQTT Client 생성
client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

device_control_publisher = DeviceControlPublisher(client)

sign_shortcut_controller = SignShortcutController(
    shortcut_manager=shortcut_manager,
    action_executor=action_executor,
    publisher=device_control_publisher,
    cooldown_sec=SIGN_COOLDOWN_SEC,
)


def load_shortcuts() -> None:
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


def publish_logical_state(result: ActionResult) -> None:
    if not result.success or result.power_on is None:
        return

    # 현재 팀 통합용으로 제안된 논리적 상태 토픽.
    # 실제 하드웨어 ACK가 아니라 RPi5가 요청한 목표 상태를 의미한다.
    state_topic = (
        f"safehub/state/{result.room}/{result.device}"
    )

    state_payload = json.dumps(
        {
            "source": "sign_shortcut",
            "power_on": result.power_on,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )

    publish_result = client.publish(
        topic=state_topic,
        payload=state_payload,
        qos=1,
        retain=False,
    )

    if publish_result.rc != mqtt.MQTT_ERR_SUCCESS:
        raise RuntimeError(
            f"논리적 기기 상태 MQTT publish 실패: "
            f"rc={publish_result.rc}"
        )


def handle_csi_message(payload: str) -> None:
    event = json.loads(payload)

    if not isinstance(event, dict):
        raise ValueError(
            "CSI 이벤트 메시지는 JSON 객체여야 합니다."
        )

    event_manager.add_event(event)

    print(
        f"수신: {event['event']} "
        f"(priority={event['priority']})"
    )


def handle_sign_message(payload: str) -> None:
    data = json.loads(payload)

    if not isinstance(data, dict):
        raise ValueError(
            "수어 번역 메시지는 JSON 객체여야 합니다."
        )

    text = data.get("text")

    if not isinstance(text, str) or not text.strip():
        raise ValueError(
            "수어 번역 메시지에 유효한 text가 없습니다."
        )

    result = sign_shortcut_controller.handle_sign(text)

    if result is None:
        print(
            f"등록된 단축키가 없거나 cooldown 중: "
            f"{text.strip()}"
        )
        return

    if result.success:
        publish_logical_state(result)

    print(result.message)


def handle_shortcut_command(payload: str) -> None:
    result = registration_handler.handle_payload(payload)

    if result.success:
        shortcut_store.save(
            shortcut_manager.get_all()
        )

    print(result.message)


def dispatch_message(
    topic: str,
    payload: str,
) -> None:
    if topic == BEDROOM_TOPIC:
        handle_csi_message(payload)
        return

    if topic == BATHROOM_TOPIC:
        handle_csi_message(payload)
        return

    if topic == SIGN_TRANSLATION_TOPIC:
        handle_sign_message(payload)
        return

    if topic == SHORTCUT_COMMAND_TOPIC:
        handle_shortcut_command(payload)
        return

    print(f"알 수 없는 MQTT 토픽: {topic}")


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

    # 재연결 시에도 필요한 모든 토픽을 다시 구독
    client.subscribe(BEDROOM_TOPIC, qos=1)
    client.subscribe(BATHROOM_TOPIC, qos=1)
    client.subscribe(SIGN_TRANSLATION_TOPIC, qos=1)
    client.subscribe(SHORTCUT_COMMAND_TOPIC, qos=1)


def on_message(
    client,
    userdata,
    msg,
):
    try:
        payload = msg.payload.decode("utf-8")

        dispatch_message(
            topic=msg.topic,
            payload=payload,
        )

    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        KeyError,
        ValueError,
        RuntimeError,
    ) as error:
        print(
            f"잘못된 MQTT 메시지 "
            f"(topic={msg.topic}): {error}"
        )


def main() -> None:
    load_shortcuts()

    client.on_connect = on_connect
    client.on_message = on_message

    client.connect(
        BROKER_HOST,
        BROKER_PORT,
        60,
    )

    print(
        f"MQTT Broker 연결 시도: "
        f"{BROKER_HOST}:{BROKER_PORT}"
    )

    client.loop_forever()


if __name__ == "__main__":
    main()