import os
import sys

import cv2
try:
    import mediapipe as mp
except ModuleNotFoundError:
    mp = None
import numpy as np

import hand_features as hf

# 최종?
# ============================================================
# 경로
# ============================================================

BASE_DIR = os.path.dirname(
    os.path.abspath(__file__)
)

TEMPLATE_PATH = os.path.join(
    BASE_DIR,
    "template_runtime_v3",
    "05n_local_templates_train.npz",
)


# ============================================================
# 클래스
# ============================================================

CLASS_INFO = {
    0: ("에어컨", "WORD0128", "two_hand"),
    1: ("문잠그다", "WORD0527", "two_hand"),
    2: ("꺼지다", "WORD2353", "one_hand"),
    3: ("덥다", "WORD1382", "two_hand"),
    4: ("춥다", "WORD1248", "two_hand"),
    5: ("구조", "WORD1588", "two_hand"),
    6: ("연기", "WORD1570", "two_hand"),
    7: ("아프다", "WORD1152", "one_hand"),
    8: ("괜찮다", "WORD1381", "one_hand"),
    9: ("감사", "WORD1290", "two_hand"),
}


ONE_HAND_IDS = [
    2,  # 2353 꺼지다
    7,  # 1152 아프다
    8,  # 1381 괜찮다
]


TWO_HAND_IDS = [
    0,  # 0128 에어컨
    1,  # 0527 문잠그다
    3,  # 1382 덥다
    4,  # 1248 춥다
    5,  # 1588 구조
    6,  # 1570 연기
    9,  # 1290 감사
]


# ============================================================
# 설정
# ============================================================

TARGET_FRAMES = 80

FULL_FEATURE_DIM = 172
LOCAL_DIM = 84

K = 3

ONE_HAND_RATIO_THRESHOLD = 0.20

# no-sign은 아직 별도 문제
WEBCAM_NO_MOTION_THRESHOLD = 0.0

ANCHOR_FRAME_COUNT = 5
CANONICAL_HAND = "RIGHT"

CAMERA_INDEX = 0

MIN_ACCEPTED_FRAMES = 20

# 기존 06a / 06f / 06g와 동일
BOTH_FRAME_RATIO_THRESHOLD = 0.35


# ============================================================
# 파일 확인
# ============================================================

if not os.path.exists(
    TEMPLATE_PATH
):
    print(
        f"[ERROR] Template 파일 없음:"
    )

    print(
        TEMPLATE_PATH
    )

    sys.exit(1)


# ============================================================
# Temporal resampling
# ============================================================

def temporal_resample(
    sequence,
    target_frames=TARGET_FRAMES,
):

    sequence = np.asarray(
        sequence,
        dtype=np.float32,
    )


    if sequence.ndim != 2:

        raise ValueError(
            f"sequence ndim 오류: "
            f"{sequence.shape}"
        )


    original_frames = (
        sequence.shape[0]
    )

    feature_dim = (
        sequence.shape[1]
    )


    if original_frames < 2:

        raise ValueError(
            f"프레임 부족: "
            f"{original_frames}"
        )


    if (
        original_frames
        ==
        target_frames
    ):

        return sequence.copy()


    old_x = np.linspace(
        0.0,
        1.0,
        original_frames,
        dtype=np.float64,
    )


    new_x = np.linspace(
        0.0,
        1.0,
        target_frames,
        dtype=np.float64,
    )


    output = np.empty(
        (
            target_frames,
            feature_dim,
        ),
        dtype=np.float32,
    )


    for dim in range(
        feature_dim
    ):

        output[
            :,
            dim
        ] = np.interp(
            new_x,
            old_x,
            sequence[
                :,
                dim
            ],
        )


    return output


# ============================================================
# Template load
# ============================================================

