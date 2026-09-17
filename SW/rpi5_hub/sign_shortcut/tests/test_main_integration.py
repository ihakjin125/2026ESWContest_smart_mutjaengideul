import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import paho.mqtt.client as mqtt

import main
from core.event_manager import EventManager
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

        return (mqtt.MQTT_ERR_SUCCESS, len(self.subscriptions))

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

        return FakePublishResult(mqtt.MQTT_ERR_SUCCESS)


class FakeReasonCode:
    is_failure = False


class FakeMessage:
    def __init__(self, topic, payload):
        self.topic = topic
        self.payload = payload.encode("utf-8")


with tempfile.TemporaryDirectory() as temp_dir:
    store_path = Path(temp_dir) / "shortcuts.json"

    fake_client = FakeMqttClient()

    shortcut_manager = ShortcutManager()
    action_executor = ActionExecutor()
    shortcut_store = ShortcutStore(store_path)

    registration_handler = ShortcutRegistrationHandler(
        shortcut_manager
    )

    device_control_publisher = DeviceControlPublisher(
        fake_client
    )

    sign_shortcut_controller = SignShortcutController(
        shortcut_manager=shortcut_manager,
        action_executor=action_executor,
        publisher=device_control_publisher,
        cooldown_sec=2.5,
    )

    # main.py의 전역 구성 요소를 테스트용 객체로 교체
    main.client = fake_client
    main.event_manager = EventManager()
    main.shortcut_manager = shortcut_manager
    main.action_executor = action_executor
    main.shortcut_store = shortcut_store
    main.registration_handler = registration_handler
    main.device_control_publisher = device_control_publisher
    main.sign_shortcut_controller = sign_shortcut_controller

    expected_topics = {
        main.BEDROOM_TOPIC,
        main.BATHROOM_TOPIC,
        main.SIGN_TRANSLATION_TOPIC,
        main.SHORTCUT_COMMAND_TOPIC,
    }


    # 1. MQTT 최초 연결 시 필요한 4개 토픽 구독
    main.on_connect(
        fake_client,
        None,
        None,
        FakeReasonCode(),
        None,
    )

    first_subscriptions = fake_client.subscriptions[:4]

    assert len(first_subscriptions) == 4
    assert {
        item["topic"]
        for item in first_subscriptions
    } == expected_topics
    assert all(
        item["qos"] == 1
        for item in first_subscriptions
    )

    print("PASS | 01 all MQTT topics subscribed")


    # 2. 재연결 시 동일한 4개 토픽 다시 구독
    main.on_connect(
        fake_client,
        None,
        None,
        FakeReasonCode(),
        None,
    )

    reconnect_subscriptions = fake_client.subscriptions[4:8]

    assert len(reconnect_subscriptions) == 4
    assert {
        item["topic"]
        for item in reconnect_subscriptions
    } == expected_topics
    assert all(
        item["qos"] == 1
        for item in reconnect_subscriptions
    )

    print("PASS | 02 MQTT reconnect resubscribes all topics")


    # 3. 등록 MQTT 수신 -> 메모리 등록 + JSON 저장
    register_payload = json.dumps(
        {
            "operation": "register",
            "sign": "에어컨",
            "room": "livingroom",
            "device": "aircon",
            "action": "toggle",
        },
        ensure_ascii=False,
    )

    register_message = FakeMessage(
        main.SHORTCUT_COMMAND_TOPIC,
        register_payload,
    )

    main.on_message(
        fake_client,
        None,
        register_message,
    )

    registered = shortcut_manager.find_by_sign("에어컨")

    assert registered is not None
    assert registered.room == "livingroom"
    assert registered.device == "aircon"
    assert registered.action == "toggle"
    assert store_path.exists()

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

    print("PASS | 03 registration MQTT saved shortcut JSON")


    # 4. 수어 MQTT -> command + 논리적 state publish
    sign_payload = json.dumps(
        {
            "text": "에어컨",
        },
        ensure_ascii=False,
    )

    sign_message = FakeMessage(
        main.SIGN_TRANSLATION_TOPIC,
        sign_payload,
    )

    with patch(
        "sign_shortcut.core.sign_shortcut_controller.time.monotonic",
        side_effect=[
            100.0,
            100.1,
        ],
    ):
        main.on_message(
            fake_client,
            None,
            sign_message,
        )

        assert len(fake_client.publishes) == 2

        command_publish = fake_client.publishes[0]
        state_publish = fake_client.publishes[1]

        assert (
            command_publish["topic"]
            == "safehub/control/livingroom/aircon/command"
        )

        assert json.loads(command_publish["payload"]) == {
            "source": "sign_shortcut",
            "action": "set_power",
            "power_on": True,
        }

        assert command_publish["qos"] == 1
        assert command_publish["retain"] is False

        assert (
            state_publish["topic"]
            == "safehub/state/livingroom/aircon"
        )

        assert json.loads(state_publish["payload"]) == {
            "source": "sign_shortcut",
            "power_on": True,
        }

        assert state_publish["qos"] == 1
        assert state_publish["retain"] is False

        print(
            "PASS | 04 sign MQTT publishes command and logical state"
        )


        # 5. cooldown 중 동일 수어는 command/state 모두 추가 발행 안 함
        main.on_message(
            fake_client,
            None,
            sign_message,
        )

        assert len(fake_client.publishes) == 2
        assert action_executor.livingroom_aircon_power_on is True

        print(
            "PASS | 05 cooldown blocks duplicate command and state"
        )


    # 6. 프로그램 재시작을 가정하고 JSON에서 단축키 복원
    restored_manager = ShortcutManager()

    main.shortcut_manager = restored_manager
    main.shortcut_store = ShortcutStore(store_path)

    main.load_shortcuts()

    restored = restored_manager.find_by_sign("에어컨")

    assert restored is not None
    assert restored.room == "livingroom"
    assert restored.device == "aircon"
    assert restored.action == "toggle"

    print("PASS | 06 restart restores shortcut from JSON")


    # 복원된 manager를 사용하는 등록 handler로 교체
    main.registration_handler = ShortcutRegistrationHandler(
        restored_manager
    )


    # 7. 삭제 MQTT -> 메모리 삭제 + JSON 갱신
    remove_payload = json.dumps(
        {
            "operation": "remove",
            "sign": "에어컨",
        },
        ensure_ascii=False,
    )

    remove_message = FakeMessage(
        main.SHORTCUT_COMMAND_TOPIC,
        remove_payload,
    )

    main.on_message(
        fake_client,
        None,
        remove_message,
    )

    assert restored_manager.find_by_sign("에어컨") is None

    saved_after_remove = json.loads(
        store_path.read_text(encoding="utf-8")
    )

    assert saved_after_remove == []

    print("PASS | 07 remove MQTT updates shortcut JSON")


    # 8. 기존 CSI 메시지도 EventManager로 정상 전달
    main.event_manager = EventManager()

    csi_payload = json.dumps(
        {
            "event": "fall_detected",
            "priority": 10,
        },
        ensure_ascii=False,
    )

    csi_message = FakeMessage(
        main.BEDROOM_TOPIC,
        csi_payload,
    )

    main.on_message(
        fake_client,
        None,
        csi_message,
    )

    queued_event = main.event_manager.get_next_event()

    assert queued_event is not None
    assert queued_event["event"] == "fall_detected"
    assert queued_event["priority"] == 10

    print("PASS | 08 CSI MQTT still reaches EventManager")


print()
print("PASS | RPi5 main integration all tests passed")