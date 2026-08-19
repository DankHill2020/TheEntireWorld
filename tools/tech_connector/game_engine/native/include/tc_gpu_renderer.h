#ifndef TC_GPU_RENDERER_H
#define TC_GPU_RENDERER_H

#include "tc_runtime_core.h"

#include <filesystem>
#include <memory>
#include <string>

namespace tc::runtime {

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
};

class GpuRenderer {
public:
    explicit GpuRenderer(RenderBackend requested_backend = RenderBackend::automatic);
    ~GpuRenderer();
    GpuRenderer(const GpuRenderer&) = delete;
    GpuRenderer& operator=(const GpuRenderer&) = delete;

    bool initialize(void* native_window, int width, int height, std::string& error);
    bool resize(int width, int height, std::string& error);
    bool render(const World& world, std::string& error);
    bool capture_bmp(const std::filesystem::path& path, std::string& error);
    [[nodiscard]] bool ready() const noexcept;
    [[nodiscard]] GpuRenderProfile profile() const noexcept;
    [[nodiscard]] RenderBackend backend() const noexcept;
    [[nodiscard]] RenderBackendCapabilities capabilities() const;

private:
    class Implementation;
    std::unique_ptr<Implementation> implementation_;
};

}  // namespace tc::runtime

#endif
