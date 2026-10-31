#ifndef TC_GPU_RENDERER_H
#define TC_GPU_RENDERER_H

#include "tc_runtime_core.h"

#include <algorithm>
#include <array>
#include <filesystem>
#include <memory>
#include <string>

namespace tc::runtime {

namespace detail {
inline float pacing_adjusted_gpu_ms(float timestamp_ms,float present_wait_ms,bool vsync) noexcept {
    return std::max(0.0F,timestamp_ms-(vsync?present_wait_ms:0.0F));
}
}

enum class RenderBackend : std::uint8_t { automatic, d3d11, d3d12, vulkan, metal, null_backend };

struct RenderBackendCapabilities {
    RenderBackend backend{RenderBackend::null_backend};
    std::string name{"Null"};
    bool available{false};
    bool presentation{false};
    bool gpu_skinning{false};
    bool compute{false};
    bool ray_tracing{false};
};

struct GpuRenderProfile {
    float gpu_ms{0.0F};
    float render_scale{1.0F};
    int render_width{0};
    int render_height{0};
    bool temporal{false};
    bool dynamic_resolution{false};
    std::size_t gpu_skinned_draws{0};
    std::size_t cpu_skinned_draws{0};
    std::size_t submitted_geometry_draws{0};
    std::size_t submitted_shadow_draws{0};
    std::array<float, 4> gpu_samples_ms{};
    std::size_t gpu_sample_count{0};
    bool vsync{true};
    std::size_t gpu_skin_stream_sets{0};
    std::size_t gpu_skin_palette_sets{0};
    float present_wall_ms{0.0F};
    float cpu_skin_wall_ms{0.0F};
    float shadow_wall_ms{0.0F};
    float geometry_wall_ms{0.0F};
    float post_wall_ms{0.0F};
    std::size_t inverse_bind_reads{0};
    std::size_t inverse_bind_cache_hits{0};
    std::size_t ui_compositions{0};
    std::size_t ui_texture_creations{0};
    std::size_t ui_image_decodes{0};
    float ui_bitmap_ms{0.0F};
    float ui_draw_ms{0.0F};
    float ui_copy_ms{0.0F};
    float ui_text_ms{0.0F};
    float ui_blend_ms{0.0F};
    float ui_upload_ms{0.0F};
    float gpu_work_estimate_ms{0.0F};
    std::size_t history_allocations{0};
};

struct GpuAdapterInfo {
    std::string name;
    std::uint32_t vendor_id{0};
    std::uint32_t device_id{0};
    std::uint64_t dedicated_video_memory_bytes{0};
    bool software{false};
};

class GpuRenderer {
public:
    explicit GpuRenderer(RenderBackend requested_backend = RenderBackend::automatic);
    ~GpuRenderer();
    GpuRenderer(const GpuRenderer&) = delete;
    GpuRenderer& operator=(const GpuRenderer&) = delete;

    bool initialize(void* native_window, int width, int height, std::string& error);
    bool resize(int width, int height, std::string& error);
    void set_vsync(bool enabled) noexcept;
    void set_cpu_skinning_diagnostic(bool enabled) noexcept;
    void set_ui_scale(float scale) noexcept;
    bool render(const World& world, std::string& error,
                const std::filesystem::path* capture_before_present = nullptr);
    bool capture_bmp(const std::filesystem::path& path, std::string& error);
    [[nodiscard]] bool ready() const noexcept;
    [[nodiscard]] GpuRenderProfile profile() const noexcept;
    [[nodiscard]] GpuAdapterInfo adapter_info() const;
    [[nodiscard]] RenderBackend backend() const noexcept;
    [[nodiscard]] RenderBackendCapabilities capabilities() const;

private:
    class Implementation;
    std::unique_ptr<Implementation> implementation_;
};

}  // namespace tc::runtime

#endif