def load_templates():

    data = np.load(
        TEMPLATE_PATH,
        allow_pickle=True,
    )


    required = {
        "local_templates",
        "class_ids",
        "real_ids",
        "usage_types",
        "target_frames",
        "feature_dim",
        "k",
    }


    missing = (
        required
        -
        set(
            data.files
        )
    )


    if missing:

        raise RuntimeError(
            f"Template key 부족: "
            f"{missing}"
        )


    templates = np.asarray(
        data[
            "local_templates"
        ],
        dtype=np.float32,
    )


    class_ids = np.asarray(
        data[
            "class_ids"
        ],
        dtype=np.int64,
    )


    real_ids = np.asarray(
        data[
            "real_ids"
        ]
    ).astype(str)


    usage_types = np.asarray(
        data[
            "usage_types"
        ]
    ).astype(str)


    target_frames = int(
        np.asarray(
            data[
                "target_frames"
            ]
        ).reshape(-1)[0]
    )


    feature_dim = int(
        np.asarray(
            data[
                "feature_dim"
            ]
        ).reshape(-1)[0]
    )


    saved_k = int(
        np.asarray(
            data[
                "k"
            ]
        ).reshape(-1)[0]
    )


    print()
    print("=" * 110)
    print(
        "LOCAL TEMPLATE"
    )
    print("=" * 110)


    print(
        "Path      :",
        TEMPLATE_PATH,
    )


    print(
        "Templates :",
        templates.shape,
    )


    print(
        "Class ids :",
        class_ids.shape,
    )


    print(
        "Frames    :",
        target_frames,
    )


    print(
        "Feature   :",
        feature_dim,
    )


    print(
        "K         :",
        saved_k,
    )


    if templates.shape != (
        len(
            class_ids
        ),
        TARGET_FRAMES,
        LOCAL_DIM,
    ):

        raise RuntimeError(
            f"Template shape 오류: "
            f"{templates.shape}"
        )


    if target_frames != TARGET_FRAMES:

        raise RuntimeError(
            "target_frames 불일치"
        )


    if feature_dim != LOCAL_DIM:

        raise RuntimeError(
            "feature_dim 불일치"
        )


    if saved_k != K:

        raise RuntimeError(
            f"K 불일치: "
            f"{saved_k}"
        )


    if not np.all(
        np.isfinite(
            templates
        )
    ):

        raise RuntimeError(
            "Template NaN/Inf"
        )


    print(
        "Finite    : PASS"
    )


    print()
    print(
        "Class distribution:"
    )


    for class_id in range(
        10
    ):

        label, word, usage = (
            CLASS_INFO[
                class_id
            ]
        )


        count = int(
            np.sum(
                class_ids
                ==
                class_id
            )
        )


        print(
            f"  {word[-4:]} "
            f"{label:<8} "
            f"{usage:<9} "
            f": {count}"
        )


    return {
        "templates":
            templates,

        "class_ids":
            class_ids,

        "real_ids":
            real_ids,

        "usage_types":
            usage_types,
    }


# ============================================================
# MediaPipe → AI Hub coordinate bridge
# ============================================================

def landmarks_to_aihub_xy(
    hand_landmarks,
    width,
    height,
):

    points = []


    for landmark in (
        hand_landmarks.landmark
    ):

        # 화면 자체는 mirror 상태.
        # 기존 v3 bridge와 동일하게
        # AI Hub 방향으로 x 복원.
        x = (
            1.0
            -
            float(
                landmark.x
            )
        ) * float(
            width
        )


        y = (
            float(
                landmark.y
            )
            *
            float(
                height
            )
        )


        points.append(
            [
                x,
                y,
            ]
        )


    return np.asarray(
        points,
        dtype=np.float32,
    )


def extract_hands(
    results,
    width,
    height,
):

    detected = {}


    if (
        results.multi_hand_landmarks
        is None
        or
        results.multi_handedness
        is None
    ):

        return detected


    for (
        hand_landmarks,
        handedness,
    ) in zip(
        results.multi_hand_landmarks,
        results.multi_handedness,
    ):

        classification = (
            handedness
            .classification[0]
        )


        label = (
            classification
            .label
            .upper()
        )


        confidence = float(
            classification.score
        )


        if label not in (
            "LEFT",
            "RIGHT",
        ):

            continue


        xy = landmarks_to_aihub_xy(
            hand_landmarks,
            width,
            height,
        )


        if (
            label not in detected
            or
            confidence
            >
            detected[
                label
            ]["confidence"]
        ):

            detected[
                label
            ] = {
                "xy":
                    xy,

                "confidence":
                    confidence,
            }


    return detected


# ============================================================
# RMSE classifier
# ============================================================

def calculate_distances(
    query,
    templates,
):

    # query:
    # (80, 84)
    #
    # templates:
    # (67, 80, 84)

    diff = (
        templates
        -
        query[
            None,
            ...
        ]
    )


    distances = np.sqrt(
        np.mean(
            diff ** 2,
            axis=(1, 2),
        )
    )


    return distances


