#include <opencv2/core.hpp>
#ifndef VISION_RAW_ONLY
#include <opencv2/imgcodecs.hpp>
#endif
#include <onnxruntime_cxx_api.h>
#include <string>
#include <opencv2/imgproc.hpp>
#include <opencv2/videoio.hpp>

#include "vision_frame_hands.hpp"
#include "runtime_data.hpp"
#include "sign_runtime.hpp"
#include <algorithm>
#include <array>
#include <cmath>
#include <chrono>
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


struct Palm {
    int id;
    double score;
    std::array<double,4> box;
    std::array<cv::Point2d,7> points;
};
struct Hand {
    Palm palm;
    double confidence, handedness;
    std::array<cv::Point2f,21> xy;
};

// NHWC RGB float32, matching NumPy's explicit division.
std::vector<float> tensor_rgb(const cv::Mat& rgb) {
    if (rgb.type()!=CV_8UC3) throw std::runtime_error("Expected RGB uint8");
    std::vector<float> v(rgb.total()*3);
    for(int y=0;y<rgb.rows;++y) {
        const auto* row=rgb.ptr<uint8_t>(y);
        for(int x=0;x<rgb.cols*3;++x)
            v[size_t(y)*rgb.cols*3+x]=float(row[x])/255.0f;
    }
    return v;
}
class Model {
    Ort::Session session_;
    int side_;
public:
    Model(Ort::Env& env, const fs::path& path, const Ort::SessionOptions& opts,int side)
        :session_(env,path.c_str(),opts),side_(side) {
        if(session_.GetInputCount()!=1) throw std::runtime_error("Expected one input");
        auto type=session_.GetInputTypeInfo(0);
        auto t=type.GetTensorTypeAndShapeInfo();
        if(t.GetElementType()!=ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT ||
           t.GetShape()!=std::vector<int64_t>{1,side,side,3})
            throw std::runtime_error("Unexpected model input shape/type");
    }
    std::vector<std::vector<float>> run(std::vector<float>& input,
            const std::vector<const char*>& names,
            const std::vector<std::vector<int64_t>>& shapes) {
        if(input.size()!=size_t(side_)*side_*3) throw std::runtime_error("Input size");
        auto memory=Ort::MemoryInfo::CreateCpu(OrtArenaAllocator,OrtMemTypeDefault);
        std::array<int64_t,4> shape{1,side_,side_,3};
        auto tensor=Ort::Value::CreateTensor<float>(memory,input.data(),input.size(),shape.data(),4);
        const char* input_name="input_1";
        auto values=session_.Run(Ort::RunOptions{nullptr},&input_name,&tensor,1,names.data(),names.size());
        std::vector<std::vector<float>> outputs;
        for(size_t i=0;i<values.size();++i) {
            auto t=values[i].GetTensorTypeAndShapeInfo();
            if(t.GetElementType()!=ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT || t.GetShape()!=shapes.at(i))
                throw std::runtime_error("Unexpected model output shape/type");
            const auto* p=values[i].GetTensorData<float>();
            outputs.emplace_back(p,p+t.GetElementCount());
            for(float x:outputs.back()) if(!std::isfinite(x)) throw std::runtime_error("Nonfinite output");
        }
        return outputs;
    }
};

