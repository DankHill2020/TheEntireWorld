#include "tc_gpu_renderer.h"

#include <cassert>

int main() {
    using tc::runtime::GpuRenderer;
    using tc::runtime::RenderBackend;

#if defined(_WIN32)
    const GpuRenderer automatic;
    const auto automatic_capabilities = automatic.capabilities();
    assert(automatic.backend() == RenderBackend::d3d11);
    assert(automatic_capabilities.available);
    assert(automatic_capabilities.presentation);
    assert(automatic_capabilities.gpu_skinning);
    assert(automatic_capabilities.compute);

    const GpuRenderer d3d12(RenderBackend::d3d12);
    assert(d3d12.backend() == RenderBackend::d3d12);
    assert(!d3d12.capabilities().available);
#else
    const GpuRenderer automatic;
    assert(automatic.backend() == RenderBackend::null_backend);
    assert(automatic.capabilities().available);
    assert(!automatic.capabilities().presentation);
#endif

    const GpuRenderer vulkan(RenderBackend::vulkan);
    assert(vulkan.backend() == RenderBackend::vulkan);
    assert(!vulkan.capabilities().available);
    assert(!vulkan.capabilities().presentation);

    const GpuRenderer metal(RenderBackend::metal);
    assert(metal.backend() == RenderBackend::metal);
    assert(!metal.capabilities().available);
    assert(!metal.capabilities().ray_tracing);
    return 0;
}
