#include <opencv2/core.hpp>
#include <opencv2/imgproc.hpp>
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <vector>

namespace fs = std::filesystem;
using Box = std::array<int, 4>;

template<class T>
std::vector<T> read(const fs::path& p, size_t count) {
    if (fs::file_size(p) != count * sizeof(T))
        throw std::runtime_error("Wrong file size: " + p.string());
    std::vector<T> v(count);
    std::ifstream f(p, std::ios::binary);
    if (!f.read(reinterpret_cast<char*>(v.data()), count * sizeof(T)))
        throw std::runtime_error("Read failed: " + p.string());
    for (auto x : v)
        if (!std::isfinite(static_cast<double>(x)))
            throw std::runtime_error("Non-finite input");
    return v;
}

struct Crop {
    cv::Mat image;
    Box box;
    cv::Point2i bias;
};

Crop crop_pad(const cv::Mat& image, cv::Point2d lo,
              cv::Point2d hi, bool rotation) {
    const auto wh = hi - lo;
    const cv::Point2d shift(0, rotation ? 0 : -0.4 * wh.y);
    lo += shift;
    hi += shift;
    const auto center = (lo + hi) * 0.5;
    const auto half = (hi - lo) * ((rotation ? 4.0 : 3.0) / 2.0);
    lo = center - half;
    hi = center + half;
    Box b = {
        std::clamp(static_cast<int>(lo.x), 0, image.cols),
        std::clamp(static_cast<int>(lo.y), 0, image.rows),
        std::clamp(static_cast<int>(hi.x), 0, image.cols),
        std::clamp(static_cast<int>(hi.y), 0, image.rows)
    };
    const int w = b[2] - b[0], h = b[3] - b[1];
    if (w <= 0 || h <= 0) throw std::runtime_error("Empty crop");
    const int side = rotation
        ? static_cast<int>(std::sqrt(double(h)*h + double(w)*w))
        : std::max(h, w);
    const int ph = side - h, pw = side - w;
    const int left = pw / 2, top = ph / 2;
    cv::Mat padded;
    cv::copyMakeBorder(image(cv::Rect(b[0], b[1], w, h)), padded,
        top, ph-top, left, pw-left,
        cv::BORDER_CONSTANT | cv::BORDER_ISOLATED, cv::Scalar(0,0,0));
    return {padded, b, {b[0]-left, b[1]-top}};
}

