import os
import importlib.util

import cv2
try:
    import mediapipe as mp
except ModuleNotFoundError:
    mp = None
import numpy as np

import hand_features as hf


# ============================================================
# 파일 정보
# ============================================================

FILE_TAG = "[최종 런타임 후보 / 전체 웹캠 검증 중]"


# ============================================================
# 경로
# ============================================================

BASE_DIR = os.path.dirname(
    os.path.abspath(__file__)
)

RUNTIME_PATH = os.path.join(
    BASE_DIR,
    "06j_webcam_local_template.py",
)


# ============================================================
# 06j import
# ============================================================

spec = importlib.util.spec_from_file_location(
    "runtime06j",
    RUNTIME_PATH,
)

runtime = importlib.util.module_from_spec(
    spec
)

spec.loader.exec_module(
    runtime
)


# ============================================================
# 클래스
# ============================================================

AIRCON_ID = 0   # 0128 에어컨
LOCK_ID = 1     # 0527 문잠그다
HOT_ID = 3      # 1382 덥다
COLD_ID = 4     # 1248 춥다


HOT_RESCUE_BASE_IDS = {
    AIRCON_ID,
    LOCK_ID,
    COLD_ID,
}


# ============================================================
# 설정
# ============================================================

K = 3

TARGET_FRAMES = 80

LOCAL_START = 0
LOCAL_END = 84
LOCAL_DIM = 84

HANDSHAPE_DIM = 40

LAST40_START = 48
LAST40_END = 80


# ============================================================
# Handshape 설정
# ============================================================

ANGLE_TRIPLETS = [
    # Thumb
    (1, 2, 3),
    (2, 3, 4),

    # Index
    (5, 6, 7),
    (6, 7, 8),

    # Middle
    (9, 10, 11),
    (10, 11, 12),

    # Ring
    (13, 14, 15),
    (14, 15, 16),

    # Pinky
    (17, 18, 19),
    (18, 19, 20),
]


FINGER_CHAINS = [
    [1, 2, 3, 4],
    [5, 6, 7, 8],
    [9, 10, 11, 12],
    [13, 14, 15, 16],
    [17, 18, 19, 20],
]


TIP_IDS = [
    4,
    8,
    12,
    16,
    20,
]


PALM_IDS = [
    0,
    5,
    9,
    13,
    17,
]


# ============================================================
# 표시
# ============================================================

def class_text(class_id):

    label, word, usage = (
        runtime.CLASS_INFO[
            int(class_id)
        ]
    )

    return (
        f"{word[-4:]} "
        f"{label}"
    )


# ============================================================
# 기본 거리
# ============================================================

def point_distance(a, b):

    return float(
        np.linalg.norm(
            a - b
        )
    )


# ============================================================
# 관절 각도
# ============================================================

def normalized_angle(a, b, c):

    v1 = a - b
    v2 = c - b

    n1 = float(
        np.linalg.norm(v1)
    )

    n2 = float(
        np.linalg.norm(v2)
    )

    if (
        n1 < 1e-8
        or
        n2 < 1e-8
    ):

        return 0.0

    cosine = float(
        np.dot(
            v1,
            v2,
        )
        /
        (
            n1
            *
            n2
        )
    )

    cosine = float(
        np.clip(
            cosine,
            -1.0,
            1.0,
        )
    )

    angle = float(
        np.arccos(
            cosine
        )
    )

    return (
        angle
        /
        np.pi
    )


# ============================================================
# 손가락 straightness
# ============================================================

def finger_straightness(
    landmarks,
    chain,
):

    direct = point_distance(
        landmarks[
            chain[0]
        ],
        landmarks[
            chain[-1]
        ],
    )

    path = 0.0

    for i in range(
        len(chain) - 1
    ):

        path += point_distance(
            landmarks[
                chain[i]
            ],
            landmarks[
                chain[i + 1]
            ],
        )

    if path < 1e-8:

        return 0.0

    return float(
        direct
        /
        path
    )


