# 실행과 빌드

Windows 10/11 64비트, Python 3.12에서 개발·패키징합니다. 경로는 저장소 루트 기준입니다.

## 소스 실행

PowerShell에서:

~~~powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
~~~

소스 실행 데이터는 data-v2에 저장합니다. WIFI_SENSING2_DATA_DIR 환경 변수로 다른 폴더를 지정할 수 있습니다. 실행 파일은 자신의 옆에 WifiSensing2.0-data를 만듭니다.

## 자동 검사

실제 USB 보드를 사용하지 않고 임시 폴더와 생성한 합성 CSI로 검사합니다.

~~~powershell
New-Item -ItemType Directory -Force test-results | Out-Null
$env:QT_QPA_PLATFORM = 'offscreen'
$env:WIFI_SENSING2_DATA_DIR = "$PWD\test-results\isolated-data"
.\.venv\Scripts\python.exe app.py --self-test test-results\source.json
Remove-Item Env:QT_QPA_PLATFORM
Remove-Item Env:WIFI_SENSING2_DATA_DIR
~~~

PASS 여부와 검사 수가 JSON에 저장됩니다. 실패 시 같은 파일에 오류가 기록됩니다. 이 검사는 실제 행동 인식 정확도를 측정하지 않습니다.

## Windows 실행 파일 생성

~~~powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe build.py
~~~

release/WifiSensing2.0.exe가 생성됩니다. Python을 설치하지 않은 PC에도 배포할 수 있습니다. build.py는 상대 경로를 사용하는 WifiSensing2.0.spec을 실행합니다. 내장 C6 펌웨어, Pi 실행 소스와 라이선스 고지도 포함됩니다.

배포할 때 실행 파일과 시작하기.txt, C6-준비와-실험순서.md, PI-사용방법.md, README.md, ARCHITECTURE.md, NOTICE.md 및 라이선스 파일을 함께 전달하세요. 개인 기록은 포함하지 않습니다. 실행 파일은 용량이 크므로 GitHub Release 첨부 파일로 올리고 소스 커밋에서는 제외합니다.

## C6 펌웨어 재빌드

~~~powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-firmware.txt
.\.venv\Scripts\python.exe -m platformio run -d firmware-c6
.\.venv\Scripts\python.exe firmware-c6\package_firmware.py
~~~

환경은 espressif32@6.10.0, ESP-IDF 5.4 계열, esp_csi_gain_ctrl 0.1.5입니다. 두 역할을 모두 빌드한 다음 병합 바이너리와 SHA-256 manifest를 생성합니다. 이후 앱도 다시 빌드해야 새 펌웨어가 실행 파일에 포함됩니다.

빌드 폴더를 별도로 지정했다면 package_firmware.py --build-dir 경로를 전달합니다. 패키징 명령은 보드에 쓰지 않습니다. 실제 설치는 앱의 C6 설치기를 사용합니다.

firmware/에는 공유기 방식 ESP32·C3 소스가 있습니다. 이 폴더의 기존 설정은 플래시 8MB이므로 사용할 보드의 종류·플래시 크기·USB 방식에 맞춰 설정을 확인한 후 빌드해야 합니다. C3에 C6 바이너리를 사용하지 않습니다.

## GitHub에 올릴 파일

저장소 루트의 소스, 문서, 설정, 라이선스와 firmware-c6/bin의 작은 펌웨어 파일만 올립니다. .gitignore는 가상환경·개인 수집 기록·모델·로그·보드 백업·빌드 결과·실행 파일을 제외합니다. 이 폴더에는 원본 참고 저장소나 개인 실험 데이터가 필요하지 않습니다.
