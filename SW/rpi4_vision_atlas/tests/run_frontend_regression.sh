#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
project_dir="$(cd -- "$script_dir/.." && pwd)"
tools_dir="$project_dir/tools"
fixture_root="$script_dir/fixtures"
palm_fixture="$fixture_root/palm_decode_reference"
roi_fixture="$fixture_root/roi_opencv_reference"
compiler="${CXX:-g++}"

for required_path in \
    "$palm_fixture/raw_boxes_f32.bin" \
    "$roi_fixture/image_bgr_u8.bin" \
    "$roi_fixture/hand_landmarks_f32.bin"
do
    if [[ ! -f "$required_path" ]]; then
        echo "ERROR: required fixture not found: $required_path" >&2
        exit 1
    fi
done

build_dir="$(mktemp -d "${TMPDIR:-/tmp}/frontend_regression.XXXXXX")"
trap 'rm -rf "$build_dir"' EXIT

if command -v pkg-config >/dev/null 2>&1 \
   && pkg-config --exists opencv4; then
    read -r -a opencv_flags <<< "$(pkg-config --cflags --libs opencv4)"
else
    if [[ ! -d /usr/include/opencv4 ]]; then
        echo "ERROR: OpenCV 4 development headers not found" >&2
        exit 1
    fi
    opencv_flags=(
        -I/usr/include/opencv4
        -lopencv_imgproc
        -lopencv_core
    )
fi

compile_checker() {
    local checker_name="$1"
    "$compiler" -std=c++17 -O2 \
        "$tools_dir/$checker_name.cpp" \
        -o "$build_dir/$checker_name" \
        "${opencv_flags[@]}"
}

for checker_name in \
    palm_generated_anchor_check \
    palm_decode_check \
    hand_roi_check \
    hand_restore_check
do
    echo "Compiling $checker_name..."
    compile_checker "$checker_name"
done

echo "[1/4] Generated anchors"
"$build_dir/palm_generated_anchor_check" "$palm_fixture" 640 480

echo "[2/4] Palm decode and NMS"
"$build_dir/palm_decode_check" "$palm_fixture" 640 480

echo "[3/4] Rotated hand ROI"
"$build_dir/hand_roi_check" "$roi_fixture"

echo "[4/4] Hand landmark restore"
"$build_dir/hand_restore_check" "$roi_fixture"

echo "PASS: complete C++ vision frontend regression"
