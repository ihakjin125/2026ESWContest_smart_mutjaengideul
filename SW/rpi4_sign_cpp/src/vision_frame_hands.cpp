#include "vision_frame_hands.hpp"

#include <algorithm>
#include <cmath>
#include <stdexcept>
#include <utility>
#include <vector>


namespace sign_engine {
namespace {


enum class PhysicalHand {
    Left,
    Right,
};


PhysicalHand physicalHand(
    double raw
) {
    // Same rule as jsonl_frame_hands.cpp:
    //
    // raw > 0.5
    //   -> model RIGHT
    //   -> physical LEFT
    //
    // raw <= 0.5
    //   -> model LEFT
    //   -> physical RIGHT
    return raw > 0.5
        ? PhysicalHand::Left
        : PhysicalHand::Right;
}


const char* physicalHandName(
    PhysicalHand hand
) {
    return hand == PhysicalHand::Left
        ? "LEFT"
        : "RIGHT";
}


void validateDetection(
    const VisionHandDetection& detection
) {
    if (
        !std::isfinite(
            detection.handedness_raw
        )
        ||
        detection.handedness_raw < 0.0
        ||
        detection.handedness_raw > 1.0
    ) {
        throw std::runtime_error(
            "Vision handedness_raw must be finite and in [0, 1]"
        );
    }

    if (
        !std::isfinite(
            detection.confidence
        )
        ||
        detection.confidence < 0.0
        ||
        detection.confidence > 1.0
    ) {
        throw std::runtime_error(
            "Vision confidence must be finite and in [0, 1]"
        );
    }

    for (
        const Point2f& point :
        detection.landmarks.points
    ) {
        if (
            !std::isfinite(point.x)
            ||
            !std::isfinite(point.y)
        ) {
            throw std::runtime_error(
                "Vision landmark coordinates must be finite"
            );
        }
    }
}


double median(
    std::vector<double> values
) {
    if (values.empty()) {
        throw std::runtime_error(
            "internal error: median of empty values"
        );
    }

    std::sort(
        values.begin(),
        values.end()
    );

    const std::size_t size =
        values.size();

    const std::size_t middle =
        size / 2;

    if ((size % 2) != 0) {
        return values[middle];
    }

    return (
        values[middle - 1]
        +
        values[middle]
    ) / 2.0;
}


}  // namespace


VisionRecordingResult buildRecordingFramesFromVision(
    const VisionRecordingDetections& recording
) {
    VisionRecordingResult result{};

    result.input_frame_count =
        recording.size();


    // ========================================================
    // Validate input and find recording-wide maximum hand count.
    // ========================================================

    for (
        const VisionFrameDetections& frame :
        recording
    ) {
        result.maximum_hands_per_frame =
            std::max(
                result.maximum_hands_per_frame,
                frame.size()
            );

        for (
            const VisionHandDetection& hand :
            frame
        ) {
            validateDetection(
                hand
            );
        }
    }


    // ========================================================
    // ONE-HAND recording
    //
    // Exact JSONL adapter semantics:
    //
    // maximum_hands <= 1
    // -> discard empty frames
    // -> recording-wide raw median
    // -> stabilize every observed hand into one physical slot
    // ========================================================

    if (
        result.maximum_hands_per_frame
        <=
        1
    ) {
        result.used_single_hand_stabilization =
            true;

        std::vector<
            const VisionHandDetection*
        > observations;

        observations.reserve(
            recording.size()
        );

        std::vector<double> raw_values;

        raw_values.reserve(
            recording.size()
        );

        for (
            const VisionFrameDetections& frame :
            recording
        ) {
            if (frame.empty()) {
                continue;
            }

            const VisionHandDetection& hand =
                frame.front();

            observations.push_back(
                &hand
            );

            raw_values.push_back(
                hand.handedness_raw
            );
        }

        if (observations.empty()) {
            return result;
        }

        const double median_raw =
            median(
                std::move(
                    raw_values
                )
            );

        const PhysicalHand stabilized_side =
            physicalHand(
                median_raw
            );

        result.has_median_handedness =
            true;

        result.median_handedness_raw =
            median_raw;

        result.stabilized_physical_hand =
            physicalHandName(
                stabilized_side
            );

        result.frames.reserve(
            observations.size()
        );

        for (
            const VisionHandDetection* hand :
            observations
        ) {
            FrameHands output{};

            if (
                stabilized_side
                ==
                PhysicalHand::Left
            ) {
                output.has_left =
                    true;

                output.left =
                    hand->landmarks;
            } else {
                output.has_right =
                    true;

                output.right =
                    hand->landmarks;
            }

            result.frames.push_back(
                std::move(
                    output
                )
            );
        }

        return result;
    }


    // ========================================================
    // MULTI-HAND recording
    //
    // Exact JSONL adapter semantics:
    //
    // For every frame:
    //   - physical LEFT / RIGHT selected independently
    //   - highest confidence wins
    //   - strict '>' means confidence tie keeps first detection
    //   - completely empty frame is discarded
    // ========================================================

    result.used_single_hand_stabilization =
        false;

    result.frames.reserve(
        recording.size()
    );

    for (
        const VisionFrameDetections& frame :
        recording
    ) {
        const VisionHandDetection* selected_left =
            nullptr;

        const VisionHandDetection* selected_right =
            nullptr;

        for (
            const VisionHandDetection& hand :
            frame
        ) {
            if (
                physicalHand(
                    hand.handedness_raw
                )
                ==
                PhysicalHand::Left
            ) {
                if (
                    selected_left == nullptr
                    ||
                    hand.confidence
                    >
                    selected_left->confidence
                ) {
                    selected_left =
                        &hand;
                }
            } else {
                if (
                    selected_right == nullptr
                    ||
                    hand.confidence
                    >
                    selected_right->confidence
                ) {
                    selected_right =
                        &hand;
                }
            }
        }

        if (
            selected_left == nullptr
            &&
            selected_right == nullptr
        ) {
            continue;
        }

        FrameHands output{};

        if (
            selected_left
            !=
            nullptr
        ) {
            output.has_left =
                true;

            output.left =
                selected_left->landmarks;
        }

        if (
            selected_right
            !=
            nullptr
        ) {
            output.has_right =
                true;

            output.right =
                selected_right->landmarks;
        }

        result.frames.push_back(
            std::move(
                output
            )
        );
    }

    return result;
}


}  // namespace sign_engine
