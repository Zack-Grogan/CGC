// Resident adapter for the NVIDIA Audio2Face-3D SDK's public executor API.
#include "audio2face/audio2face.h"
#include "audio2x/cuda_utils.h"
#include <cuda_runtime_api.h>
#include <nlohmann/json.hpp>
#include <cmath>
#include <fstream>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <vector>

using Json = nlohmann::json;
void check(std::error_code error) {
    if (error) throw std::runtime_error(error.message());
}
struct Destroyer {
    template<class T> void operator()(T* pointer) const { if (pointer) pointer->Destroy(); }
};
template<class T> using Owned = std::unique_ptr<T, Destroyer>;
struct Frames {
    std::vector<std::vector<float>> weights;
    std::vector<std::int64_t> timestamps;
    std::string error;
};
bool collect(void* userdata, const nva2f::IBlendshapeExecutor::DeviceResults& result) {
    auto& frames = *static_cast<Frames*>(userdata);
    std::vector<float> values(result.weights.Size());
    auto error = cudaMemcpyAsync(values.data(), result.weights.Data(), values.size()*sizeof(float), cudaMemcpyDeviceToHost, result.cudaStream);
    if (error == cudaSuccess) error = cudaStreamSynchronize(result.cudaStream);
    if (error != cudaSuccess) { frames.error = cudaGetErrorString(error); return false; }
    for (float value: values) if (!std::isfinite(value)) { frames.error="Nonfinite blendshape weight"; return false; }
    frames.weights.push_back(std::move(values));
    frames.timestamps.push_back(result.timeStampCurrentFrame);
    return true;
}
int main(int argc, char** argv) {
    auto* output = std::cout.rdbuf();
    std::cout.rdbuf(std::cerr.rdbuf());
    std::ostream protocol(output);
    auto send = [&](const Json& value) { protocol << "CGC_A2F_JSON " << value.dump() << std::endl; };
    try {
        if (argc!=2) throw std::runtime_error("Supply model.json");
        Owned<nva2f::IDiffusionModel::IGeometryModelInfo> model_info;
        nva2f::IDiffusionModel::IGeometryModelInfo* raw_info=nullptr;
        Owned<nva2f::IBlendshapeExecutorBundle> bundle(nva2f::ReadDiffusionBlendshapeSolveExecutorBundle(
            1, argv[1], nva2f::IGeometryExecutor::ExecutionOption::SkinTongue, true, 2, true, &raw_info, nullptr));
        model_info.reset(raw_info);
        if (!bundle || !model_info) throw std::runtime_error("Audio2Face bundle initialization failed");
        auto& executor=bundle->GetExecutor();
        if (executor.GetResultType()!=nva2f::IBlendshapeExecutor::ResultsType::DEVICE) throw std::runtime_error("Expected the GPU blendshape solver");
        std::size_t numerator=0,denominator=0; executor.GetFrameRate(numerator,denominator);
        send({{"ready",true},{"sample_rate",executor.GetSamplingRate()},{"fps_numerator",numerator},{"fps_denominator",denominator},{"weights",executor.GetWeightCount()},{"identity","Mark"}});
        std::string line;
        while (std::getline(std::cin,line)) {
            try {
                auto request=Json::parse(line);
                std::ifstream input(request.at("samples").get<std::string>(),std::ios::binary|std::ios::ate);
                if (!input) throw std::runtime_error("Cannot read float audio samples");
                auto bytes=static_cast<std::streamoff>(input.tellg());
                if (bytes<=0 || bytes%sizeof(float)!=0) throw std::runtime_error("Invalid float audio length");
                std::vector<float> samples(static_cast<std::size_t>(bytes)/sizeof(float));
                input.seekg(0); input.read(reinterpret_cast<char*>(samples.data()),bytes);
                for(float value:samples) if(!std::isfinite(value)) throw std::runtime_error("Nonfinite audio sample");
                check(executor.Reset(0)); check(bundle->GetAudioAccumulator(0).Reset()); check(bundle->GetEmotionAccumulator(0).Reset());
                Frames frames;
                check(executor.SetResultsCallback(collect,&frames));
                auto stream=bundle->GetCudaStream().Data();
                check(bundle->GetEmotionAccumulator(0).Accumulate(0,model_info->GetNetworkInfo().GetDefaultEmotion(),stream));
                check(bundle->GetEmotionAccumulator(0).Close());
                check(bundle->GetAudioAccumulator(0).Accumulate(nva2x::HostTensorFloatConstView{samples.data(),samples.size()},stream));
                check(bundle->GetAudioAccumulator(0).Close());
                while(nva2x::GetNbReadyTracks(executor)>0) check(executor.Execute(nullptr));
                check(executor.Wait(0)); check(bundle->GetCudaStream().Synchronize());
                if(!frames.error.empty()) throw std::runtime_error(frames.error);
                if(frames.weights.empty()) throw std::runtime_error("Audio2Face produced no frames");
                Json result={{"sample_rate",executor.GetSamplingRate()},{"timestamps",frames.timestamps},{"weights",frames.weights},{"identity","Mark"},{"fps_numerator",numerator},{"fps_denominator",denominator}};
                std::ofstream file(request.at("output").get<std::string>()); file<<result.dump();
                send({{"ok",true},{"frames",frames.weights.size()},{"weight_count",executor.GetWeightCount()}});
            } catch(const std::exception& error) { send({{"ok",false},{"error",error.what()}}); }
        }
        return 0;
    } catch(const std::exception& error) { send({{"ready",false},{"error",error.what()}}); return 1; }
}