# ============================================================
# 한 손 Handshape 20차원
#
# angle        10
# straightness  5
# tip-palm      5
# ============================================================

def build_single_handshape(
    landmarks,
):

    landmarks = np.asarray(
        landmarks,
        dtype=np.float32,
    )

    if landmarks.shape != (
        21,
        2,
    ):

        raise RuntimeError(
            f"landmark shape 오류: "
            f"{landmarks.shape}"
        )

    # --------------------------------------------------------
    # Angle
    # --------------------------------------------------------

    angles = []

    for a, b, c in (
        ANGLE_TRIPLETS
    ):

        angles.append(
            normalized_angle(
                landmarks[a],
                landmarks[b],
                landmarks[c],
            )
        )

    # --------------------------------------------------------
    # Straightness
    # --------------------------------------------------------

    straightness = []

    for chain in (
        FINGER_CHAINS
    ):

        straightness.append(
            finger_straightness(
                landmarks,
                chain,
            )
        )

    # --------------------------------------------------------
    # Tip → Palm
    # --------------------------------------------------------

    palm_center = np.mean(
        landmarks[
            PALM_IDS
        ],
        axis=0,
    )

    tip_palm = []

    for tip_id in TIP_IDS:

        tip_palm.append(
            point_distance(
                landmarks[
                    tip_id
                ],
                palm_center,
            )
        )

    descriptor = np.asarray(
        (
            angles
            +
            straightness
            +
            tip_palm
        ),
        dtype=np.float32,
    )

    if descriptor.shape != (
        20,
    ):

        raise RuntimeError(
            f"Hand descriptor 오류: "
            f"{descriptor.shape}"
        )

    return descriptor


# ============================================================
# Local (80,84)
# →
# Handshape (80,40)
# ============================================================

def build_handshape_sequence(
    local_feature,
):

    local_feature = np.asarray(
        local_feature,
        dtype=np.float32,
    )

    if local_feature.shape != (
        TARGET_FRAMES,
        LOCAL_DIM,
    ):

        raise RuntimeError(
            f"Local shape 오류: "
            f"{local_feature.shape}"
        )

    output = []

    for frame_index in range(
        TARGET_FRAMES
    ):

        slot_a = (
            local_feature[
                frame_index,
                0:42,
            ]
            .reshape(
                21,
                2,
            )
        )

        slot_b = (
            local_feature[
                frame_index,
                42:84,
            ]
            .reshape(
                21,
                2,
            )
        )

        desc_a = (
            build_single_handshape(
                slot_a
            )
        )

        desc_b = (
            build_single_handshape(
                slot_b
            )
        )

        output.append(
            np.concatenate(
                [
                    desc_a,
                    desc_b,
                ],
                axis=0,
            )
        )

    output = np.stack(
        output,
        axis=0,
    ).astype(
        np.float32
    )

    if output.shape != (
        TARGET_FRAMES,
        HANDSHAPE_DIM,
    ):

        raise RuntimeError(
            f"Handshape shape 오류: "
            f"{output.shape}"
        )

    if not np.all(
        np.isfinite(output)
    ):

        raise RuntimeError(
            "Handshape NaN/Inf"
        )

    return output


# ============================================================
# Runtime Local templates
# →
# Runtime Handshape templates
# ============================================================