double overlap(const Palm& a,const Palm& b) {
    const auto& x=a.box; const auto& y=b.box;
    double intersection=std::max(0.0,std::min(x[2],y[2])-std::max(x[0],y[0]))*
                        std::max(0.0,std::min(x[3],y[3])-std::max(x[1],y[1]));
    double u=(x[2]-x[0])*(x[3]-x[1])+(y[2]-y[0])*(y[3]-y[1])-intersection;
    return u>0?intersection/u:0;
}
std::vector<Palm> palms(const cv::Mat& image,Model& model) {
    double ratio=std::min(192.0/image.rows,192.0/image.cols);
    int nh=int(image.rows*ratio),nw=int(image.cols*ratio);
    if(nh<1||nw<1) throw std::runtime_error("Image aspect ratio too extreme");
    int top=(192-nh)/2,left=(192-nw)/2;
    cv::Mat resized,padded,rgb;
    cv::resize(image,resized,{nw,nh},0,0,cv::INTER_LINEAR);
    cv::copyMakeBorder(resized,padded,top,192-nh-top,left,192-nw-left,cv::BORDER_CONSTANT,cv::Scalar(0,0,0));
    cv::cvtColor(padded,rgb,cv::COLOR_BGR2RGB);
    auto input=tensor_rgb(rgb);
    auto out=model.run(input,{"Identity","Identity_1"},{{1,2016,18},{1,2016,1}});
    const double scale=std::max(image.cols,image.rows);
    const std::array<double,2> bias{double(int(left/ratio)),double(int(top/ratio))};
    std::vector<Palm> candidates;
    int id=0;
    for(auto config:std::array<std::array<int,2>,2>{{{24,2},{12,6}}}) {
        for(int y=0;y<config[0];++y) for(int x=0;x<config[0];++x) for(int r=0;r<config[1];++r,++id) {
            double logit=out[1][id];
            double score=logit>=0?1/(1+std::exp(-logit)):std::exp(logit)/(1+std::exp(logit));
            if(score<=0.3) continue;
            Palm p{}; p.id=id; p.score=score;
            const std::array<double,2> anchor{(x+0.5)/config[0],(y+0.5)/config[0]};
            for(int d=0;d<2;++d) {
                double center=double(out[0][id*18+d])/192.0;
                double wh=double(out[0][id*18+2+d])/192.0;
                p.box[d]=(center-wh/2+anchor[d])*scale-bias[d];
                p.box[2+d]=(center+wh/2+anchor[d])*scale-bias[d];
                for(int k=0;k<7;++k) {
                    double v=(double(out[0][id*18+4+k*2+d])/192.0+anchor[d])*scale-bias[d];
                    if(d==0) p.points[k].x=v; else p.points[k].y=v;
                }
            }
            if(p.box[2]>p.box[0]&&p.box[3]>p.box[1]) candidates.push_back(p);
        }
    }
    std::cout<<"Palm candidates: "<<candidates.size()<<"\n";
    std::stable_sort(candidates.begin(),candidates.end(),[](const Palm&a,const Palm&b){return a.score>b.score;});
    std::vector<Palm> selected;
    for(const auto& p:candidates) {
        bool suppressed=false;
        for(const auto& q:selected) if(overlap(p,q)>0.3) {suppressed=true;break;}
        if(!suppressed) selected.push_back(p);
    }
    std::cout<<"After NMS: "<<selected.size()<<"\n";
    return selected;
}

bool hand(const cv::Mat& image,const Palm& p,Model& model,Hand& result) {
    auto first=crop_pad(image,{p.box[0],p.box[1]},{p.box[2],p.box[3]},true);
    cv::Mat rgb;
    cv::cvtColor(first.image,rgb,cv::COLOR_BGR2RGB);
    std::array<cv::Point2d,7> local;
    for(int i=0;i<7;++i) local[i]=p.points[i]-cv::Point2d(first.bias.x,first.bias.y);
    auto delta=local[2]-local[0];
    double pi=std::acos(-1.0),rad=pi/2-std::atan2(-delta.y,delta.x);
    rad-=2*pi*std::floor((rad+pi)/(2*pi));
    double angle=rad*180/pi;
    cv::Point2f center(float((first.box[0]+first.box[2])/2.0-first.bias.x),float((first.box[1]+first.box[3])/2.0-first.bias.y));
    auto matrix=cv::getRotationMatrix2D(center,angle,1.0);
    cv::Mat rotated;
    cv::warpAffine(rgb,rotated,matrix,rgb.size(),cv::INTER_LINEAR,cv::BORDER_CONSTANT,cv::Scalar(0,0,0));
    cv::Point2d lo(1e100,1e100),hi(-1e100,-1e100);
    for(auto point:local) {
        double x=matrix.at<double>(0,0)*point.x+matrix.at<double>(0,1)*point.y+matrix.at<double>(0,2);
        double y=matrix.at<double>(1,0)*point.x+matrix.at<double>(1,1)*point.y+matrix.at<double>(1,2);
        lo.x=std::min(lo.x,x);lo.y=std::min(lo.y,y);hi.x=std::max(hi.x,x);hi.y=std::max(hi.y,y);
    }
    auto second=crop_pad(rotated,lo,hi,false);
    cv::Mat roi;
    cv::resize(second.image,roi,{224,224},0,0,cv::INTER_AREA);
    auto input=tensor_rgb(roi);
    auto out=model.run(input,{"Identity","Identity_1","Identity_2","Identity_3"},{{1,63},{1,1},{1,1},{1,63}});
    std::cout<<"Anchor "<<p.id<<": palm="<<p.score<<", hand="<<out[1][0]<<"\n";
    if(out[1][0]<0.8f) return false;
    cv::Mat inverse;
    cv::invertAffineTransform(matrix,inverse);
    double cx=(second.box[0]+second.box[2])/2.0,cy=(second.box[1]+second.box[3])/2.0;
    double ocx=inverse.at<double>(0,0)*cx+inverse.at<double>(0,1)*cy+inverse.at<double>(0,2);
    double ocy=inverse.at<double>(1,0)*cx+inverse.at<double>(1,1)*cy+inverse.at<double>(1,2);
    double scale=std::max((second.box[2]-second.box[0])/224.0,(second.box[3]-second.box[1])/224.0);
    auto rotation=cv::getRotationMatrix2D(cv::Point2f(0,0),angle,1.0);
    result.palm=p;result.confidence=out[1][0];result.handedness=out[2][0];
    for(int i=0;i<21;++i) {
        float x=float((double(out[0][i*3])-112.0)*scale),y=float((double(out[0][i*3+1])-112.0)*scale);
        double ox=double(x)*rotation.at<double>(0,0)+double(y)*rotation.at<double>(1,0);
        double oy=double(x)*rotation.at<double>(0,1)+double(y)*rotation.at<double>(1,1);
        result.xy[i]={float((ox+ocx)+first.bias.x),float((oy+ocy)+first.bias.y)};
        if(!std::isfinite(result.xy[i].x)||!std::isfinite(result.xy[i].y)) throw std::runtime_error("Nonfinite XY");
    }
    return true;
}

