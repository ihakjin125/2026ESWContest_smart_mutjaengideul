import json
import tempfile
from pathlib import Path

import paho.mqtt.client as mqtt

import main
from mqtt_receiver import (
    BATHROOM_TOPIC,
    BEDROOM_TOPIC,
    SHORTCUT_COMMAND_TOPIC,
    SIGN_TRANSLATION_TOPIC,
)


class FakePublishResult:
    def __init__(self, rc):
        self.rc = rc


class FakeMqttClient:
    def __init__(self):
        self.userdata = None
        self.on_connect = None
        self.on_message = None

        self.publishes = []

    def user_data_set(self, userdata):
        self.userdata = userdata

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


with tempfile.TemporaryDirectory() as temp_dir:
    store_path = Path(temp_dir) / "shortcuts.json"

    config = main.AppConfig(
        broker_host="test-broker.local",
        broker_port=1883,
        keepalive=60,
        client_id="safehub-main-integration-test",
        shortcut_store_path=store_path,
        sign_cooldown_sec=0.0,
    )

    fake_client = FakeMqttClient()

    application = main.build_application(
        config=config,
        client=fake_client,
    )

    # 1. build_application이 Router와 MQTT callback을 연결
    assert fake_client.userdata is application.router
    assert fake_client.on_connect is not None
    assert fake_client.on_message is not None

    print("PASS | 01 application router configured")


    # 2. 단축키 등록 -> ShortcutManager + JSON 저장
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

    application.router.route(
        SHORTCUT_COMMAND_TOPIC,
        register_payload,
    )

    registered = application.shortcut_manager.find_by_sign(
        "에어컨"
    )

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

    print("PASS | 02 registration persisted")


    # 3. 등록된 수어 -> aircon ON command 1회 publish
    sign_payload = json.dumps(
        {
            "text": "에어컨",
        },
        ensure_ascii=False,
    ).encode("utf-8")

    application.router.route(
        SIGN_TRANSLATION_TOPIC,
        sign_payload,
    )

    assert len(fake_client.publishes) == 1

    command = fake_client.publishes[0]

    assert (
        command["topic"]
        == "safehub/control/livingroom/aircon/command"
    )

    assert json.loads(command["payload"]) == {
        "source": "sign_shortcut",
        "action": "set_power",
        "power_on": True,
    }

    assert command["qos"] == 1
    assert command["retain"] is False

    print("PASS | 03 sign publishes aircon ON command")


    # 4. 같은 수어 재실행 -> aircon OFF command
    application.router.route(
        SIGN_TRANSLATION_TOPIC,
        sign_payload,
    )

    assert len(fake_client.publishes) == 2

    second_command = fake_client.publishes[1]

    assert json.loads(second_command["payload"]) == {
        "source": "sign_shortcut",
        "action": "set_power",
        "power_on": False,
    }

    print("PASS | 04 repeated sign publishes aircon OFF command")


    # 5. 등록되지 않은 수어 -> publish 없음
    before_publish_count = len(
        fake_client.publishes
    )

    unknown_payload = json.dumps(
        {
            "text": "감사",
        },
        ensure_ascii=False,
    ).encode("utf-8")

    application.router.route(
        SIGN_TRANSLATION_TOPIC,
        unknown_payload,
    )

    assert (
        len(fake_client.publishes)
        == before_publish_count
    )

    print("PASS | 05 unregistered sign publishes nothing")


    # 6. 재시작 가정 -> JSON에서 단축키 복원
    restarted_client = FakeMqttClient()

    restarted_application = main.build_application(
        config=config,
        client=restarted_client,
    )

    restored = (
        restarted_application
        .shortcut_manager
        .find_by_sign("에어컨")
    )

    assert restored is not None
    assert restored.room == "livingroom"
    assert restored.device == "aircon"
    assert restored.action == "toggle"

    print("PASS | 06 restart restores shortcut")


    # 7. 삭제 -> 메모리와 JSON 모두 갱신
    remove_payload = json.dumps(
        {
            "operation": "remove",
            "sign": "에어컨",
        },
        ensure_ascii=False,
    ).encode("utf-8")

    restarted_application.router.route(
        SHORTCUT_COMMAND_TOPIC,
        remove_payload,
    )

    assert (
        restarted_application
        .shortcut_manager
        .find_by_sign("에어컨")
        is None
    )

    saved_after_remove = json.loads(
        store_path.read_text(encoding="utf-8")
    )

    assert saved_after_remove == []

    print("PASS | 07 removal updates persisted shortcuts")


    # 8. 침실 CSI -> EventManager
    bedroom_payload = json.dumps(
        {
            "event": "fall_detected",
            "priority": 9,
        }
    ).encode("utf-8")

    restarted_application.router.route(
        BEDROOM_TOPIC,
        bedroom_payload,
    )

    bedroom_event = (
        restarted_application
        .event_manager
        .get_next_event()
    )

    assert bedroom_event is not None
    assert bedroom_event["event"] == "fall_detected"
    assert bedroom_event["priority"] == 9

    print("PASS | 08 bedroom CSI reaches EventManager")


    # 9. 화장실 CSI -> EventManager
    bathroom_payload = json.dumps(
        {
            "event": "fall_detected",
            "priority": 10,
        }
    ).encode("utf-8")

    restarted_application.router.route(
        BATHROOM_TOPIC,
        bathroom_payload,
    )

    bathroom_event = (
        restarted_application
        .event_manager
        .get_next_event()
    )

    assert bathroom_event is not None
    assert bathroom_event["event"] == "fall_detected"
    assert bathroom_event["priority"] == 10

    print("PASS | 09 bathroom CSI reaches EventManager")


print()
print("PASS | RPi5 main integration all tests passed")