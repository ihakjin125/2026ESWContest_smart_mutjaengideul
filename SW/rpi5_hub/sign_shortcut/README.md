# SafeHub RPi5 Sign Shortcut Integration

수어 인식 결과를 사용자가 등록한 스마트홈 기기 동작과 연결하는
SafeHub RPi5 Hub의 수어 단축키 제어 기능입니다.

기존에 `sign_shortcut/` 내부에서 독립적으로 동작하던 프로토타입을
RPi5 Hub의 MQTT 수신 구조와 통합했습니다.

현재 구현은 실제 Raspberry Pi 5 및 실제 Mosquitto Broker 없이
Fake MQTT Client 기반 자동 테스트까지 완료된 상태입니다.

실제 RPi5, Mosquitto Broker, 스마트홈 하드웨어 연동은 별도 확인이 필요합니다.


## 구조

RPi5 Hub의 주요 실행 흐름은 다음과 같습니다.

```text
main.py
  |
  +-- 환경변수 설정 로드
  |
  +-- EventManager
  +-- ShortcutManager
  +-- ShortcutStore
  +-- ShortcutRegistrationHandler
  +-- ActionExecutor
  +-- DeviceControlPublisher
  +-- SignShortcutController
  |
  +-- mqtt_receiver.MessageRouter
          |
          +-- CSI 이벤트
          |     -> EventManager
          |
          +-- 수어 번역 결과
          |     -> SignShortcutController
          |     -> DeviceControlPublisher
          |
          +-- 단축키 등록/삭제
                -> ShortcutManager
                -> ShortcutStore
```

`main.py`는 Composition Root 역할만 담당하며,
MQTT 메시지의 실제 routing은 `mqtt_receiver.py`의
`MessageRouter`에서 처리합니다.

`main.py`와 `mqtt_receiver.py`는 import만 수행했을 때
Broker 연결이나 `loop_forever()`를 시작하지 않습니다.


## MQTT Topic Contract

| 방향 | Topic | QoS | 역할 |
|---|---|---:|---|
| 수신 | `safehub/csi/bedroom/event` | 1 | 침실 CSI 이벤트 |
| 수신 | `safehub/csi/bathroom/event` | 1 | 화장실 CSI 이벤트 |
| 수신 | `safehub/vision/livingroom/translation` | 0 | 수어 번역 결과 |
| 수신 | `safehub/config/sign_shortcut/command` | 1 | 수어 단축키 등록/삭제 |
| 발행 | `safehub/control/livingroom/aircon/command` | 1 | 거실 에어컨 제어 명령 |

`safehub/vision/livingroom/translation`은 기존 RPi4 Vision 및
SafeHub UI에서 사용하던 계약을 그대로 유지합니다.

`safehub/control/livingroom/aircon/command`도 기존 SafeHub UI의
에어컨 명령 계약을 그대로 사용합니다.

`safehub/config/sign_shortcut/command`는 RPi5 Hub에서
단축키 등록 및 삭제를 처리하기 위해 추가한 MQTT 계약입니다.

별도의 `safehub/state/livingroom/aircon` 상태 Topic은 사용하지 않습니다.


## 수어 번역 메시지

Topic:

```text
safehub/vision/livingroom/translation
```

Payload:

```json
{
  "text": "에어컨"
}
```

등록된 수어인 경우 해당 Shortcut을 찾아 기기 동작을 실행합니다.

등록되지 않은 수어는 MQTT 제어 명령을 발행하지 않습니다.


## 단축키 등록

Topic:

```text
safehub/config/sign_shortcut/command
```

등록 Payload:

```json
{
  "operation": "register",
  "sign": "에어컨",
  "room": "livingroom",
  "device": "aircon",
  "action": "toggle"
}
```

삭제 Payload:

```json
{
  "operation": "remove",
  "sign": "에어컨"
}
```

정상적으로 등록 또는 삭제된 단축키는
`ShortcutStore`를 통해 JSON 파일에 저장됩니다.


## 에어컨 제어 메시지

등록된 `에어컨 -> livingroom -> aircon -> toggle` 단축키가 실행되면
다음 Topic으로 명령을 발행합니다.

```text
safehub/control/livingroom/aircon/command
```

ON:

```json
{
  "source": "sign_shortcut",
  "action": "set_power",
  "power_on": true
}
```

OFF:

```json
{
  "source": "sign_shortcut",
  "action": "set_power",
  "power_on": false
}
```

QoS는 1이며 retain은 사용하지 않습니다.


## CSI 이벤트 처리

RPi5 Hub는 다음 CSI Topic을 구독합니다.

```text
safehub/csi/bedroom/event
safehub/csi/bathroom/event
```

수신된 이벤트는 JSON 형식과 필수 필드를 확인한 뒤
`EventManager`에 전달합니다.

현재 Python Hub에서는 CSI 낙상 이벤트에 대한 새로운 액추에이터 정책이나
SafeHub UI 동작을 추가하지 않습니다.

SafeHub Flutter 앱의 기존 CSI 구독 구조를 유지하며,
Python Hub에서는 이벤트 검증, 큐 적재 및 로그 역할만 수행합니다.


## MQTT 오류 처리

다음과 같은 잘못된 MQTT 메시지는 해당 메시지만 거부하고
MQTT network loop 전체를 종료시키지 않습니다.

