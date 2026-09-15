#include <opencv2/core.hpp>
#ifndef VISION_RAW_ONLY
#include <opencv2/imgcodecs.hpp>
#endif
#include <onnxruntime_cxx_api.h>
#include <string>
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
    std::array<cv::Point3f,21> world_xyz;
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
        result.world_xyz[i] = {
            out[3][i*3],
            out[3][i*3+1],
            out[3][i*3+2]
        };
        float x=float((double(out[0][i*3])-112.0)*scale),y=float((double(out[0][i*3+1])-112.0)*scale);
        double ox=double(x)*rotation.at<double>(0,0)+double(y)*rotation.at<double>(1,0);
        double oy=double(x)*rotation.at<double>(0,1)+double(y)*rotation.at<double>(1,1);
        result.xy[i]={float((ox+ocx)+first.bias.x),float((oy+ocy)+first.bias.y)};
        if(!std::isfinite(result.xy[i].x)||!std::isfinite(result.xy[i].y)) throw std::runtime_error("Nonfinite XY");
    }
    return true;
}
#ifndef VISION_PHOTO_NO_MAIN
int main(int argc,char** argv) {
    try {
        if(argc!=4) throw std::runtime_error("Usage: vision_photo IMAGE MODEL_DIR NEW_OUTPUT_DIR");
        cv::Mat image;
#ifdef VISION_RAW_ONLY
        // Local regression uses identical decoded BGR bytes, avoiding codec differences.
        const fs::path fixture=argv[1];
        auto wh=read<int32_t>(fixture/"image_wh_i32.bin",2);
        if(wh[0]<=0||wh[1]<=0) throw std::runtime_error("Invalid raw size");
        auto bytes=read<uint8_t>(fixture/"image_bgr_u8.bin",size_t(wh[0])*wh[1]*3);
        image=cv::Mat(wh[1],wh[0],CV_8UC3,bytes.data()).clone();
#else
        image=cv::imread(argv[1],cv::IMREAD_COLOR);
#endif
        if(image.empty()) throw std::runtime_error("Could not read image");
        fs::path models=argv[2],output=argv[3];
        if(fs::exists(output)) throw std::runtime_error("Output directory already exists; choose a new name");
        Ort::Env env(ORT_LOGGING_LEVEL_WARNING,"vision_photo");
        Ort::SessionOptions opts;opts.SetIntraOpNumThreads(1);opts.SetInterOpNumThreads(1);
        opts.SetGraphOptimizationLevel(GraphOptimizationLevel::ORT_ENABLE_ALL);
        Model palm_model(env,models/"palm_detection_mediapipe_2023feb.onnx",opts,192);
        Model hand_model(env,models/"handpose_estimation_mediapipe_2023feb.onnx",opts,224);
        auto selected=palms(image,palm_model);
        std::vector<Hand> hands;
        for(const auto& p:selected) {Hand h{};if(hand(image,p,hand_model,h)) hands.push_back(h);}
        fs::create_directories(output);
        std::ofstream json(output/"result.json");
        json<<std::setprecision(12)<<"{\n\"image_size_wh\":["<<image.cols<<","<<image.rows<<"],\n"
            <<"\"coordinate_system\":\"original unflipped image pixels\",\n"
            <<"\"mirror_input\":false,\n"
            <<"\"opencv\":\""<<CV_VERSION<<"\",\"onnxruntime\":\""<<OrtGetApiBase()->GetVersionString()<<"\",\n"
            <<"\"provider\":\"CPUExecutionProvider\",\"hands\":[\n";
        auto canvas=image.clone();
        const std::array<std::array<int,2>,21> edges{{{0,1},{1,2},{2,3},{3,4},{0,5},{5,6},{6,7},{7,8},{5,9},{9,10},{10,11},{11,12},{9,13},{13,14},{14,15},{15,16},{13,17},{17,18},{18,19},{19,20},{0,17}}};
        for(size_t j=0;j<hands.size();++j) {
            const auto& h=hands[j];if(j)json<<",\n";
            const char* model_hand=h.handedness>0.5?"RIGHT":"LEFT";
            const char* physical_hand=h.handedness>0.5?"LEFT":"RIGHT";
            json<<"{\"anchor_index\":"<<h.palm.id<<",\"palm_score\":"<<h.palm.score
                <<",\"hand_confidence\":"<<h.confidence<<",\"handedness_raw\":"<<h.handedness
                <<",\"model_hand\":\""<<model_hand<<"\",\"physical_hand\":\""<<physical_hand
                <<"\",\"palm_box_xyxy\":[";
            for(int i=0;i<4;++i){if(i)json<<",";json<<h.palm.box[i];}
            json<<"],\"landmarks_xy\":[";
            for(int i=0;i<21;++i){if(i)json<<",";json<<"["<<h.xy[i].x<<","<<h.xy[i].y<<"]";}
            json<<"]}";
            for(auto e:edges)cv::line(canvas,cv::Point(cvRound(h.xy[e[0]].x),cvRound(h.xy[e[0]].y)),cv::Point(cvRound(h.xy[e[1]].x),cvRound(h.xy[e[1]].y)),cv::Scalar(0,255,0),1);
            for(int i=0;i<21;++i){cv::Point p(cvRound(h.xy[i].x),cvRound(h.xy[i].y));cv::circle(canvas,p,2,cv::Scalar(0,0,255),-1);cv::putText(canvas,std::to_string(i),p+cv::Point(3,-3),cv::FONT_HERSHEY_SIMPLEX,0.3,cv::Scalar(0,255,255),1);}
        }
        json<<"\n]}\n";json.close();if(!json)throw std::runtime_error("JSON write failed");
        #ifdef VISION_RAW_ONLY
        std::ofstream ppm(output/"overlay.ppm",std::ios::binary);
        ppm<<"P6\n"<<canvas.cols<<" "<<canvas.rows<<"\n255\n";
        cv::Mat overlay_rgb;cv::cvtColor(canvas,overlay_rgb,cv::COLOR_BGR2RGB);
        ppm.write(reinterpret_cast<const char*>(overlay_rgb.data),overlay_rgb.total()*3);
        ppm.close();if(!ppm)throw std::runtime_error("PPM write failed");
#else
        if(!cv::imwrite((output/"overlay.png").string(),canvas))throw std::runtime_error("Image write failed");
#endif
        std::cout<<"Accepted hands: "<<hands.size()<<"\nResults: "<<output<<"\n";
        return 0;
    } catch(const std::exception& e) {std::cerr<<"ERROR: "<<e.what()<<"\n";return 1;}
}
#endif  // VISION_PHOTO_NO_MAIN