namespace {

constexpr std::array<const char*,15> CLASS_NAMES = {
    "에어컨",
    "문잠그다",
    "꺼지다",
    "덥다",
    "춥다",
    "구조",
    "연기",
    "아프다",
    "괜찮다",
    "감사",
    "점등",
    "소등",
    "온도",
    "배고프다",
    "목마르다"
};

std::string className(int id) {
    if(id < 0 || id >= static_cast<int>(CLASS_NAMES.size())) {
        return "NO-SIGN";
    }

    return CLASS_NAMES[static_cast<std::size_t>(id)];
}

}

int main(int argc,char** argv) {
    try {
        if(argc != 4) {
            throw std::runtime_error(
                "Usage: vision_sign_host VIDEO MODEL_DIR RUNTIME_DATA_DIR"
            );
        }

        const fs::path video_path = argv[1];
        const fs::path models = argv[2];
        const std::string runtime_dir = argv[3];

        cv::VideoCapture capture(
            video_path.string()
        );

        if(!capture.isOpened()) {
            throw std::runtime_error(
                "Could not open video: " +
                video_path.string()
            );
        }

        Ort::Env env(
            ORT_LOGGING_LEVEL_WARNING,
            "vision_sign"
        );

        Ort::SessionOptions opts;

        opts.SetIntraOpNumThreads(1);
        opts.SetInterOpNumThreads(1);

        opts.SetGraphOptimizationLevel(
            GraphOptimizationLevel::ORT_ENABLE_ALL
        );

        Model palm_model(
            env,
            models /
            "palm_detection_mediapipe_2023feb.onnx",
            opts,
            192
        );

        Model hand_model(
            env,
            models /
            "handpose_estimation_mediapipe_2023feb.onnx",
            opts,
            224
        );

        sign_engine::VisionRecordingDetections recording;

        std::size_t decoded_frames = 0;
        std::size_t frames_with_hands = 0;
        std::size_t accepted_hands = 0;

        double vision_total_ms = 0.0;

        const auto pipeline_begin =
            std::chrono::steady_clock::now();

        cv::Mat frame;

        while(capture.read(frame)) {

            if(frame.empty()) {
                continue;
            }

            ++decoded_frames;

            const auto vision_begin =
                std::chrono::steady_clock::now();

            // Existing classifier/adapter contract:
            // landmark coordinates are mirrored camera pixels.
            cv::Mat mirrored;

            cv::flip(
                frame,
                mirrored,
                1
            );

            auto selected =
                palms(
                    mirrored,
                    palm_model
                );

            sign_engine::VisionFrameDetections
                frame_detections;

            for(const auto& p : selected) {

                Hand h{};

                if(
                    !hand(
                        mirrored,
                        p,
                        hand_model,
                        h
                    )
                ) {
                    continue;
                }

                sign_engine::VisionHandDetection detection{};

                detection.handedness_raw =
                    h.handedness;

                detection.confidence =
                    h.confidence;

                for(int i = 0; i < 21; ++i) {

                    detection.landmarks.points[i].x =
                        h.xy[i].x;

                    detection.landmarks.points[i].y =
                        h.xy[i].y;
                }

                frame_detections.push_back(
                    std::move(detection)
                );

                ++accepted_hands;
            }

            if(!frame_detections.empty()) {
                ++frames_with_hands;
            }

            recording.push_back(
                std::move(frame_detections)
            );

            const auto vision_end =
                std::chrono::steady_clock::now();

            vision_total_ms +=
                std::chrono::duration<double, std::milli>(
                    vision_end - vision_begin
                ).count();
        }

        capture.release();

        const auto pipeline_end =
            std::chrono::steady_clock::now();

        const double pipeline_ms =
            std::chrono::duration<double, std::milli>(
                pipeline_end - pipeline_begin
            ).count();

        if(decoded_frames == 0) {
            throw std::runtime_error(
                "Video contained no decoded frames"
            );
        }

        const auto classify_begin =
            std::chrono::steady_clock::now();

        const auto adapted =
            sign_engine::buildRecordingFramesFromVision(
                recording
            );

        const auto runtime =
            sign_engine::loadRuntimeData(
                runtime_dir
            );

        sign_engine::validateRuntimeData(
            runtime
        );

        const auto result =
            sign_engine::classifyRecording(
                adapted.frames,
                runtime
            );

        const auto classify_end =
            std::chrono::steady_clock::now();

        const double classify_ms =
            std::chrono::duration<double, std::milli>(
                classify_end - classify_begin
            ).count();

        const double avg_vision_ms =
            decoded_frames > 0
                ? vision_total_ms / decoded_frames
                : 0.0;

        const double effective_vision_fps =
            vision_total_ms > 0.0
                ? decoded_frames * 1000.0 / vision_total_ms
                : 0.0;

        const double effective_pipeline_fps =
            pipeline_ms > 0.0
                ? decoded_frames * 1000.0 / pipeline_ms
                : 0.0;

        std::cout
            << "\n========================================\n"
            << "VISION + SIGN INTEGRATED RESULT\n"
            << "========================================\n";

        std::cout
            << "decoded_frames    : "
            << decoded_frames << "\n"

            << "frames_with_hands : "
            << frames_with_hands << "\n"

            << "accepted_hands    : "
            << accepted_hands << "\n"

            << "pipeline_ms       : "
            << pipeline_ms << "\n"

            << "vision_total_ms   : "
            << vision_total_ms << "\n"

            << "avg_vision_ms     : "
            << avg_vision_ms << "\n"

            << "vision_fps        : "
            << effective_vision_fps << "\n"

            << "pipeline_fps      : "
            << effective_pipeline_fps << "\n"

            << "classify_ms       : "
            << classify_ms << "\n"

            << "adapter_frames    : "
            << adapted.frames.size() << "\n"

            << "maximum_hands     : "
            << adapted.maximum_hands_per_frame
            << "\n";

        if(adapted.has_median_handedness) {

            std::cout
                << "median_raw        : "
                << adapted.median_handedness_raw
                << "\n"

                << "stabilized_hand   : "
                << adapted.stabilized_physical_hand
                << "\n";
        }

        std::cout
            << "\nvalid             : "
            << (result.valid ? "true" : "false")
            << "\n"

            << "final_id          : "
            << result.final_id
            << "\n"

            << "class             : "
            << className(result.final_id)
            << "\n"

            << "stage             : "
            << result.stage
            << "\n"

            << "is_nosign         : "
            << (result.is_nosign ? "true" : "false")
            << "\n"

            << "source_mode       : "
            << result.source_mode
            << "\n"

            << "selected_frames   : "
            << result.selected_frames
            << "\n"

            << "total_frames      : "
            << result.recording_stats.total_frames
            << "\n"

            << "left_frames       : "
            << result.recording_stats.left_count
            << "\n"

            << "right_frames      : "
            << result.recording_stats.right_count
            << "\n"

            << "both_frames       : "
            << result.recording_stats.both_count
            << "\n"

            << "both_ratio        : "
            << result.recording_stats.both_ratio
            << "\n"

            << "error             : "
            << result.error
            << "\n"

            << "========================================\n";

        if(result.valid && !result.is_nosign) {
            std::cout
                << "\n>>> "
                << className(result.final_id)
                << "\n";
        }
        else if(result.valid && result.is_nosign) {
            std::cout
                << "\n>>> NO-SIGN\n";
        }
        else {
            std::cout
                << "\n>>> INVALID INPUT\n";
        }

        return 0;
    }
    catch(const std::exception& e) {

        std::cerr
            << "ERROR: "
            << e.what()
            << "\n";

        return 1;
    }
}
