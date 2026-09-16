# Wi-Fi CSI 모듈의 팀 시스템 연동 범위

## 현재 변경

WiFi-CSI-Sensing 폴더에 센싱 실험·학습·추론 도구를 추가합니다. 팀장 저장소 main을 기준으로 준비하며 기존 feature/HW의 ESP32, feature/SW의 SW 소스는 수정하지 않습니다.

PC에서 학습하고 Pi에서 수집·전처리·추론합니다. 현재 edge_runtime.py의 JSON 출력은 로컬 실행 결과이며 MQTT 이벤트 규격으로 정의한 것이 아닙니다.

## 확인한 MQTT 규격

기준 파일: [config/topics.json, develop의 확인 시점 커밋](https://github.com/minbeom77/2026ESWContest_smart_mutjaengideul/blob/6faa228c59ce3ffb432bcda1863dbeda72a73f6e/config/topics.json)

명세 버전은 1.1입니다. 원본 파일은 변경하거나 새 버전으로 복사하지 않습니다. 연동 작업을 시작할 때 최신 합의 버전을 다시 확인합니다.

| 항목 | 침실 | 화장실 |
| --- | --- | --- |
| Topic | safehub/csi/bedroom/event | safehub/csi/bathroom/event |
| QoS | 1 | 1 |
| retain | false | false |
| 명세상 publisher | ESP32_BEDROOM | ESP32_BATHROOM |
| subscriber | RPi5 | RPi5 |

공통 JSON Key와 자료형:

| Key | 명세 |
| --- | --- |
| message_id | UUID 문자열 |
| device | 문자열 |
| event | 문자열 |
| confidence | 0~1 실수 |
| priority | 1~10 정수 |
| timestamp | Unix timestamp 정수 |

이번 변경에는 MQTT 전송 코드나 새 payload를 추가하지 않습니다. 따라서 Topic·Key·QoS·retain 변경이 없습니다.

## 팀 협의가 필요한 다음 단계

- 실제 추론을 수행하는 Pi와 명세상 ESP32 publisher/device 이름을 어떻게 대응할지 확인합니다.
- 사용자 정의 행동 이름을 허용된 event 값으로 어떻게 매핑할지 결정합니다.
- 모델 점수 confidence의 전달 조건, priority, 반복 이벤트 억제·message_id 정책을 정합니다. 모델 점수는 현장 정답 확률과 동일하지 않습니다.
- 사용 환경의 공통 Python 버전과 의존성 버전을 확인합니다.
- 전송기·수신기·수신 GUI를 Dummy Data로 검사한 뒤 실제 장비로 검사합니다.

현재는 MQTT 발행이 없으므로 학습 중인 불확실한 결과가 팀의 실제 경보 시스템으로 전송되지 않습니다.

## 기존 검증 환경

이 모듈은 Windows Python 3.12에서 검사했습니다. 정확한 기존 버전은 WiFi-CSI-Sensing/requirements.txt에 있습니다. 다른 팀 모듈의 requirements를 덮어쓰거나 루트에 하나로 합치지 않습니다.

형식 검사는 개발 도구 Ruff 0.16.7로 수행합니다. 앱 실행 의존성에는 추가하지 않습니다. 팀의 공용 개발 도구 채택 여부는 리뷰에서 확인합니다.
