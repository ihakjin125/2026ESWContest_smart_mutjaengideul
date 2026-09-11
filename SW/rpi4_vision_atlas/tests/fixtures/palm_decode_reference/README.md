# Palm decode reference fixture

This fixture validates the C++ palm anchor generation, output decoding,
score calculation, and non-maximum suppression against the Python reference.

- Source image size: 640 x 480
- Palm model output candidates: 2016
- Score threshold candidates: 5
- Expected NMS keep count: 1
- Expected kept anchor ID: 388

`palm_generated_anchor_check` regenerates anchors in C++. `palm_decode_check`
uses the exported anchors. Both must reproduce the reference decode result.
