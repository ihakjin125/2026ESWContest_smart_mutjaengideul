import json
import tempfile
from pathlib import Path

import paho.mqtt.client as mqtt

from core.event_manager import EventManager
from mqtt_receiver import (
    BATHROOM_TOPIC,
    BEDROOM_TOPIC,
    SHORTCUT_COMMAND_TOPIC,
    SIGN_TRANSLATION_TOPIC,
    MessageRouter,
    configure_callbacks,
    create_client,
    on_connect,
    on_message,
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


class FakePublishResult:
    def __init__(self, rc):
        self.rc = rc


class FakeMqttClient:
    def __init__(self):
        self.subscriptions = []
        self.publishes = []

    def subscribe(self, topic, qos):
        self.subscriptions.append(
            {
                "topic": topic,
                "qos": qos,
            }
        )

        return (
            mqtt.MQTT_ERR_SUCCESS,
            len(self.subscriptions),
        )

    def publish(
        self,
        topic,
        payload,
        qos,
        retain,
    ):
        self.publishes.append(
            {
                "topic": topic,
                "payload": payload,
                "qos": qos,
                "retain": retain,
            }
        )

        return FakePublishResult(
            mqtt.MQTT_ERR_SUCCESS
        )


class FakeReasonCode:
    is_failure = False


class FakeMessage:
    def __init__(
        self,
        topic,
        payload,
    ):
        self.topic = topic
        self.payload = payload


with tempfile.TemporaryDirectory() as temp_dir:
    store_path = Path(temp_dir) / "shortcuts.json"

    event_manager = EventManager()
    shortcut_manager = ShortcutManager()
    shortcut_store = ShortcutStore(store_path)

    registration_handler = ShortcutRegistrationHandler(
        shortcut_manager
    )

    fake_client = FakeMqttClient()

    publisher = DeviceControlPublisher(
        fake_client
    )

    controller = SignShortcutController(
        shortcut_manager=shortcut_manager,
        action_executor=ActionExecutor(),
        publisher=publisher,
        cooldown_sec=0.0,
    )

    router = MessageRouter(
        event_manager=event_manager,
        shortcut_manager=shortcut_manager,
        registration_handler=registration_handler,
        sign_shortcut_controller=controller,
        shortcut_store=shortcut_store,
    )


    # 1. 연결 시 topic/QoS 계약 확인
    on_connect(
        fake_client,
        None,
        None,
        FakeReasonCode(),
        None,
    )

    assert fake_client.subscriptions == [
        {
            "topic": BEDROOM_TOPIC,
            "qos": 1,
        },
        {
            "topic": BATHROOM_TOPIC,
            "qos": 1,
        },
        {
            "topic": SIGN_TRANSLATION_TOPIC,
            "qos": 0,
        },
        {
            "topic": SHORTCUT_COMMAND_TOPIC,
            "qos": 1,
        },
    ]

    print("PASS | 01 MQTT topic QoS contracts")


    # 2. 침실 CSI routing
    bedroom_event = {
        "event": "fall_detected",
        "priority": 9,
    }

    router.route(
        BEDROOM_TOPIC,
        json.dumps(
            bedroom_event
        ).encode("utf-8"),
    )

    queued = event_manager.get_next_event()

    assert queued is not None
    assert queued["event"] == "fall_detected"
    assert queued["priority"] == 9

    print("PASS | 02 bedroom CSI routed")


    # 3. 화장실 CSI routing
    bathroom_event = {
        "event": "fall_detected",
        "priority": 10,
    }

    router.route(
        BATHROOM_TOPIC,
        json.dumps(
            bathroom_event
        ).encode("utf-8"),
    )

    queued = event_manager.get_next_event()

    assert queued is not None
    assert queued["event"] == "fall_detected"
    assert queued["priority"] == 10

    print("PASS | 03 bathroom CSI routed")


    # 4. 단축키 등록 routing
    register_payload = json.dumps(
        {
            "operation": "register",
            "sign": "에어컨",
            "room": "livingroom",
            "device": "aircon",
            "action": "toggle",
        },
        ensure_ascii=False,
    ).encode("utf-8")

    router.route(
        SHORTCUT_COMMAND_TOPIC,
        register_payload,
    )

    shortcut = shortcut_manager.find_by_sign(
        "에어컨"
    )

    assert shortcut is not None
    assert store_path.exists()

    print("PASS | 04 shortcut registration routed")


    # 5. 수어 결과 routing -> aircon command publish
    sign_payload = json.dumps(
        {
            "text": "에어컨",
        },
        ensure_ascii=False,
    ).encode("utf-8")

    router.route(
        SIGN_TRANSLATION_TOPIC,
        sign_payload,
    )

    assert len(fake_client.publishes) == 1

    command = fake_client.publishes[0]

    assert (
        command["topic"]
        == "safehub/control/livingroom/aircon/command"
    )

    payload = json.loads(
        command["payload"]
    )

    assert payload == {
        "source": "sign_shortcut",
        "action": "set_power",
        "power_on": True,
    }

    print("PASS | 05 sign routed to device command")


    # 6. 잘못된 priority 거부
    try:
        router.route(
            BEDROOM_TOPIC,
            json.dumps(
                {
                    "event": "fall_detected",
                    "priority": 99,
                }
            ).encode("utf-8"),
        )

        raise AssertionError(
            "잘못된 priority가 허용되었습니다."
        )

    except ValueError:
        pass

    print("PASS | 06 invalid priority rejected")


    # 7. 잘못된 JSON 거부
    try:
        router.route(
            BEDROOM_TOPIC,
            b"{ invalid json",
        )

        raise AssertionError(
            "잘못된 JSON이 허용되었습니다."
        )

    except json.JSONDecodeError:
        pass

    print("PASS | 07 invalid JSON rejected")


    # 8. 잘못된 UTF-8 거부
    try:
        router.route(
            BEDROOM_TOPIC,
            b"\xff\xfe\xfa",
        )

        raise AssertionError(
            "잘못된 UTF-8 payload가 허용되었습니다."
        )

    except UnicodeDecodeError:
        pass

    print("PASS | 08 invalid UTF-8 rejected")


    # 9. on_message는 예외를 바깥으로 전파하지 않음
    invalid_message = FakeMessage(
        BEDROOM_TOPIC,
        b"{ invalid json",
    )

    on_message(
        fake_client,
        router,
        invalid_message,
    )

    print("PASS | 09 callback contains malformed message errors")


    # 10. MQTT client 생성과 callback 설정을 분리해서 수행
    real_client = create_client(
        client_id="safehub-test",
    )

    assert isinstance(
        real_client,
        mqtt.Client,
    )

    configure_callbacks(
        client=real_client,
        router=router,
    )

    assert real_client.on_connect is not None
    assert real_client.on_message is not None

    real_client.disconnect()

    print("PASS | 10 client creation has no network side effect")


print()
print("PASS | mqtt_receiver all tests passed")