# Raspberry Pi 4/5 · 수집, 전처리, 추론

64비트 Raspberry Pi OS에서 실행합니다. 모델 학습은 Windows PC에서 합니다.
PC와 동일한 50채널·DWT·PCA 3성분·8 Hz 필터를 사용하며, CNN 추론은 NumPy로 실행하여 PyTorch 설치가 필요 없습니다.
PC에서 수치 일치 검사를 거치지만 실제 Pi의 속도·USB·장시간 운전은 보드에서 확인해야 합니다.

ZIP을 풀고 해당 폴더의 터미널에서:

```sh
sudo apt update
sudo apt install python3-venv
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
sudo usermod -aG dialout "$USER"
```

USB 권한 변경 후 로그아웃/로그인합니다. 수신 보드의 포트는 `ls /dev/serial/by-id/`로 확인합니다.
포트 경로를 아래 `/dev/ttyACM0` 대신 넣으세요. USB-UART 브리지라면 `/dev/ttyUSB0`일 수 있습니다.

```sh
python edge_runtime.py --port /dev/ttyACM0 --model model
```

새 신호의 행동·모델 점수가 JSON으로 출력됩니다. 신호 부족·끊김은 판단 보류입니다. Ctrl+C로 종료합니다.
모델을 수집한 보드 구성과 추론 구성이 같아야 합니다. 기존 공유기+ESP32 모델로 C6 두 대를 판단하지 않습니다.

라벨 기록 수집:

```sh
python edge_runtime.py --port /dev/ttyACM0 --label 정지 --seconds 30 --round roomA-day1-round1
python edge_runtime.py --port /dev/ttyACM0 --label 걷기 --seconds 30 --round roomA-day1-round1
```

pi-records의 `.json` 파일을 PC 앱의 **기록 가져오기**로 가져와 선택·학습합니다. `.jsonl`은 원본 통신 저널입니다.
한 회차에서 모든 행동을 수집하고, 새 회차에서는 움직임을 새로 수행하세요. 같은 파일을 복사하여 회차를 늘리면 평가가 무효가 됩니다.
학습·검증·최종 평가용으로 행동마다 최소 3회차, 실험에는 5~10회차 이상을 권장합니다.
낙상은 전후 전체를 같은 라벨로 묶지 말고 PC에서 실제 동작 구간을 잘라 확인하세요.
