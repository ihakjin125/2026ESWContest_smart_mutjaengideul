# RPi4 C++ Vision Frontend

이 디렉터리는 Raspberry Pi 4에서 카메라 프레임을 손 landmark로 변환하는 C++ frontend를 관리한다.

## Scope

```text
Camera frame
-> Palm ONNX preprocessing/inference
-> anchor decode and NMS
-> rotated hand ROI
-> HandPose ONNX
-> 21 landmarks in original image coordinates
-> FrameHands / RecordingFrames
```

Feature V3, SIGN/NO-SIGN gate, 15-class classifier는 별도 classifier runtime의 책임이다.

## Deterministic regression

전체 frontend 수치 회귀 검사는 다음 한 줄로 실행한다.

```bash
SW/rpi4_vision_atlas/tests/run_frontend_regression.sh
```

스크립트는 임시 디렉터리에 네 checker를 컴파일하고 순서대로 실행한다.

1. `palm_generated_anchor_check`: C++ anchor 생성 및 decode 비교
2. `palm_decode_check`: 저장된 anchor를 사용한 decode/NMS 비교
3. `hand_roi_check`: 회전 ROI와 HandPose 입력 tensor 비교
4. `hand_restore_check`: 21개 landmark의 원본 이미지 좌표 복원 비교

성공 시 마지막에 다음 문구가 출력된다.

```text
PASS: complete C++ vision frontend regression
```

ROI 단계만 검사하려면 다음을 실행한다.

```bash
SW/rpi4_vision_atlas/tests/run_hand_roi_check.sh
```

## Requirements

- Bash
- C++17 compiler (`g++` 또는 `CXX` 환경변수로 지정한 compiler)
- OpenCV 4 development headers and libraries
- `pkg-config opencv4`, 또는 `/usr/include/opencv4`와 시스템 OpenCV libraries

빌드 결과는 임시 디렉터리에 생성되고 실행 후 자동 삭제된다.

## Fixtures

- `tests/fixtures/palm_decode_reference`: Palm anchor/decode/NMS 기준 데이터
- `tests/fixtures/roi_opencv_reference`: ROI와 landmark 복원 기준 데이터

`actual_*` 파일은 checker가 진단용으로 생성하며 Git에서 제외한다.

Python OpenCV 5.0.0과 C++ OpenCV 4.6.0은 보간 반올림 결과가 조금 다를 수 있다. ROI 검사는 기하 정보의 정확한 일치를 요구하면서 다음 raster 오차만 허용한다.

- RGB channel maximum error: 4
- RGB channel mean error: 0.05
- Changed-channel ratio: 4 percent
- Normalized input maximum error: `4/255 + epsilon`

이 허용치는 HandPose 출력 비교에서 confidence와 landmark 변화가 미미함을 확인한 뒤 정했다.

## Remaining live checks

fixture 회귀 검사는 카메라 또는 실제 RPi4 성능을 측정하지 않는다. 최종 장비에서는 Camera1 연속 입력, Palm/HandPose inference FPS, 좌우 손 배치, FrameHands 전달을 별도로 확인해야 한다.