int main(int argc, char** argv) {
    try {
        if (argc != 2) throw std::runtime_error("Usage: hand_roi_check <fixture>");
        static_assert(sizeof(float) == 4 && sizeof(double) == 8);
        const uint16_t endian = 1;
        if (*reinterpret_cast<const unsigned char*>(&endian) != 1)
            throw std::runtime_error("Little-endian host required");

        const fs::path dir = argv[1];
        const auto wh = read<int32_t>(dir/"image_wh_i32.bin", 2);
        if (wh[0] <= 0 || wh[1] <= 0) throw std::runtime_error("Invalid size");
        auto pixels = read<uint8_t>(dir/"image_bgr_u8.bin",
                                    size_t(wh[0])*wh[1]*3);
        const auto box = read<double>(dir/"palm_box_f64.bin", 4);
        const auto pts = read<double>(dir/"palm_points_f64.bin", 14);
        const auto expected_box = read<int32_t>(dir/"expected_rotated_box_i32.bin", 4);
        const auto expected_bias = read<int32_t>(dir/"expected_bias_i32.bin", 2);
        const auto expected_matrix = read<double>(dir/"expected_matrix_f64.bin", 6);
        const auto expected_angle = read<double>(dir/"expected_angle_f64.bin", 1);
        const size_t n = 224*224*3;
        const auto expected_rgb = read<uint8_t>(dir/"expected_roi_rgb_u8.bin", n);
        const auto expected_input = read<float>(dir/"expected_input_f32.bin", n);

        cv::Mat image(wh[1], wh[0], CV_8UC3, pixels.data());
        auto first = crop_pad(image, {box[0],box[1]}, {box[2],box[3]}, true);
        cv::Mat rgb;
        cv::cvtColor(first.image, rgb, cv::COLOR_BGR2RGB);

        std::array<cv::Point2d,7> local;
        for (int i=0; i<7; ++i)
            local[i] = {pts[2*i]-first.bias.x, pts[2*i+1]-first.bias.y};
        const auto delta = local[2]-local[0];
        const double pi = std::acos(-1.0);
        double radians = pi/2 - std::atan2(-delta.y, delta.x);
        radians -= 2*pi*std::floor((radians+pi)/(2*pi));
        const double angle = radians*180/pi;

        const cv::Point2f center(
            float((first.box[0]+first.box[2])/2.0-first.bias.x),
            float((first.box[1]+first.box[3])/2.0-first.bias.y));
        const cv::Mat matrix = cv::getRotationMatrix2D(center, angle, 1.0);
        cv::Mat rotated;
        cv::warpAffine(rgb, rotated, matrix, rgb.size(),
                       cv::INTER_LINEAR, cv::BORDER_CONSTANT, cv::Scalar(0,0,0));

        cv::Point2d lo(1e100,1e100), hi(-1e100,-1e100);
        for (const auto& p : local) {
            const double x = matrix.at<double>(0,0)*p.x
                           + matrix.at<double>(0,1)*p.y + matrix.at<double>(0,2);
            const double y = matrix.at<double>(1,0)*p.x
                           + matrix.at<double>(1,1)*p.y + matrix.at<double>(1,2);
            lo.x=std::min(lo.x,x); lo.y=std::min(lo.y,y);
            hi.x=std::max(hi.x,x); hi.y=std::max(hi.y,y);
        }
        const auto second = crop_pad(rotated, lo, hi, false);
        cv::Mat roi;
        cv::resize(second.image, roi, {224,224}, 0,0, cv::INTER_AREA);
        if (!roi.isContinuous()) roi = roi.clone();

        
        {
            std::ofstream rgb_file(dir/"actual_roi_rgb_u8.bin", std::ios::binary);
            rgb_file.write(reinterpret_cast<const char*>(roi.data), n);
            std::vector<float> input(n);
            for (size_t i=0; i<n; ++i)
                input[i] = float(roi.data[i])/255.0f;
            std::ofstream input_file(dir/"actual_input_f32.bin", std::ios::binary);
            input_file.write(reinterpret_cast<const char*>(input.data()),
                             n*sizeof(float));
            if (!rgb_file || !input_file)
                throw std::runtime_error("Output write failed");
        }

        double matrix_error=0, input_error=0, pixel_sum=0;
        int pixel_max=0;
        size_t changed=0;
        for (int i=0; i<6; ++i)
            matrix_error=std::max(matrix_error,
                std::abs(matrix.at<double>(i/3,i%3)-expected_matrix[i]));
        for (size_t i=0; i<n; ++i) {
            const int error=std::abs(int(roi.data[i])-int(expected_rgb[i]));
            pixel_max=std::max(pixel_max,error);
            pixel_sum+=error;
            changed+=(error!=0);
            const float value=float(roi.data[i])/255.0f;
            input_error=std::max(input_error,
                std::abs(double(value)-double(expected_input[i])));
        }
        bool box_ok=true;
        for (int i=0; i<4; ++i) box_ok &= second.box[i]==expected_box[i];
        const bool bias_ok=first.bias.x==expected_bias[0]
                        && first.bias.y==expected_bias[1];
        const double angle_error=std::abs(angle-expected_angle[0]);
        const bool geometry_ok=box_ok && bias_ok
                           && angle_error<=1e-9 && matrix_error<=1e-9;
        const double pixel_mean=pixel_sum/double(n);
        const double changed_ratio=double(changed)/double(n);

        // OpenCV 4.6 C++ and OpenCV 5.x Python can differ slightly in
        // interpolation rounding. Keep the cross-version tolerance tight.
        const bool raster_ok=pixel_max<=4
                          && pixel_mean<=0.05
                          && changed_ratio<=0.04
                          && input_error<=4.0/255.0+1e-7;
        const bool pass=geometry_ok && raster_ok;

        std::cout << std::setprecision(12);
        std::cout << "OpenCV C++: " << CV_VERSION << "\n";
        std::cout << "Angle: " << angle << "\n";
        std::cout << "Angle max_abs_error: " << angle_error << "\n";
        std::cout << "Matrix max_abs_error: " << matrix_error << "\n";
        std::cout << "Rotated box:";
        for (auto x:second.box) std::cout << " " << x;
        std::cout << "\nBox exact match: " << (box_ok?"YES":"NO")
                  << "\nBias exact match: " << (bias_ok?"YES":"NO")
                  << "\nRGB max pixel error: " << pixel_max
                  << "\nRGB mean pixel error: " << pixel_mean
                  << "\nChanged channel values: " << changed << " / " << n
                  << "\nChanged channel ratio: " << changed_ratio
                  << "\nInput float max_abs_error: " << input_error
                  << "\nRaster tolerance match: " << (raster_ok?"YES":"NO")
                  << "\n" << (pass?"PASS":"FAIL") << "\n";
        return pass?0:1;
    } catch (const std::exception& e) {
        std::cerr << "ERROR: " << e.what() << "\n";
        return 1;
    }
}
