#define VISION_PHOTO_NO_MAIN
#include "vision_photo.cpp"
#undef VISION_PHOTO_NO_MAIN

#include <chrono>

#include "vision_frame_hands.hpp"
#include "runtime_data.hpp"
#include "sign_runtime.hpp"
#include "raw_tcp_streamer.hpp"

namespace {

constexpr int kPalmInterval = 10;
constexpr float kBorderMargin = 8.0f;


sign_engine::VisionFrameDetections to_vision_detections(
    const std::vector<Hand>& hands
) {
    sign_engine::VisionFrameDetections detections;

    detections.reserve(
        hands.size()
    );

    for (const Hand& hand : hands) {
        sign_engine::VisionHandDetection detection{};

        detection.handedness_raw =
            hand.handedness;

        detection.confidence =
            hand.confidence;

        for (std::size_t i = 0; i < 21; ++i) {
            detection.landmarks.points[i].x =
                hand.xy[i].x;

            detection.landmarks.points[i].y =
                hand.xy[i].y;
        }

        detections.push_back(
            detection
        );
    }

    return detections;
}


Palm tracked_palm_from_hand(const Hand& hand_result) {
    Palm tracked{};
    tracked.id = -1;
    tracked.score = hand_result.confidence;
    tracked.points[0] = hand_result.xy[0];
    tracked.points[1] = hand_result.xy[5];
    tracked.points[2] = hand_result.xy[9];
    tracked.points[3] = hand_result.xy[13];
    tracked.points[4] = hand_result.xy[17];
    tracked.points[5] = hand_result.xy[1];

    cv::Point2d center(0.0, 0.0);
    for (int i = 0; i < 6; ++i) {
        center += tracked.points[i];
    }
    tracked.points[6] = center * (1.0 / 6.0);

    cv::Point2d lo(1e100, 1e100);
    cv::Point2d hi(-1e100, -1e100);
    for (const auto& point : tracked.points) {
        lo.x = std::min(lo.x, point.x);
        lo.y = std::min(lo.y, point.y);
        hi.x = std::max(hi.x, point.x);
        hi.y = std::max(hi.y, point.y);
    }
    if (hi.x - lo.x < 2.0 || hi.y - lo.y < 2.0) {
        throw std::runtime_error("Tracked palm is too small");
    }
    tracked.box = {lo.x, lo.y, hi.x, hi.y};
    return tracked;
}

bool near_border(const Hand& hand_result, int width, int height) {
    // Fingertips may legitimately touch the frame edge. Re-detect only when
    // the stable palm core approaches an edge.
    constexpr std::array<int, 5> kPalmCore{0, 5, 9, 13, 17};
    for (const int index : kPalmCore) {
        const auto& point = hand_result.xy[index];
        if (point.x < kBorderMargin || point.y < kBorderMargin ||
            point.x >= width - kBorderMargin ||
            point.y >= height - kBorderMargin) {
            return true;
        }
    }
    return false;
}

std::vector<Hand> run_hands(const cv::Mat& image,
                            const std::vector<Palm>& palms_to_run,
                            Model& hand_model,
                            bool& any_failure) {
    std::vector<Hand> results;
    any_failure = false;
    for (const auto& palm : palms_to_run) {
        Hand result{};
        if (hand(image, palm, hand_model, result)) {
            results.push_back(result);
        } else {
            any_failure = true;
        }
    }
    return results;
}

void write_frame_json(std::ofstream& output,
                      size_t frame_index,
                      int width,
                      int height,
                      double processing_ms,
                      bool used_palm_detector,
                      const std::vector<Hand>& hands) {
    output << std::setprecision(12)
           << "{\"frame_index\":" << frame_index
           << ",\"image_size_wh\":[" << width << ',' << height << ']'
           << ",\"coordinate_system\":\"mirrored camera image pixels\""
           << ",\"mirror_input\":true"
           << ",\"processing_ms\":" << processing_ms
           << ",\"used_palm_detector\":"
           << (used_palm_detector ? "true" : "false")
           << ",\"hands\":[";

    for (size_t index = 0; index < hands.size(); ++index) {
        if (index != 0) {
            output << ',';
        }
        const auto& result = hands[index];
        const char* model_hand = result.handedness > 0.5 ? "RIGHT" : "LEFT";
        const char* physical_hand = result.handedness > 0.5 ? "LEFT" : "RIGHT";
        output << "{\"anchor_index\":" << result.palm.id
               << ",\"palm_score\":" << result.palm.score
               << ",\"hand_confidence\":" << result.confidence
               << ",\"handedness_raw\":" << result.handedness
               << ",\"model_hand\":\"" << model_hand << "\""
               << ",\"physical_hand\":\"" << physical_hand << "\""
               << ",\"landmarks_xy\":[";
        for (int point = 0; point < 21; ++point) {
            if (point != 0) {
                output << ',';
            }
            output << '[' << result.xy[point].x
                   << ',' << result.xy[point].y << ']';
        }
        const auto world_a = result.world_xyz[5] - result.world_xyz[0];
        const auto world_b = result.world_xyz[17] - result.world_xyz[0];
        const auto world_c = result.world_xyz[4] - result.world_xyz[0];
        const float world_chirality = world_a.cross(world_b).dot(world_c);
        output << "],\"world_chirality\":" << world_chirality << '}';
    }
    output << "]}\n";
    output.flush();
}

void write_overlay_ppm(const fs::path& path,
                       const cv::Mat& image,
                       const std::vector<Hand>& hands) {
    cv::Mat canvas = image.clone();
    const std::array<std::array<int, 2>, 21> edges{{
        {{0,1}},{{1,2}},{{2,3}},{{3,4}},{{0,5}},{{5,6}},{{6,7}},
        {{7,8}},{{5,9}},{{9,10}},{{10,11}},{{11,12}},{{9,13}},
        {{13,14}},{{14,15}},{{15,16}},{{13,17}},{{17,18}},
        {{18,19}},{{19,20}},{{0,17}}
    }};
    for (const auto& hand_result : hands) {
        for (const auto& edge : edges) {
            const cv::Point from(
                cvRound(hand_result.xy[edge[0]].x),
                cvRound(hand_result.xy[edge[0]].y)
            );
            const cv::Point to(
                cvRound(hand_result.xy[edge[1]].x),
                cvRound(hand_result.xy[edge[1]].y)
            );
            cv::line(canvas, from, to, cv::Scalar(0, 255, 0), 1);
        }
        for (int i = 0; i < 21; ++i) {
            const cv::Point point(
                cvRound(hand_result.xy[i].x),
                cvRound(hand_result.xy[i].y)
            );
            cv::circle(canvas, point, 2, cv::Scalar(0, 0, 255), -1);
        }
    }
    cv::Mat rgb;
    cv::cvtColor(canvas, rgb, cv::COLOR_BGR2RGB);
    std::ofstream ppm(path, std::ios::binary);
    ppm << "P6\n" << rgb.cols << ' ' << rgb.rows << "\n255\n";
    ppm.write(reinterpret_cast<const char*>(rgb.data),
              static_cast<std::streamsize>(rgb.total() * rgb.elemSize()));
    if (!ppm) {
        throw std::runtime_error("Could not write overlay PPM");
    }
}

}  // namespace

