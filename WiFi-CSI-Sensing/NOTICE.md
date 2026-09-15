# 출처 및 변경 사항

WiFi-CSI-Sensing은 멋쟁이들 팀의 Wi-Fi CSI 수집·학습·인식 모듈입니다. Windows 프로그램 이름은 WifiSensing 2.0입니다.

## 참고한 프로젝트

- 원 프로젝트: [Dongbang-Yeuijiguk/2025ESWContest_smart_3019](https://github.com/Dongbang-Yeuijiguk/2025ESWContest_smart_3019)
- 참고 영역: SOOM-AI의 CSI 전처리 흐름과 초기 Simple1DCNN 구성
- 원 저작권: Copyright (c) 2025 Dongbang Yeuijiguk
- 원 라이선스: MIT. 전문은 LICENSE 및 THIRD_PARTY_NOTICES.txt에 보존합니다.

현재의 채널 매핑·DWT 임계값·PCA 성분 수·필터·CNN·평가 분리는 참고 프로젝트와 다릅니다. 이 구현의 성능 검증 범위는 VALIDATION.md에 정리되어 있습니다.

## 현재 구현에서 구성한 부분

- Windows 데스크톱 수집·기록 선택·학습·실시간 인식 UI
- 행동 항목 추가·삭제, 구간 편집, 선택 기록 일괄 삭제·복원
- 물리 채널 50개를 사용하는 관찰·학습·추론 공통 전처리 경로
- 3성분 파형 CNN, 측정 회차별 학습·검증·평가 분리
- ESP32-C6 ESP-NOW 송수신 펌웨어, 칩 확인 및 플래시 백업 설치기
- 라즈베리파이 수집·전처리·NumPy 추론과 모델 내보내기

이 소스 배포본에는 원 프로젝트의 실험 데이터, 사용자의 수집 기록·모델·장치 로그, 현재 사용하지 않는 과거 알고리즘 파일을 포함하지 않습니다. 자동 검사용 CSI는 synthetic_fixture.py가 수학적으로 생성하는 가상 입력입니다.

## 외부 구성 요소

Python, Qt/PySide6, PyTorch, NumPy, SciPy, scikit-learn, PyWavelets, pyqtgraph, pyserial 등은 각각의 저작권과 라이선스를 따릅니다. 관련 고지는 THIRD_PARTY_NOTICES.txt에 있습니다.

C6 설치기는 esptool 4.8.1을 사용합니다. 펌웨어는 ESP-IDF 및 Espressif CSI gain control 구성 요소를 사용합니다. LICENSE-C6.txt와 firmware/ESP-IDF-LICENSE.txt를 함께 배포합니다.
