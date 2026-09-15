#pragma once

#include "sign_types.hpp"

#include <cstddef>
#include <string>
#include <vector>


namespace sign_engine {


// ============================================================
// One hand detection produced by the C++ Vision pipeline.
//
// Coordinates are ALREADY pixel coordinates in the mirrored
// camera image.
//
// Therefore:
//   - no mirroring
//   - no normalization
//   - no coordinate conversion
//
// is performed by this adapter.
//
// handedness_raw:
//   > 0.5  -> model RIGHT -> physical LEFT
//   <= 0.5 -> model LEFT  -> physical RIGHT
//
// This matches jsonl_frame_hands.cpp exactly.
// ============================================================

struct VisionHandDetection {
    double handedness_raw =
        0.0;

    double confidence =
        0.0;

    HandLandmarks landmarks{};
};


// One raw Vision frame may contain zero, one, or multiple hands.
using VisionFrameDetections =
    std::vector<VisionHandDetection>;


// Entire capture before sequence-level stabilization.
using VisionRecordingDetections =
    std::vector<VisionFrameDetections>;


// ============================================================
// Result metadata.
//
// Kept intentionally similar to JsonlRecordingResult so direct
// Vision input can be compared against the already-validated
// JSONL path.
// ============================================================

struct VisionRecordingResult {
    RecordingFrames frames;

    std::size_t input_frame_count =
        0;

    std::size_t maximum_hands_per_frame =
        0;

    bool used_single_hand_stabilization =
        false;

    bool has_median_handedness =
        false;

    double median_handedness_raw =
        0.0;

    std::string stabilized_physical_hand;
};


// ============================================================
// Direct in-memory Vision -> RecordingFrames adapter.
//
// Semantics intentionally mirror jsonl_frame_hands.cpp:
//
// maximum_hands <= 1:
//   - discard empty frames
//   - compute recording-wide handedness_raw median
//   - stabilize every observed frame to one physical slot
//
// maximum_hands >= 2:
//   - choose LEFT / RIGHT independently per frame
//   - highest confidence wins
//   - strict '>' keeps earlier detection on a tie
//   - discard completely empty frames
// ============================================================

VisionRecordingResult buildRecordingFramesFromVision(
    const VisionRecordingDetections& recording
);


}  // namespace sign_engine