int main(int argc, char** argv) {
    try {
        if (argc != 7) {
            throw std::runtime_error(
                "Usage: vision_stream_sign WIDTH HEIGHT MODEL_DIR OUTPUT_JSONL MAX_FRAMES RUNTIME_DATA_DIR"
            );
        }
        const int width = std::stoi(argv[1]);
        const int height = std::stoi(argv[2]);
        const fs::path models = argv[3];
        const fs::path output_path = argv[4];
        const size_t max_frames = static_cast<size_t>(std::stoul(argv[5]));
        const std::string runtime_data_dir = argv[6];
        if (width <= 0 || height <= 0 || max_frames == 0) {
            throw std::runtime_error("Invalid stream arguments");
        }
        if (fs::exists(output_path)) {
            throw std::runtime_error("Output JSONL already exists");
        }

        Ort::Env env(ORT_LOGGING_LEVEL_WARNING, "vision_stream");
        Ort::SessionOptions opts;
        opts.SetIntraOpNumThreads(2);
        opts.SetInterOpNumThreads(1);
        opts.SetGraphOptimizationLevel(GraphOptimizationLevel::ORT_ENABLE_ALL);
        Model palm_model(
            env,
            models / "palm_detection_mediapipe_2023feb.onnx",
            opts,
            192
        );
        Model hand_model(
            env,
            models / "handpose_estimation_mediapipe_2023feb.onnx",
            opts,
            224
        );

        const sign_engine::RuntimeData runtime =
            sign_engine::loadRuntimeData(
                runtime_data_dir
            );

        sign_engine::validateRuntimeData(
            runtime
        );

        std::cout
            << "Runtime data validated: "
            << runtime_data_dir
            << '\n';

        std::ofstream jsonl(output_path);
        if (!jsonl) {
            throw std::runtime_error("Could not create output JSONL");
        }

        RawTcpStreamer camera_streamer(5000);
        if (!camera_streamer.start()) {
            std::cerr
                << "[camera stream] disabled; sign recognition continues\n";
        }

        cv::Mat frame(height, width, CV_8UC3);
        std::vector<Palm> tracked_palms;
        std::vector<Hand> latest_hands;
        bool force_detection = true;
        size_t processed_frames = 0;
        size_t detected_frames = 0;
        size_t palm_frames = 0;
        double processing_ms_sum = 0.0;

        sign_engine::VisionRecordingDetections vision_recording;
        vision_recording.reserve(max_frames);

        while (processed_frames < max_frames) {
            const size_t bytes = frame.total() * frame.elemSize();
            std::cin.read(reinterpret_cast<char*>(frame.data),
                          static_cast<std::streamsize>(bytes));
            if (std::cin.gcount() == 0) {
                break;
            }
            if (static_cast<size_t>(std::cin.gcount()) != bytes) {
                throw std::runtime_error("Partial raw frame received");
            }
            cv::flip(frame, frame, 1);

            camera_streamer.sendFrame(frame);

            const auto start = std::chrono::steady_clock::now();
            bool used_palm_detector = force_detection ||
                processed_frames % kPalmInterval == 0;
            std::vector<Palm> inputs = used_palm_detector
                ? palms(frame, palm_model)
                : tracked_palms;
            if (used_palm_detector) {
                ++palm_frames;
            }

            bool failure = false;
            auto hands = run_hands(frame, inputs, hand_model, failure);

            // Accuracy fallback: reacquire immediately on the same frame.
            if (!used_palm_detector && (failure || hands.empty())) {
                used_palm_detector = true;
                ++palm_frames;
                inputs = palms(frame, palm_model);
                hands = run_hands(frame, inputs, hand_model, failure);
            }

            tracked_palms.clear();
            bool border = false;
            for (const auto& hand_result : hands) {
                tracked_palms.push_back(tracked_palm_from_hand(hand_result));
                border = border || near_border(hand_result, width, height);
            }
            force_detection = failure || hands.empty() || border;
            latest_hands = hands;
            if (!hands.empty()) {
                ++detected_frames;
            }

            vision_recording.push_back(
                to_vision_detections(hands)
            );

            const auto end = std::chrono::steady_clock::now();
            const double processing_ms =
                std::chrono::duration<double, std::milli>(end - start).count();
            processing_ms_sum += processing_ms;
            write_frame_json(
                jsonl,
                processed_frames,
                width,
                height,
                processing_ms,
                used_palm_detector,
                hands
            );
            ++processed_frames;
        }

        const sign_engine::VisionRecordingResult direct_recording =
            sign_engine::buildRecordingFramesFromVision(
                vision_recording
            );

        std::cout
            << "Direct input frames: "
            << direct_recording.input_frame_count
            << '\n'
            << "Direct adapter frames: "
            << direct_recording.frames.size()
            << '\n'
            << "Direct maximum hands: "
            << direct_recording.maximum_hands_per_frame
            << '\n'
            << "Direct single stabilize: "
            << (
                direct_recording.used_single_hand_stabilization
                    ? "true"
                    : "false"
            )
            << '\n';

        const sign_engine::SignRecognitionResult sign_result =
            sign_engine::classifyRecording(
                direct_recording.frames,
                runtime
            );

        std::cout
            << "========================================\n"
            << "DIRECT SIGN CLASSIFIER RESULT\n"
            << "========================================\n"
            << "valid           : "
            << (sign_result.valid ? "true" : "false")
            << '\n'
            << "final_id        : "
            << sign_result.final_id
            << '\n'
            << "stage           : "
            << sign_result.stage
            << '\n'
            << "is_nosign       : "
            << (sign_result.is_nosign ? "true" : "false")
            << '\n'
            << "source_mode     : "
            << sign_result.source_mode
            << '\n'
            << "selected_frames : "
            << sign_result.selected_frames
            << '\n'
            << "both_ratio      : "
            << sign_result.recording_stats.both_ratio
            << '\n'
            << "error           : "
            << sign_result.error
            << '\n'
            << "========================================\n";

        write_overlay_ppm(
            output_path.string() + ".last.ppm",
            frame,
            latest_hands
        );
        const double average_ms = processed_frames == 0
            ? 0.0
            : processing_ms_sum / processed_frames;
        std::cout << std::fixed << std::setprecision(3)
                  << "Processed frames: " << processed_frames << '\n'
                  << "Frames with hands: " << detected_frames << '\n'
                  << "Palm detector frames: " << palm_frames << '\n'
                  << "Average processing ms: " << average_ms << '\n'
                  << "Processing FPS: "
                  << (average_ms > 0.0 ? 1000.0 / average_ms : 0.0) << '\n'
                  << "JSONL: " << output_path << '\n'
                  << "Last overlay: " << output_path.string() << ".last.ppm\n";
        return processed_frames == max_frames ? 0 : 2;
    } catch (const std::exception& error) {
        std::cerr << "ERROR: " << error.what() << '\n';
        return 1;
    }
}
