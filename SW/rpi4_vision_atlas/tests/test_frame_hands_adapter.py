"""Unit tests for the C++ result to FrameHands adapter."""

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from frame_hands_adapter import (
    FrameHandsError,
    frame_hands_from_result,
    load_recording_frames,
    recording_frames_from_results,
)


def hand(raw, physical, value=1.0, confidence=0.9):
    model = "RIGHT" if raw > 0.5 else "LEFT"
    return {
        "handedness_raw": raw,
        "model_hand": model,
        "physical_hand": physical,
        "hand_confidence": confidence,
        "landmarks_xy": np.full((21, 2), value, dtype=np.float32).tolist(),
    }


def frame(hands, mirror=True, size=None):
    return {
        "mirror_input": mirror,
        "image_size_wh": [640, 480] if size is None else size,
        "hands": hands,
    }


class FrameHandsAdapterTest(unittest.TestCase):
    def test_model_right_maps_to_physical_left_unflipped(self):
        left, right = frame_hands_from_result(
            {"mirror_input": False, "hands": [hand(0.735, "LEFT")]}
        )
        self.assertEqual(left.shape, (21, 2))
        self.assertIsNone(right)

    def test_model_right_maps_to_physical_left_mirrored(self):
        left, right = frame_hands_from_result(
            {"mirror_input": True, "hands": [hand(0.735, "LEFT")]}
        )
        self.assertEqual(left.shape, (21, 2))
        self.assertIsNone(right)

    def test_one_hand_sequence_median_stops_frame_label_flips(self):
        raw_values = [0.20, 0.25, 0.70, 0.30, 0.65, 0.28, 0.32]
        frames = recording_frames_from_results(
            [frame([hand(raw, "UNVERIFIED", value=i)]) for i, raw in enumerate(raw_values)]
        )
        self.assertEqual(len(frames), len(raw_values))
        self.assertTrue(all(left is None and right is not None for left, right in frames))

    def test_left_back_measurement_median_maps_left(self):
        raw_values = [0.345, 0.52, 0.58, 0.60, 0.62, 0.67, 0.773]
        frames = recording_frames_from_results(
            [frame([hand(raw, "UNVERIFIED")]) for raw in raw_values]
        )
        self.assertTrue(all(left is not None and right is None for left, right in frames))

    def test_higher_confidence_duplicate_wins(self):
        left, _ = frame_hands_from_result(
            {
                "mirror_input": False,
                "hands": [
                    hand(0.8, "LEFT", value=1.0, confidence=0.7),
                    hand(0.9, "LEFT", value=2.0, confidence=0.95),
                ],
            }
        )
        np.testing.assert_array_equal(left, np.full((21, 2), 2.0))

    def test_rejects_inconsistent_physical_hand(self):
        with self.assertRaises(FrameHandsError):
            frame_hands_from_result(
                {"mirror_input": True, "hands": [hand(0.735, "RIGHT")]}
            )

    def test_rejects_bad_landmark_shape(self):
        bad = hand(0.735, "LEFT")
        bad["landmarks_xy"] = [[0.0, 0.0]]
        with self.assertRaises(FrameHandsError):
            frame_hands_from_result({"mirror_input": False, "hands": [bad]})

    def test_sequence_skips_empty_frames(self):
        frames = recording_frames_from_results(
            [frame([]), frame([hand(0.735, "LEFT")])]
        )
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0][0].shape, (21, 2))
        self.assertIsNone(frames[0][1])

    def test_sequence_rejects_changed_mirror_setting(self):
        with self.assertRaises(FrameHandsError):
            recording_frames_from_results([frame([]), frame([], mirror=False)])

    def test_sequence_rejects_changed_image_size(self):
        with self.assertRaises(FrameHandsError):
            recording_frames_from_results([frame([]), frame([], size=[1280, 720])])

    def test_empty_recording_returns_empty_list(self):
        self.assertEqual(recording_frames_from_results([frame([]), frame([])]), [])

    def test_rejects_non_boolean_mirror_input(self):
        with self.assertRaises(FrameHandsError):
            frame_hands_from_result({"mirror_input": "false", "hands": []})

    def test_rejects_non_array_hands(self):
        with self.assertRaises(FrameHandsError):
            frame_hands_from_result({"mirror_input": False, "hands": {}})

    def test_rejects_invalid_handedness(self):
        for value in (-0.1, 1.1, float("nan"), float("inf")):
            with self.subTest(value=value), self.assertRaises(FrameHandsError):
                frame_hands_from_result(
                    {"mirror_input": False, "hands": [hand(value, "LEFT")]}
                )

    def test_rejects_invalid_confidence(self):
        for value in (-0.1, 1.1, float("nan"), float("inf")):
            with self.subTest(value=value), self.assertRaises(FrameHandsError):
                frame_hands_from_result(
                    {
                        "mirror_input": False,
                        "hands": [hand(0.8, "LEFT", confidence=value)],
                    }
                )

    def test_rejects_non_finite_landmark(self):
        for value in (float("nan"), float("inf")):
            bad = hand(0.8, "LEFT")
            bad["landmarks_xy"][0][0] = value
            with self.subTest(value=value), self.assertRaises(FrameHandsError):
                frame_hands_from_result({"mirror_input": False, "hands": [bad]})

    def test_rejects_missing_required_hand_field(self):
        bad = hand(0.8, "LEFT")
        del bad["hand_confidence"]
        with self.assertRaises(FrameHandsError):
            frame_hands_from_result({"mirror_input": False, "hands": [bad]})

    def test_rejects_invalid_image_size(self):
        with self.assertRaises(FrameHandsError):
            recording_frames_from_results([frame([], size=[0, 480])])

    def test_loads_jsonl(self):
        documents = [frame([]), frame([hand(0.8, "LEFT")])]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "stream.jsonl"
            path.write_text(
                "".join(json.dumps(document) + "\n" for document in documents),
                encoding="utf-8",
            )
            frames = load_recording_frames([path])
        self.assertEqual(len(frames), 1)
        self.assertIsNotNone(frames[0][0])


if __name__ == "__main__":
    unittest.main()