def build_handshape_templates(
    template_data,
):

    templates = np.asarray(
        template_data[
            "templates"
        ],
        dtype=np.float32,
    )

    class_ids = np.asarray(
        template_data[
            "class_ids"
        ],
        dtype=np.int64,
    )

    real_ids = np.asarray(
        template_data[
            "real_ids"
        ]
    ).astype(str)

    if templates.shape[1:] != (
        80,
        84,
    ):

        raise RuntimeError(
            f"Template shape 오류: "
            f"{templates.shape}"
        )

    handshape_list = []

    for template in templates:

        handshape_list.append(
            build_handshape_sequence(
                template
            )
        )

    handshape_templates = np.stack(
        handshape_list,
        axis=0,
    ).astype(
        np.float32
    )

    if handshape_templates.shape != (
        len(templates),
        80,
        40,
    ):

        raise RuntimeError(
            "Handshape template "
            f"shape 오류: "
            f"{handshape_templates.shape}"
        )

    print()
    print("=" * 120)
    print("HANDSHAPE TEMPLATE")
    print("=" * 120)

    print(
        "Local templates     :",
        templates.shape,
    )

    print(
        "Handshape templates :",
        handshape_templates.shape,
    )

    print(
        "K                   :",
        K,
    )

    print(
        "Finite              :",
        (
            "PASS"
            if np.all(
                np.isfinite(
                    handshape_templates
                )
            )
            else "FAIL"
        ),
    )

    return {
        "templates":
            handshape_templates,

        "class_ids":
            class_ids,

        "real_ids":
            real_ids,
    }


# ============================================================
# 클래스 K3 RMSE
# ============================================================

