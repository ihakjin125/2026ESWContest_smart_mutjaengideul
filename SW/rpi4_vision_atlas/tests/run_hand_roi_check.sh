#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
project_dir="$(cd -- "$script_dir/.." && pwd)"
source_file="$project_dir/tools/hand_roi_check.cpp"
fixture_dir="$script_dir/fixtures/roi_opencv_reference"
compiler="${CXX:-g++}"

for required_path in "$source_file" "$fixture_dir/image_bgr_u8.bin"; do
    if [[ ! -f "$required_path" ]]; then
        echo "ERROR: required file not found: $required_path" >&2
        exit 1
    fi
done

build_dir="$(mktemp -d "${TMPDIR:-/tmp}/hand_roi_check.XXXXXX")"
trap 'rm -rf "$build_dir"' EXIT
binary="$build_dir/hand_roi_check"

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

"$compiler" -std=c++17 -O2 \
    "$source_file" \
    -o "$binary" \
    "${opencv_flags[@]}"

echo "Running hand ROI regression fixture..."
"$binary" "$fixture_dir"
echo "PASS: hand ROI regression"