```text
잘못된 UTF-8
잘못된 JSON
필수 필드 누락
잘못된 priority
등록되지 않은 수어
```

`on_message()` 내부에서 routing 예외를 처리하여
잘못된 메시지 하나 때문에 Hub 전체 MQTT 수신 루프가 종료되지 않게 합니다.


## Environment Variables

| 환경변수 | 기본값 | 설명 |
|---|---|---|
| `MQTT_BROKER_HOST` | `raspberrypi5.local` | MQTT Broker hostname |
| `MQTT_BROKER_PORT` | `1883` | MQTT Broker port |
| `MQTT_KEEPALIVE` | `60` | MQTT keepalive |
| `MQTT_CLIENT_ID` | 빈 값 | MQTT client ID |
| `SIGN_SHORTCUT_STORE_PATH` | `sign_shortcut/shortcuts.json` | 단축키 저장 파일 위치 |
| `SIGN_COOLDOWN_SEC` | `2.5` | 같은 수어의 빠른 중복 실행 방지 시간 |

실제 장비 IP 주소는 코드에 하드코딩하지 않습니다.


## Shortcut Persistence

단축키 데이터는 기본적으로 다음 위치에 저장됩니다.

```text
SW/rpi5_hub/sign_shortcut/shortcuts.json
```

이 파일은 사용자별 runtime 데이터이므로 Git에서 추적하지 않습니다.

저장 위치는 다음 환경변수로 변경할 수 있습니다.

```text
SIGN_SHORTCUT_STORE_PATH
```

저장 시 기존 파일에 직접 덮어쓰지 않고 다음 방식으로 처리합니다.

```text
임시 파일 생성
-> JSON 전체 작성
-> flush
-> fsync
-> os.replace
-> 기존 shortcuts.json 원자적 교체
```

최종 `os.replace()`가 실패하면 기존 정상 저장 파일은 유지되며,
실패한 임시 파일은 정리됩니다.


## 실행

RPi5 Hub 디렉터리에서 실행합니다.

PowerShell:

```powershell
cd C:\2026ESWContest_smart_mutjaengideul\SW\rpi5_hub
$env:PYTHONPATH = (Get-Location).Path
python .\main.py
```

RPi/Linux:

```bash
cd SW/rpi5_hub
export PYTHONPATH="$(pwd)"
python3 main.py
```

실행 시 `main.py`가 환경변수를 읽고 필요한 객체를 생성한 뒤
MQTT Broker에 연결하고 `loop_forever()`를 실행합니다.

정상 종료 또는 `KeyboardInterrupt` 발생 시 MQTT Client의
`disconnect()`를 호출합니다.


## 자동 테스트

자동 테스트에서는 실제 Raspberry Pi 또는 실제 MQTT Broker를 사용하지 않습니다.

PowerShell:

```powershell
cd C:\2026ESWContest_smart_mutjaengideul\SW\rpi5_hub
$env:PYTHONPATH = (Get-Location).Path

Get-ChildItem .\sign_shortcut\tests\test_*.py |
Sort-Object Name |
ForEach-Object {
    python $_.FullName

    if ($LASTEXITCODE -ne 0) {
        throw "FAIL: $($_.Name)"
    }
}

python .\tests\test_mqtt_receiver.py
python .\tests\test_main_runtime.py
python .\tests\test_event_manager.py
```

현재 로컬 자동 검증 결과:

```text
sign_shortcut 테스트: 74 PASS
mqtt_receiver 테스트: 10 PASS
main runtime 테스트: 7 PASS

총 assertion 기반 자동 검증: 91 PASS

EventManager smoke test:
priority 10 -> 9 -> 3 순서 정상
```

자동 테스트에서 확인한 주요 항목은 MQTT import side effect 없음,
Topic/QoS 구독 계약, CSI routing, 잘못된 메시지 처리,
단축키 등록/삭제, 수어 인식 결과 처리, ON/OFF 명령 발행,
미등록 수어 무시, MQTT publish 실패 감지, cooldown,
단축키 재시작 복원, atomic save, 환경변수 적용,
정상 종료 및 `KeyboardInterrupt` 시 disconnect 처리입니다.


## 실제 Broker 테스트

다음 테스트는 자동 테스트에 포함하지 않습니다.

```text
tests/test_mqtt_sender.py
```

이 파일은 실제 `raspberrypi5.local` MQTT Broker를 요구하는
수동 통합 테스트입니다.

따라서 개발 PC의 자동 테스트에서 실행하지 않습니다.


## 현재 미검증 사항

다음 항목은 실제 장비 환경에서 추가 확인이 필요합니다.

```text
Raspberry Pi 5에서 main.py 실제 실행
raspberrypi5.local 이름 해석
실제 Mosquitto Broker 연결
실제 CSI Publisher -> RPi5 Hub 수신
실제 RPi4 Vision -> translation Topic 수신
실제 수어 결과 -> 에어컨 command 발행
SafeHub Flutter 앱에서 command 수신 확인
실제 장시간 실행 시 MQTT reconnect 동작
실제 스마트홈 하드웨어 제어
```

따라서 현재 상태를
"실제 Raspberry Pi 5 통합 완료" 또는
"실제 하드웨어 E2E 검증 완료"라고 표현하지 않습니다.

현재 확인된 범위는
소프트웨어 구조 통합 및 Fake MQTT 기반 자동 테스트입니다.