# 멋쟁이들 · 2026 임베디드소프트웨어 경진대회

제24회 임베디드소프트웨어 경진대회 LG전자 부문 팀 프로젝트 저장소입니다.

## Wi-Fi CSI 센싱 모듈

[WiFi-CSI-Sensing](WiFi-CSI-Sensing/README.md)은 ESP32로 수집한 무선 신호를 관찰하고, 사용자가 선택한 행동 기록으로 모델을 학습하여 새 신호를 판단하는 개발 도구입니다.

- **PC**: Windows 데스크톱 UI, 행동별 수집·구간 편집·기록 선택·CNN 학습
- **ESP32-C6 두 대**: ESP-NOW 송신기·수신기 구성 및 설치 펌웨어
- **라즈베리파이 4/5**: CSI 수집·전처리·NumPy 추론 실행 소스

실제 C6 두 대의 통신과 Pi 성능, 현장 행동 정확도는 추가 검증이 필요합니다. 현재 자동 검사는 하드웨어 없이 합성 CSI로 소프트웨어 기능을 확인합니다.

| 문서 | 내용 |
| --- | --- |
| [모듈 시작하기](WiFi-CSI-Sensing/README.md) | 수집 → 기록 선택 → 학습 → 실시간 인식 |
| [실행·빌드](WiFi-CSI-Sensing/BUILDING.md) | Python 환경, 실행 파일 생성, 자동 검사 |
| [전처리·학습 구조](WiFi-CSI-Sensing/ARCHITECTURE.md) | 50채널, DWT·PCA·저역 통과, CNN |
| [팀 시스템 연동 범위](docs/wifi-csi/INTEGRATION.md) | 기존 MQTT 명세 및 후속 협의 항목 |
| [작업 기록](docs/wifi-csi/WORKLOG.md) | 변경 사항, 검증 결과, 다음 작업 |
| [협업 규칙](CONTRIBUTING.md) | 개인 fork·feature 브랜치·PR 제출 |

## 실행

소스 실행 명령은 WiFi-CSI-Sensing 폴더 안에서 실행합니다. 자세한 환경 설정은 모듈의 BUILDING.md를 따르세요. 이 모듈에서 검사한 Python은 3.12이며 팀 전체의 공통 버전은 별도 확인이 필요합니다.

기존 feature/HW의 ESP32 실험 도구와 이 모듈은 별개 폴더로 유지합니다. 이번 변경은 기존 HW/SW 브랜치를 합치거나 덮어쓰지 않습니다.

## 팀 통신 규격

MQTT 기준은 develop의 config/topics.json입니다. 현재 CSI 모듈에는 MQTT 발행 기능이 포함되어 있지 않습니다. 연동 시 기존 Topic·JSON Key·자료형·QoS·retain을 유지하고, 정의되지 않은 항목은 팀 협의 후 문서와 함께 반영합니다.

출처·저작권 및 외부 라이선스는 [모듈 NOTICE](WiFi-CSI-Sensing/NOTICE.md)와 해당 라이선스 파일에서 확인합니다.