def get_allowed_classes(
    usage_type,
):

    if usage_type == (
        "one_hand"
    ):

        return (
            ONE_HAND_IDS.copy()
        )


    if usage_type == (
        "two_hand"
    ):

        return (
            TWO_HAND_IDS.copy()
        )


    raise RuntimeError(
        f"알 수 없는 usage type: "
        f"{usage_type}"
    )


def predict_template(
    query,
    usage_type,
    template_data,
):

    templates = (
        template_data[
            "templates"
        ]
    )


    class_ids = (
        template_data[
            "class_ids"
        ]
    )


    real_ids = (
        template_data[
            "real_ids"
        ]
    )


    distances = (
        calculate_distances(
            query,
            templates,
        )
    )


    allowed_classes = (
        get_allowed_classes(
            usage_type
        )
    )


    ranking = []


    for class_id in (
        allowed_classes
    ):

        indices = np.where(
            class_ids
            ==
            class_id
        )[0]


        if len(
            indices
        ) < K:

            raise RuntimeError(
                f"class {class_id} "
                f"template 수가 "
                f"K={K}보다 적음"
            )


        class_distances = (
            distances[
                indices
            ]
        )


        order = np.argsort(
            class_distances
        )


        top_k_local = (
            order[
                :K
            ]
        )


        top_k_distances = (
            class_distances[
                top_k_local
            ]
        )


        class_score = float(
            np.mean(
                top_k_distances
            )
        )


        nearest_global = int(
            indices[
                top_k_local[0]
            ]
        )


        nearest_real = str(
            real_ids[
                nearest_global
            ]
        )


        top_k_reals = []


        for local_index in (
            top_k_local
        ):

            global_index = int(
                indices[
                    local_index
                ]
            )


            top_k_reals.append(
                {
                    "real":
                        str(
                            real_ids[
                                global_index
                            ]
                        ),

                    "distance":
                        float(
                            distances[
                                global_index
                            ]
                        ),
                }
            )


        ranking.append(
            {
                "class_id":
                    int(
                        class_id
                    ),

                "score":
                    class_score,

                "nearest_real":
                    nearest_real,

                "top_k":
                    top_k_reals,
            }
        )


    ranking.sort(
        key=lambda item:
        item[
            "score"
        ]
    )


    pred_id = int(
        ranking[
            0
        ]["class_id"]
    )


    return (
        pred_id,
        ranking,
    )


# ============================================================
# Ranking 출력
# ============================================================

def print_ranking(
    ranking,
):

    print()
    print("=" * 125)
    print(
        "LOCAL TEMPLATE PREDICTION"
    )
    print("=" * 125)


    print(
        f"{'RANK':<7}"
        f"{'CLASS':<18}"
        f"{'SCORE':>14}"
        f"{'NEAREST REAL':>18}"
    )


    print("-" * 125)


    for rank, item in enumerate(
        ranking,
        start=1,
    ):

        class_id = (
            item[
                "class_id"
            ]
        )


        label, word, usage = (
            CLASS_INFO[
                class_id
            ]
        )


        class_text = (
            f"{word[-4:]} "
            f"{label}"
        )


        print(
            f"{rank:<7}"
            f"{class_text:<18}"
            f"{item['score']:>14.6f}"
            f"{item['nearest_real']:>18}"
        )


    print()
    print(
        "※ SCORE는 RMSE 거리입니다."
    )


    print(
        "※ 낮을수록 template와 더 가깝습니다."
    )


# ============================================================
# Main
# ============================================================

