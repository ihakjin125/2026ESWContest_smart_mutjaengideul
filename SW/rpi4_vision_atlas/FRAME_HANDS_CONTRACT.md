# FrameHands Interface Contract

이 문서는 RPi4 C++ vision frontend와 수어 분류 runtime 사이의 프레임 전달 규격을 정의한다.

## 1. Pipeline boundary

```text
Camera/OpenCV -> Palm/HandPose ONNX -> JSONL/FrameHands -> RecordingFrames -> classifier
```

C++ frontend는 원본 이미지 좌표계의 21개 손 landmark를 전달한다. 분류기는 Palm box, ROI 또는 ONNX raw tensor를 다시 계산하지 않는다.

## 2. JSONL frame format

JSONL 한 줄은 카메라 프레임 하나다. 필수 최상위 필드는 다음과 같다.

```json
{
  "mirror_input": false,
  "image_size_wh": [640, 480],
  "hands": []
}
```

- `mirror_input`: JSON boolean이어야 한다.
- `image_size_wh`: 양수인 `[width, height]` 정수 2개다.
- `hands`: JSON array다. 손이 없으면 빈 배열을 사용한다.
- 한 recording 안에서는 `mirror_input`과 `image_size_wh`가 모든 프레임에서 같아야 한다.
- 현재 producer는 프레임당 최대 두 손을 출력한다.

손 하나의 축약 형식은 다음과 같다. 실제 `landmarks_xy`에는 21개 좌표가 들어간다.

```json
{
  "anchor_index": 388,
  "palm_score": 0.869172,
  "hand_confidence": 0.992017,
  "handedness_raw": 0.734448,
  "model_hand": "RIGHT",
  "physical_hand": "LEFT",
  "landmarks_xy": [[100.0, 200.0]],
  "world_chirality": 0.001
}
```

- `hand_confidence`와 `handedness_raw`는 유한한 `0.0..1.0` 값이어야 한다.
- `landmarks_xy`는 정확히 21개의 `[x, y]`, 즉 shape `(21, 2)`여야 한다.
- `landmarks_xy`는 ROI 좌표가 아니라 원본 이미지의 pixel 좌표다.
- 모든 landmark 값은 유한해야 한다. adapter는 이미지 경계로 clamp하지 않는다.
- `model_hand`와 `physical_hand`는 생략 가능하지만, 있으면 계산값과 정확히 일치해야 한다.
- 나머지 진단 필드는 classifier 입력에 필수는 아니다.

## 3. Handedness rule

MediaPipe 계열 모델의 handedness와 실제 사람 기준 손은 반대로 매핑한다.

| `handedness_raw` | `model_hand` | `physical_hand` |
|---:|---|---|
| `> 0.5` | `RIGHT` | `LEFT` |
| `<= 0.5` | `LEFT` | `RIGHT` |

분류기의 LEFT/RIGHT slot에는 반드시 `physical_hand` 기준으로 넣는다. 선언된 문자열과 `handedness_raw`가 다르면 입력 오류로 거부한다.

## 4. FrameHands output

Python reference adapter의 프레임 출력은 다음 tuple이다.

```python
(left_xy, right_xy)
```

- 각 slot은 `None` 또는 float32 shape `(21, 2)`다.
- LEFT slot은 실제 사람의 왼손, RIGHT slot은 실제 사람의 오른손이다.
- 양손이 같은 physical slot으로 겹치면 `hand_confidence`가 높은 검출을 사용한다.
- 입력 순서는 recording 순서대로 유지한다.

## 5. Recording stabilization

모든 유효 프레임에 손이 최대 하나라면 recording 전체를 single-hand track으로 처리한다.

1. 손이 검출된 프레임들의 `handedness_raw` median을 계산한다.
2. median으로 recording 전체의 physical side 하나를 결정한다.
3. 순간적인 `0.5` 경계 통과 때문에 LEFT/RIGHT slot이 바뀌지 않게 한다.
4. 손이 검출되지 않은 프레임은 recording feature 입력에서 제외한다.

두 손이 등장한 recording은 각 프레임에서 physical side별 최고 confidence 검출을 선택한다. 손이 하나도 없는 프레임은 제외한다.

## 6. Rejection conditions

다음 입력은 `FrameHandsError`로 거부한다.

- `mirror_input`이 boolean이 아님
- `image_size_wh`가 유효한 양의 정수 쌍이 아님
- recording 도중 mirror 또는 image size가 변경됨
- `hands`가 array가 아님
- 손 객체의 필수 필드 누락
- confidence/handedness가 범위를 벗어나거나 NaN/Inf
- landmark shape가 `(21, 2)`가 아니거나 NaN/Inf 포함
- 선언된 `model_hand` 또는 `physical_hand`가 raw handedness와 불일치

예전 `mirror_*` fixture처럼 메타데이터와 raw handedness가 충돌하는 파일은 자동 보정하지 않고 거부한다.

## 7. C++ parity requirement

학진이의 C++ `RecordingFrames` 구현은 같은 JSONL에 대해 Python `frame_hands_adapter.py`와 동일한 LEFT/RIGHT 배치, 프레임 수, landmark 순서를 출력해야 한다. 그 다음 Feature V3, C4 gate, 15-class 결과를 Python reference와 비교한다.