def class_score(
    query,
    references,
):

    diff = (
        references
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

    order = np.argsort(
        distances
    )

    selected = distances[
        order[:K]
    ]

    return float(
        np.mean(
            selected
        )
    )


# ============================================================
# Handshape 특정 클래스 점수
# ============================================================

def handshape_class_score(
    query_handshape,
    handshape_data,
    class_id,
):

    indices = np.where(
        handshape_data[
            "class_ids"
        ]
        ==
        int(class_id)
    )[0]

    if len(indices) < K:

        raise RuntimeError(
            f"{class_text(class_id)} "
            f"Handshape template 부족"
        )

    return class_score(
        query=query_handshape,

        references=(
            handshape_data[
                "templates"
            ][
                indices
            ]
        ),
    )


# ============================================================
# Handshape 전체 ranking
# ============================================================

def handshape_ranking(
    query_handshape,
    handshape_data,
):

    ranking = []

    two_hand_ids = [
        0,
        1,
        3,
        4,
        5,
        6,
        9,
    ]

    for class_id in (
        two_hand_ids
    ):

        score = (
            handshape_class_score(
                query_handshape=(
                    query_handshape
                ),

                handshape_data=(
                    handshape_data
                ),

                class_id=(
                    class_id
                ),
            )
        )

        ranking.append(
            {
                "class_id":
                    int(class_id),

                "score":
                    float(score),
            }
        )

    ranking.sort(
        key=lambda x:
        x["score"]
    )

    return ranking


# ============================================================
# Local LAST40 특정 클래스 점수
# ============================================================

def local_last40_score(
    query_local,
    template_data,
    class_id,
):

    templates = np.asarray(
        template_data[
            "templates"
        ],
        dtype=np.float32,
    )

    class_ids = np.asarray(
        template_data[
            "class_ids"
        ],
        dtype=np.int64,
    )

    indices = np.where(
        class_ids
        ==
        int(class_id)
    )[0]

    if len(indices) < K:

        raise RuntimeError(
            f"{class_text(class_id)} "
            f"Local template 부족"
        )

    query_block = query_local[
        LAST40_START:
        LAST40_END,
        :
    ]

    reference_block = templates[
        indices,
        LAST40_START:
        LAST40_END,
        :
    ]

    return class_score(
        query=query_block,
        references=reference_block,
    )


# ============================================================
# 웹캠 촬영
# ============================================================

def capture_sequence():
    if mp is None:
        raise RuntimeError(
            "웹캠 캡처에는 mediapipe가 필요합니다. "
            "C++ JSONL 오프라인 입력에는 필요하지 않습니다."
        )

    mp_hands = (
        mp.solutions.hands
    )

    mp_draw = (
        mp.solutions.drawing_utils
    )

    hands = mp_hands.Hands(
        static_image_mode=False,
        max_num_hands=2,
        min_detection_confidence=0.5,
        min_tracking_confidence=0.5,
    )

    cap = cv2.VideoCapture(
        runtime.CAMERA_INDEX
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

            raise RuntimeError(
                "웹캠 frame read 실패"
            )

        frame = cv2.flip(
            frame,
            1,
        )

        height, width = (
            frame.shape[:2]
        )

        rgb = cv2.cvtColor(
            frame,
            cv2.COLOR_BGR2RGB,
        )

        results = hands.process(
            rgb
        )

        detected = (
            runtime.extract_hands(
                results,
                width,
                height,
            )
        )

        left_xy = None
        right_xy = None

        if "LEFT" in detected:

            left_xy = (
                detected[
                    "LEFT"
                ][
                    "xy"
                ]
            )

        if "RIGHT" in detected:

            right_xy = (
                detected[
                    "RIGHT"
                ][
                    "xy"
                ]
            )

        # ----------------------------------------------------
        # Landmark 표시
        # ----------------------------------------------------

        if (
            results.multi_hand_landmarks
        ):

            for hand_landmarks in (
                results.multi_hand_landmarks
            ):

                mp_draw.draw_landmarks(
                    frame,
                    hand_landmarks,
                    mp_hands.HAND_CONNECTIONS,
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
                (20, 40),
                cv2.FONT_HERSHEY_SIMPLEX,
                1.0,
                (0, 0, 255),
                2,
            )

            cv2.putText(
                frame,
                (
                    f"Frames: "
                    f"{len(recording_frames)}"
                ),
                (20, 80),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 0, 255),
                2,
            )

        else:

            cv2.putText(
                frame,
                "S=start  E=end",
                (20, 40),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (255, 255, 255),
                2,
            )

        cv2.imshow(
            "06u Combined Hierarchy",
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

            cap.release()

            cv2.destroyAllWindows()

            hands.close()

            return None

        # ----------------------------------------------------
        # S
        #
        # ★ 이미 녹화 중이면 무시
        # ----------------------------------------------------

        if key in (
            ord("s"),
            ord("S"),
        ):

            if recording:

                print(
                    ">>> 이미 녹화 중입니다. "
                    "S 입력 무시"
                )

                continue

            recording_frames = []

            recording = True

            print()
            print(
                ">>> RECORDING START"
            )

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

            print(
                ">>> RECORDING END"
            )

            break

    cap.release()

    cv2.destroyAllWindows()

    hands.close()

    return recording_frames


# ============================================================
# Webcam → Feature v3
# ============================================================

def build_webcam_feature(
    recording_frames,
):

    if not recording_frames:

        raise RuntimeError(
            "Hand frame 없음"
        )

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
    # 양손
    # ========================================================

    if (
        both_ratio
        >=
        runtime.BOTH_FRAME_RATIO_THRESHOLD
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

        if (
            len(selected)
            <
            runtime.MIN_ACCEPTED_FRAMES
        ):

            raise RuntimeError(
                f"BOTH_ALIGNED "
                f"frame 부족: "
                f"{len(selected)}"
            )

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

    # ========================================================
    # 한손
    # ========================================================

    else:

        if (
            right_count
            >=
            left_count
        ):

            source_mode = (
                "RIGHT_ONLY"
            )

            selected = [
                right

                for left, right
                in recording_frames

                if right is not None
            ]

            if (
                len(selected)
                <
                runtime.MIN_ACCEPTED_FRAMES
            ):

                raise RuntimeError(
                    "RIGHT_ONLY frame 부족"
                )

            right_sequence = np.stack(
                selected,
                axis=0,
            )

            left_sequence = None

        else:

            source_mode = (
                "LEFT_ONLY"
            )

            selected = [
                left

                for left, right
                in recording_frames

                if left is not None
            ]

            if (
                len(selected)
                <
                runtime.MIN_ACCEPTED_FRAMES
            ):

                raise RuntimeError(
                    "LEFT_ONLY frame 부족"
                )

            left_sequence = np.stack(
                selected,
                axis=0,
            )

            right_sequence = None

    print(
        "Source mode    :",
        source_mode,
    )

    print(
        "Selected frames:",
        len(selected),
    )

    # ========================================================
    # Feature v3
    # ========================================================

    result = hf.build_feature_v3(
        left_sequence=left_sequence,
        right_sequence=right_sequence,

        one_hand_ratio_threshold=(
            runtime.ONE_HAND_RATIO_THRESHOLD
        ),

        no_motion_threshold=(
            runtime.WEBCAM_NO_MOTION_THRESHOLD
        ),

        anchor_frame_count=(
            runtime.ANCHOR_FRAME_COUNT
        ),

        canonical_hand=(
            runtime.CANONICAL_HAND
        ),
    )

    if not result[
        "valid"
    ]:

        raise RuntimeError(
            "Feature v3 invalid"
        )

    usage_type = str(
        result[
            "usage"
        ][
            "type"
        ]
    )

    feature_raw = np.asarray(
        result[
            "features"
        ],
        dtype=np.float32,
    )

    feature_80 = (
        runtime.temporal_resample(
            feature_raw,
            runtime.TARGET_FRAMES,
        )
    )

    if feature_80.shape != (
        80,
        172,
    ):

        raise RuntimeError(
            f"Feature shape 오류: "
            f"{feature_80.shape}"
        )

    if not np.all(
        np.isfinite(
            feature_80
        )
    ):

        raise RuntimeError(
            "Feature NaN/Inf"
        )

    local = feature_80[
        :,
        0:84,
    ].copy()

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
        result[
            "detected_mask"
        ],
    )

    print(
        "Usage mask    :",
        result[
            "usage_mask"
        ],
    )

    print(
        "Left score    :",
        result[
            "usage"
        ].get(
            "left_score"
        ),
    )

    print(
        "Right score   :",
        result[
            "usage"
        ].get(
            "right_score"
        ),
    )

    print(
        "Ratio         :",
        result[
            "usage"
        ].get(
            "ratio"
        ),
    )

    print(
        "Raw feature   :",
        feature_raw.shape,
    )

    print(
        "Resampled     :",
        feature_80.shape,
    )

    print(
        "Local         :",
        local.shape,
    )

    return {
        "feature":
            feature_80,

        "local":
            local,

        "usage_type":
            usage_type,

        "source_mode":
            source_mode,

        "both_ratio":
            float(
                both_ratio
            ),

        "selected_frames":
            int(
                len(selected)
            ),
    }


# ============================================================
# 통합 classifier
# ============================================================

def predict_combined(
    feature_info,
    template_data,
    handshape_data,
):

    local = (
        feature_info[
            "local"
        ]
    )

    usage_type = (
        feature_info[
            "usage_type"
        ]
    )

    # ========================================================
    # Base Local
    # ========================================================

    (
        base_pred,
        local_ranking,
    ) = runtime.predict_template(
        query=local,
        usage_type=usage_type,
        template_data=template_data,
    )

    base_pred = int(
        base_pred
    )

    final_pred = (
        base_pred
    )

    stage = (
        "BASE_ONLY"
    )

    hot_info = None
    ac_info = None
    hs_ranking = None

    # ========================================================
    # Stage A
    #
    # 1382 Handshape rescue
    # ========================================================

    if (
        usage_type
        ==
        "two_hand"

        and

        base_pred
        in
        HOT_RESCUE_BASE_IDS
    ):

        query_handshape = (
            build_handshape_sequence(
                local
            )
        )

        hs_ranking = (
            handshape_ranking(
                query_handshape=(
                    query_handshape
                ),

                handshape_data=(
                    handshape_data
                ),
            )
        )

        hot_score = (
            handshape_class_score(
                query_handshape=(
                    query_handshape
                ),

                handshape_data=(
                    handshape_data
                ),

                class_id=(
                    HOT_ID
                ),
            )
        )

        base_hs_score = (
            handshape_class_score(
                query_handshape=(
                    query_handshape
                ),

                handshape_data=(
                    handshape_data
                ),

                class_id=(
                    base_pred
                ),
            )
        )

        hot_delta = (
            hot_score
            -
            base_hs_score
        )

        hot_info = {
            "hot_score":
                float(
                    hot_score
                ),

            "base_score":
                float(
                    base_hs_score
                ),

            "delta":
                float(
                    hot_delta
                ),
        }

        # ----------------------------------------------------
        # 1382가 Handshape에서 더 가까움
        # ----------------------------------------------------

        if (
            hot_score
            <
            base_hs_score
        ):

            final_pred = (
                HOT_ID
            )

            stage = (
                "HOT_HANDSHAPE_RESCUE"
            )

            return {
                "base_pred":
                    base_pred,

                "final_pred":
                    int(
                        final_pred
                    ),

                "stage":
                    stage,

                "local_ranking":
                    local_ranking,

                "handshape_ranking":
                    hs_ranking,

                "hot_info":
                    hot_info,

                "ac_info":
                    None,
            }

    # ========================================================
    # Stage B
    #
    # 0128 ↔ 1248 LAST40
    # ========================================================

    if (
        usage_type
        ==
        "two_hand"

        and

        len(
            local_ranking
        )
        >=
        2
    ):

        top2_ids = {
            int(
                local_ranking[
                    0
                ][
                    "class_id"
                ]
            ),

            int(
                local_ranking[
                    1
                ][
                    "class_id"
                ]
            ),
        }

        if (
            top2_ids
            ==
            {
                AIRCON_ID,
                COLD_ID,
            }
        ):

            aircon_score = (
                local_last40_score(
                    query_local=local,
                    template_data=template_data,
                    class_id=AIRCON_ID,
                )
            )

            cold_score = (
                local_last40_score(
                    query_local=local,
                    template_data=template_data,
                    class_id=COLD_ID,
                )
            )

            ac_delta = (
                aircon_score
                -
                cold_score
            )

            if (
                cold_score
                <
                aircon_score
            ):

                final_pred = (
                    COLD_ID
                )

            else:

                final_pred = (
                    AIRCON_ID
                )

            stage = (
                "AIRCON_COLD_LAST40"
            )

            ac_info = {
                "aircon_score":
                    float(
                        aircon_score
                    ),

                "cold_score":
                    float(
                        cold_score
                    ),

                "delta":
                    float(
                        ac_delta
                    ),
            }

    # ========================================================
    # 결과
    # ========================================================

    return {
        "base_pred":
            base_pred,

        "final_pred":
            int(
                final_pred
            ),

        "stage":
            stage,

        "local_ranking":
            local_ranking,

        "handshape_ranking":
            hs_ranking,

        "hot_info":
            hot_info,

        "ac_info":
            ac_info,
    }


# ============================================================
# Main
# ============================================================

def main():

    print()
    print("=" * 140)
    print(
        "06u WEBCAM COMBINED "
        "HIERARCHICAL TEMPLATE"
    )
    print("=" * 140)

    print(
        FILE_TAG
    )

    print()
    print(
        "Priority:"
    )

    print(
        "  1. Base Local"
    )

    print(
        "  2. 1382 Handshape rescue"
    )

    print(
        "  3. 0128/1248 Local LAST40"
    )

    print(
        "  4. Final"
    )

    print()
    print(
        "※ no-sign rejection은 아직 없음"
    )

    # ========================================================
    # Local template
    # ========================================================

    template_data = (
        runtime.load_templates()
    )

    # ========================================================
    # Handshape template
    # ========================================================

    handshape_data = (
        build_handshape_templates(
            template_data
        )
    )

    # ========================================================
    # Webcam
    # ========================================================

    frames = (
        capture_sequence()
    )

    if frames is None:

        print(
            "종료했습니다."
        )

        return

    # ========================================================
    # Feature
    # ========================================================

    feature_info = (
        build_webcam_feature(
            frames
        )
    )

    # ========================================================
    # Prediction
    # ========================================================

    result = (
        predict_combined(
            feature_info=feature_info,
            template_data=template_data,
            handshape_data=handshape_data,
        )
    )

    # ========================================================
    # Local ranking
    # ========================================================

    print()
    print("=" * 145)
    print(
        "BASE LOCAL RANKING"
    )
    print("=" * 145)

    for rank_index, item in enumerate(
        result[
            "local_ranking"
        ],
        start=1,
    ):

        print(
            f"{rank_index}. "
            f"{class_text(item['class_id']):<16} "
            f"| "
            f"{item['score']:.6f}"
        )

    # ========================================================
    # Handshape
    # ========================================================

    if (
        result[
            "handshape_ranking"
        ]
        is not None
    ):

        print()
        print("=" * 145)
        print(
            "HANDSHAPE RANKING"
        )
        print("=" * 145)

        for rank_index, item in enumerate(
            result[
                "handshape_ranking"
            ],
            start=1,
        ):

            print(
                f"{rank_index}. "
                f"{class_text(item['class_id']):<16} "
                f"| "
                f"{item['score']:.6f}"
            )

    # ========================================================
    # Decision
    # ========================================================

    print()
    print("=" * 145)
    print(
        "HIERARCHICAL DECISION"
    )
    print("=" * 145)

    print(
        "BASE :",
        class_text(
            result[
                "base_pred"
            ]
        ),
    )

    # --------------------------------------------------------
    # Hot
    # --------------------------------------------------------

    if (
        result[
            "hot_info"
        ]
        is not None
    ):

        h = (
            result[
                "hot_info"
            ]
        )

        print()
        print(
            f"1382 Handshape : "
            f"{h['hot_score']:.6f}"
        )

        print(
            f"Base Handshape : "
            f"{h['base_score']:.6f}"
        )

        print(
            f"HOT delta "
            f"(1382 - Base): "
            f"{h['delta']:+.6f}"
        )

        print(
            "  delta < 0 → 1382 덥다"
        )

        print(
            "  delta > 0 → Base 유지"
        )

    # --------------------------------------------------------
    # Aircon / Cold
    # --------------------------------------------------------

    if (
        result[
            "ac_info"
        ]
        is not None
    ):

        a = (
            result[
                "ac_info"
            ]
        )

        print()
        print(
            f"0128 LAST40 : "
            f"{a['aircon_score']:.6f}"
        )

        print(
            f"1248 LAST40 : "
            f"{a['cold_score']:.6f}"
        )

        print(
            f"AC delta "
            f"(0128 - 1248): "
            f"{a['delta']:+.6f}"
        )

        print(
            "  delta < 0 → 0128 에어컨"
        )

        print(
            "  delta > 0 → 1248 춥다"
        )

    # ========================================================
    # Final
    # ========================================================

    print()
    print("=" * 145)
    print(
        "06u FINAL RESULT"
    )
    print("=" * 145)

    print(
        "Source mode :",
        feature_info[
            "source_mode"
        ],
    )

    print(
        "Selected    :",
        feature_info[
            "selected_frames"
        ],
    )

    print(
        "Both ratio  :",
        f"{feature_info['both_ratio']:.3f}",
    )

    print(
        "Usage type  :",
        feature_info[
            "usage_type"
        ],
    )

    print(
        "BASE        :",
        class_text(
            result[
                "base_pred"
            ]
        ),
    )

    print(
        "STAGE       :",
        result[
            "stage"
        ],
    )

    print(
        "FINAL       :",
        class_text(
            result[
                "final_pred"
            ]
        ),
    )

    if (
        result[
            "base_pred"
        ]
        !=
        result[
            "final_pred"
        ]
    ):

        print()
        print(
            "★ Hierarchical correction"
        )

        print(
            f"★ "
            f"{class_text(result['base_pred'])}"
            f" → "
            f"{class_text(result['final_pred'])}"
        )

    print()
    print(
        "※ RMSE score는 confidence가 아닙니다."
    )

    print(
        "※ no-sign / rejection은 "
        "아직 적용하지 않았습니다."
    )

    print("=" * 145)


if __name__ == "__main__":
    main()