def main():

    print()
    print("=" * 110)
    print(
        "06j WEBCAM LOCAL TEMPLATE"
    )
    print("=" * 110)


    print(
        "[최종 런타임 후보 / 웹캠 검증 중]"
    )


    print()
    print(
        "Classifier:"
    )


    print(
        "  RAW Local 84-dim"
    )


    print(
        "  K = 3"
    )


    print(
        "  nearest 3 REAL RMSE mean"
    )


    print(
        "  usage-gated"
    )


    print()
    print(
        "Not used:"
    )


    print(
        "  TFLite / GRU"
    )


    print(
        "  Scaler"
    )


    print(
        "  Pair"
    )


    print(
        "  Trajectory"
    )


    print()
    print(
        "첫 테스트 대상: 1248 춥다"
    )


    # ========================================================
    # Template
    # ========================================================

    template_data = (
        load_templates()
    )


    # ========================================================
    # MediaPipe
    # ========================================================

    mp_hands = (
        mp.solutions.hands
    )


    mp_draw = (
        mp.solutions
        .drawing_utils
    )


    hands = mp_hands.Hands(
        static_image_mode=False,
        max_num_hands=2,
        min_detection_confidence=0.5,
        min_tracking_confidence=0.5,
    )


    # ========================================================
    # Webcam
    # ========================================================

    cap = cv2.VideoCapture(
        CAMERA_INDEX
    )


    if not cap.isOpened():

        raise RuntimeError(
            "웹캠을 열 수 없습니다."
        )


    recording = False

    recording_frames = []


    print()
    print("=" * 110)
    print("WEBCAM")
    print("=" * 110)


    print(
        "S : 녹화 시작"
    )


    print(
        "E : 녹화 종료 + 추론"
    )


    print(
        "Q : 종료"
    )


    while True:

        ret, frame = (
            cap.read()
        )


        if not ret:

            print(
                "[ERROR] "
                "frame read 실패"
            )

            break


        frame = cv2.flip(
            frame,
            1,
        )


        height, width = (
            frame.shape[
                :2
            ]
        )


        rgb = cv2.cvtColor(
            frame,
            cv2.COLOR_BGR2RGB,
        )


        results = hands.process(
            rgb
        )


        detected = extract_hands(
            results,
            width,
            height,
        )


        left_xy = None

        right_xy = None


        if "LEFT" in detected:

            left_xy = (
                detected[
                    "LEFT"
                ]["xy"]
            )


        if "RIGHT" in detected:

            right_xy = (
                detected[
                    "RIGHT"
                ]["xy"]
            )


        # ----------------------------------------------------
        # Landmark 표시
        # ----------------------------------------------------

        if (
            results
            .multi_hand_landmarks
        ):

            for hand_landmarks in (
                results
                .multi_hand_landmarks
            ):

                mp_draw.draw_landmarks(
                    frame,
                    hand_landmarks,
                    mp_hands
                    .HAND_CONNECTIONS,
                )


        # ----------------------------------------------------
        # Recording
        # ----------------------------------------------------

        if recording:

            if (
                left_xy is not None
                or
                right_xy is not None
            ):

                recording_frames.append(
                    (
                        left_xy,
                        right_xy,
                    )
                )


            cv2.putText(
                frame,
                "RECORDING",
                (
                    20,
                    40,
                ),
                cv2.FONT_HERSHEY_SIMPLEX,
                1.0,
                (
                    0,
                    0,
                    255,
                ),
                2,
            )


            cv2.putText(
                frame,
                f"Frames: "
                f"{len(recording_frames)}",
                (
                    20,
                    80,
                ),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (
                    0,
                    0,
                    255,
                ),
                2,
            )


        else:

            cv2.putText(
                frame,
                "LOCAL TEMPLATE",
                (
                    20,
                    40,
                ),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (
                    255,
                    255,
                    255,
                ),
                2,
            )


            cv2.putText(
                frame,
                "S=start E=end Q=quit",
                (
                    20,
                    80,
                ),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (
                    255,
                    255,
                    255,
                ),
                2,
            )


        cv2.imshow(
            "06j Local Template",
            frame,
        )


        key = (
            cv2.waitKey(1)
            &
            0xFF
        )


        # ----------------------------------------------------
        # Q
        # ----------------------------------------------------

        if key in (
            ord("q"),
            ord("Q"),
        ):

            break


        # ----------------------------------------------------
        # S
        # ----------------------------------------------------

        if key in (
            ord("s"),
            ord("S"),
        ):

            recording_frames = []

            recording = True


            print()
            print("=" * 110)
            print(
                ">>> RECORDING START"
            )
            print("=" * 110)


        # ----------------------------------------------------
        # E
        # ----------------------------------------------------

        if key in (
            ord("e"),
            ord("E"),
        ):

            if not recording:

                continue


            recording = False


            print()
            print("=" * 110)
            print(
                ">>> RECORDING END"
            )
            print("=" * 110)


            break


    cap.release()

    cv2.destroyAllWindows()

    hands.close()


    # ========================================================
    # Capture statistics
    # ========================================================

    if len(
        recording_frames
    ) == 0:

        print(
            "[ERROR] "
            "녹화 프레임 없음"
        )

        return


    total_frames = len(
        recording_frames
    )


    left_count = sum(
        left is not None

        for left, right
        in recording_frames
    )


    right_count = sum(
        right is not None

        for left, right
        in recording_frames
    )


    both_count = sum(
        (
            left is not None
            and
            right is not None
        )

        for left, right
        in recording_frames
    )


    both_ratio = (
        both_count
        /
        total_frames
    )


    print()
    print("=" * 110)
    print("CAPTURE")
    print("=" * 110)


    print(
        "Hand frames    :",
        total_frames,
    )


    print(
        "Both detected  :",
        both_count,
    )


    print(
        "Left detected  :",
        left_count,
    )


    print(
        "Right detected :",
        right_count,
    )


    print(
        f"Both ratio     : "
        f"{both_ratio:.3f}"
    )


    # ========================================================
    # Source 선택
    # ========================================================
    #
    # 기존 06a/06f 방식 유지.
    #
    # 양손 비율이 충분하면:
    #   simultaneous two-hand frames만 사용
    #
    # 아니면:
    #   더 많이 검출된 한 손을 사용
    #
    # ========================================================

    if (
        both_ratio
        >=
        BOTH_FRAME_RATIO_THRESHOLD
    ):

        source_mode = (
            "BOTH_ALIGNED"
        )


        selected = [
            (
                left,
                right,
            )

            for left, right
            in recording_frames

            if (
                left is not None
                and
                right is not None
            )
        ]


        if len(
            selected
        ) < MIN_ACCEPTED_FRAMES:

            print(
                "[ABORT] "
                "BOTH_ALIGNED 프레임 부족:"
            )

            print(
                len(
                    selected
                )
            )

            return


        left_sequence = np.stack(
            [
                left

                for left, right
                in selected
            ],
            axis=0,
        )


        right_sequence = np.stack(
            [
                right

                for left, right
                in selected
            ],
            axis=0,
        )


    else:

        if (
            right_count
            >=
            left_count
        ):

            source_mode = (
                "ONE_RIGHT"
            )


            selected = [
                right

                for left, right
                in recording_frames

                if right is not None
            ]


            if len(
                selected
            ) < MIN_ACCEPTED_FRAMES:

                print(
                    "[ABORT] "
                    "RIGHT 프레임 부족"
                )

                return


            left_sequence = None


            right_sequence = (
                np.stack(
                    selected,
                    axis=0,
                )
            )


        else:

            source_mode = (
                "ONE_LEFT"
            )


            selected = [
                left

                for left, right
                in recording_frames

                if left is not None
            ]


            if len(
                selected
            ) < MIN_ACCEPTED_FRAMES:

                print(
                    "[ABORT] "
                    "LEFT 프레임 부족"
                )

                return


            left_sequence = (
                np.stack(
                    selected,
                    axis=0,
                )
            )


            right_sequence = None


    print(
        "Source mode    :",
        source_mode,
    )


    if (
        source_mode
        ==
        "BOTH_ALIGNED"
    ):

        print(
            "Selected frames:",
            left_sequence.shape[0],
        )


    elif (
        left_sequence
        is not None
    ):

        print(
            "Selected frames:",
            left_sequence.shape[0],
        )


    else:

        print(
            "Selected frames:",
            right_sequence.shape[0],
        )


    # ========================================================
    # Feature v3
    # ========================================================

    feature_result = (
        hf.build_feature_v3(
            left_sequence=(
                left_sequence
            ),

            right_sequence=(
                right_sequence
            ),

            one_hand_ratio_threshold=(
                ONE_HAND_RATIO_THRESHOLD
            ),

            no_motion_threshold=(
                WEBCAM_NO_MOTION_THRESHOLD
            ),

            anchor_frame_count=(
                ANCHOR_FRAME_COUNT
            ),

            canonical_hand=(
                CANONICAL_HAND
            ),
        )
    )


    if not feature_result[
        "valid"
    ]:

        print(
            "[ERROR] "
            "Feature v3 invalid"
        )

        return


    usage_type = str(
        feature_result[
            "usage"
        ]["type"]
    )


    print()
    print("=" * 110)
    print("FEATURE V3")
    print("=" * 110)


    print(
        "Usage type    :",
        usage_type,
    )


    print(
        "Detected mask :",
        feature_result[
            "detected_mask"
        ],
    )


    print(
        "Usage mask    :",
        feature_result[
            "usage_mask"
        ],
    )


    print(
        "Left score    :",
        feature_result[
            "usage"
        ].get(
            "left_score"
        ),
    )


    print(
        "Right score   :",
        feature_result[
            "usage"
        ].get(
            "right_score"
        ),
    )


    print(
        "Ratio         :",
        feature_result[
            "usage"
        ].get(
            "ratio"
        ),
    )


    feature_172 = np.asarray(
        feature_result[
            "features"
        ],
        dtype=np.float32,
    )


    if (
        feature_172.ndim
        !=
        2
        or
        feature_172.shape[1]
        !=
        FULL_FEATURE_DIM
    ):

        raise RuntimeError(
            f"Feature shape 오류: "
            f"{feature_172.shape}"
        )


    print(
        "Raw feature   :",
        feature_172.shape,
    )


    # ========================================================
    # 80 frame resample
    # ========================================================

    feature_80 = (
        temporal_resample(
            feature_172,
            TARGET_FRAMES,
        )
    )


    print(
        "Resampled     :",
        feature_80.shape,
    )


    # ========================================================
    # Local 84 only
    # ========================================================

    local_feature = (
        feature_80[
            :,
            0:LOCAL_DIM
        ].copy()
    )


    print()
    print("=" * 110)
    print(
        "LOCAL FEATURE"
    )
    print("=" * 110)


    print(
        "Shape  :",
        local_feature.shape,
    )


    print(
        "Finite :",
        bool(
            np.all(
                np.isfinite(
                    local_feature
                )
            )
        ),
    )


    if local_feature.shape != (
        TARGET_FRAMES,
        LOCAL_DIM,
    ):

        raise RuntimeError(
            f"Local shape 오류: "
            f"{local_feature.shape}"
        )


    if not np.all(
        np.isfinite(
            local_feature
        )
    ):

        raise RuntimeError(
            "Local NaN/Inf"
        )


    # ========================================================
    # Template classification
    # ========================================================

    (
        pred_id,
        ranking,
    ) = predict_template(
        query=(
            local_feature
        ),

        usage_type=(
            usage_type
        ),

        template_data=(
            template_data
        ),
    )


    print_ranking(
        ranking
    )


    # ========================================================
    # 결과
    # ========================================================

    pred_label, pred_word, _ = (
        CLASS_INFO[
            pred_id
        ]
    )


    top1_score = float(
        ranking[
            0
        ]["score"]
    )


    if len(
        ranking
    ) >= 2:

        top2_score = float(
            ranking[
                1
            ]["score"]
        )


        margin = (
            top2_score
            -
            top1_score
        )

    else:

        top2_score = None

        margin = None


    print()
    print("=" * 125)
    print(
        "TOP-1 TEMPLATE DETAIL"
    )
    print("=" * 125)


    print(
        f"Class   : "
        f"{pred_word[-4:]} "
        f"{pred_label}"
    )


    print(
        f"Score   : "
        f"{top1_score:.6f}"
    )


    print(
        f"Nearest : "
        f"{ranking[0]['nearest_real']}"
    )


    print()
    print(
        f"Nearest {K} REAL:"
    )


    for index, item in enumerate(
        ranking[
            0
        ]["top_k"],
        start=1,
    ):

        print(
            f"  {index}. "
            f"{item['real']} "
            f"| "
            f"{item['distance']:.6f}"
        )


    print()
    print("=" * 125)
    print(
        "06j RESULT"
    )
    print("=" * 125)


    print(
        "Source mode :",
        source_mode,
    )


    print(
        "Usage type  :",
        usage_type,
    )


    print(
        f"TOP-1       : "
        f"{pred_word[-4:]} "
        f"{pred_label}"
    )


    print(
        f"Score       : "
        f"{top1_score:.6f}"
    )


    if margin is not None:

        print(
            f"TOP1/TOP2 margin : "
            f"{margin:.6f}"
        )


    print()
    print(
        "TOP-3:"
    )


    for rank, item in enumerate(
        ranking[
            :3
        ],
        start=1,
    ):

        class_id = (
            item[
                "class_id"
            ]
        )


        label, word, usage = (
            CLASS_INFO[
                class_id
            ]
        )


        print(
            f"{rank}. "
            f"{word[-4:]} "
            f"{label:<8} "
            f"| score "
            f"{item['score']:.6f} "
            f"| nearest "
            f"{item['nearest_real']}"
        )


    print()
    print(
        "※ score는 confidence가 아니라 RMSE 거리입니다."
    )


    print(
        "※ 낮을수록 TRAIN template와 유사합니다."
    )


    print(
        "※ 현재 no-sign / 거부 threshold는 적용하지 않습니다."
    )


    print("=" * 125)


if __name__ == "__main__":
    main()