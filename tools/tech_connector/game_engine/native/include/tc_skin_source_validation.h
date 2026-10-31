#ifndef TC_SKIN_SOURCE_VALIDATION_H
#define TC_SKIN_SOURCE_VALIDATION_H

#include <cmath>
#include <cstddef>
#include <cstdint>
#include <span>

namespace tc::runtime::detail {

// A vertex with no positive influence is legal: both skinning paths keep
// its authored rest position. Malformed offsets, indices and floats are not.
inline bool valid_skin_source(std::size_t vertex_count,
                              std::size_t maximum_influences,
                              std::size_t joint_count,
                              std::span<const float> rest_positions,
                              std::span<const std::uint32_t> offsets,
                              std::span<const std::uint32_t> joint_indices,
                              std::span<const float> weights) noexcept {
    if(vertex_count==0||rest_positions.size()/3!=vertex_count||
       rest_positions.size()%3!=0||offsets.size()!=vertex_count+1||
       offsets.front()!=0||joint_indices.size()!=weights.size()||
       offsets.back()!=weights.size())return false;
    for(const float value:rest_positions)if(!std::isfinite(value))return false;
    for(std::size_t index=0;index<vertex_count;++index){
        const auto begin=offsets[index],end=offsets[index+1];
        if(begin>end||end>weights.size()||end-begin>maximum_influences)return false;
    }
    for(std::size_t index=0;index<weights.size();++index){
        if(joint_indices[index]>=joint_count||!std::isfinite(weights[index])||
           weights[index]<0.0F)return false;
    }
    return true;
}

}  // namespace tc::runtime::detail

#endif
