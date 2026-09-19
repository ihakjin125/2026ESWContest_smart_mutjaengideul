import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import main


class FakeMqttClient:
    def __init__(
        self,
        raise_keyboard_interrupt=False,
        raise_connect_error=False,
    ):
        self.userdata = None
        self.on_connect = None
        self.on_message = None

        self.connect_calls = []
        self.disconnect_calls = 0
        self.loop_calls = 0

        self.raise_keyboard_interrupt = raise_keyboard_interrupt
        self.raise_connect_error = raise_connect_error

    def user_data_set(self, userdata):
        self.userdata = userdata

    def connect(
        self,
        host,
        port,
        keepalive,
    ):
        self.connect_calls.append(
            {
                "host": host,
                "port": port,
                "keepalive": keepalive,
            }
        )

        if self.raise_connect_error:
            raise RuntimeError("test connection error")

    def loop_forever(self):
        self.loop_calls += 1

        if self.raise_keyboard_interrupt:
            raise KeyboardInterrupt

    def disconnect(self):
        self.disconnect_calls += 1

    def publish(
        self,
        topic,
        payload,
        qos,
        retain,
    ):
        raise AssertionError(
            "이 테스트에서는 publish가 호출되면 안 됩니다."
        )


with tempfile.TemporaryDirectory() as temp_dir:
    store_path = Path(temp_dir) / "shortcuts.json"

    env = {
        "MQTT_BROKER_HOST": "test-broker.local",
        "MQTT_BROKER_PORT": "2883",
        "MQTT_KEEPALIVE": "45",
        "MQTT_CLIENT_ID": "safehub-test-client",
        "SIGN_SHORTCUT_STORE_PATH": str(store_path),
        "SIGN_COOLDOWN_SEC": "3.0",
    }

    # 1. 환경변수 설정 읽기
    with patch.dict(
        os.environ,
        env,
        clear=False,
    ):
        config = main.load_config()

    assert config.broker_host == "test-broker.local"
    assert config.broker_port == 2883
    assert config.keepalive == 45
    assert config.client_id == "safehub-test-client"
    assert config.shortcut_store_path == store_path
    assert config.sign_cooldown_sec == 3.0

    print("PASS | 01 environment configuration applied")


    # 2. 주입한 MQTT client로 application 조립
    fake_client = FakeMqttClient()

    application = main.build_application(
        config=config,
        client=fake_client,
    )

    assert application.client is fake_client
    assert fake_client.userdata is application.router
    assert fake_client.on_connect is not None
    assert fake_client.on_message is not None

    assert (
        application.sign_shortcut_controller._cooldown_sec
        == 3.0
    )

    print("PASS | 02 application dependencies built")


    # 3. 잘못된 port 환경변수 거부
    with patch.dict(
        os.environ,
        {
            **env,
            "MQTT_BROKER_PORT": "not-a-number",
        },
        clear=False,
    ):
        try:
            main.load_config()

            raise AssertionError(
                "잘못된 MQTT_BROKER_PORT가 허용되었습니다."
            )

        except ValueError:
            pass

    print("PASS | 03 invalid broker port rejected")


    # 4. 음수 cooldown 환경변수 거부
    with patch.dict(
        os.environ,
        {
            **env,
            "SIGN_COOLDOWN_SEC": "-1",
        },
        clear=False,
    ):
        try:
            main.load_config()

            raise AssertionError(
                "음수 SIGN_COOLDOWN_SEC가 허용되었습니다."
            )

        except ValueError:
            pass

    print("PASS | 04 invalid cooldown rejected")


    # 5. run()이 환경변수 host/port/keepalive를 실제 connect에 사용
    normal_client = FakeMqttClient()
    created_client_ids = []

    def create_normal_client(client_id=None):
        created_client_ids.append(client_id)
        return normal_client

    with (
        patch.dict(
            os.environ,
            env,
            clear=False,
        ),
        patch(
            "main.create_client",
            side_effect=create_normal_client,
        ),
    ):
        exit_code = main.run()

    assert exit_code == 0

    assert created_client_ids == [
        "safehub-test-client"
    ]

    assert normal_client.connect_calls == [
        {
            "host": "test-broker.local",
            "port": 2883,
            "keepalive": 45,
        }
    ]

    assert normal_client.loop_calls == 1
    assert normal_client.disconnect_calls == 1

    print(
        "PASS | 05 run uses environment and disconnects normally"
    )


    # 6. KeyboardInterrupt에서도 정상 종료 + disconnect
    interrupt_client = FakeMqttClient(
        raise_keyboard_interrupt=True,
    )

    with (
        patch.dict(
            os.environ,
            env,
            clear=False,
        ),
        patch(
            "main.create_client",
            return_value=interrupt_client,
        ),
    ):
        exit_code = main.run()

    assert exit_code == 0
    assert interrupt_client.loop_calls == 1
    assert interrupt_client.disconnect_calls == 1

    print(
        "PASS | 06 KeyboardInterrupt disconnects cleanly"
    )


    # 7. 실행 오류도 종료 코드 1 + disconnect
    error_client = FakeMqttClient(
        raise_connect_error=True,
    )

    with (
        patch.dict(
            os.environ,
            env,
            clear=False,
        ),
        patch(
            "main.create_client",
            return_value=error_client,
        ),
    ):
        exit_code = main.run()

    assert exit_code == 1
    assert error_client.disconnect_calls == 1

    print(
        "PASS | 07 runtime error returns failure and disconnects"
    )


print()
print("PASS | main runtime all tests passed")