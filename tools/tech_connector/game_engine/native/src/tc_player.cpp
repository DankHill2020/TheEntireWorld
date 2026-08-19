#include "tc_runtime_core.h"
#include "tc_audio_mixer.h"
#include "tc_gpu_renderer.h"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

#if defined(_WIN32)
#include <windows.h>
#include <mmsystem.h>
#include <shellapi.h>
#endif

using Clock = std::chrono::steady_clock;
using tc::runtime::EntityId;
using tc::runtime::Runtime;

struct Options {
    std::filesystem::path scene;
    std::filesystem::path screenshot;
    std::filesystem::path log;
    int frames{0};
    int screenshot_frame{2};
    bool headless{false};
    bool pie{false};
    bool trace_graph{false};
    bool show_help{false};
    bool renderer_capabilities{false};
    bool require_renderer{false};
    tc::runtime::RenderBackend renderer{tc::runtime::RenderBackend::automatic};
    std::string option_error;
};

bool parse_renderer(const std::string& value, tc::runtime::RenderBackend& backend) {
    if (value == "automatic" || value == "auto") backend = tc::runtime::RenderBackend::automatic;
    else if (value == "d3d11") backend = tc::runtime::RenderBackend::d3d11;
    else if (value == "d3d12") backend = tc::runtime::RenderBackend::d3d12;
    else if (value == "vulkan") backend = tc::runtime::RenderBackend::vulkan;
    else if (value == "metal") backend = tc::runtime::RenderBackend::metal;
    else if (value == "null") backend = tc::runtime::RenderBackend::null_backend;
    else return false;
    return true;
}

Options parse_options(const std::vector<std::string>& args) {
    Options options;
    for (std::size_t index = 1; index < args.size(); ++index) {
        const auto& value = args[index];
        if (value == "--scene" && index + 1 < args.size()) options.scene = args[++index];
        else if (value == "--frames" && index + 1 < args.size()) options.frames = std::stoi(args[++index]);
        else if (value == "--screenshot" && index + 1 < args.size()) options.screenshot = args[++index];
        else if (value == "--screenshot-frame" && index + 1 < args.size()) options.screenshot_frame = std::max(1, std::stoi(args[++index]));
        else if (value == "--log" && index + 1 < args.size()) options.log = args[++index];
        else if (value == "--headless") options.headless = true;
        else if (value == "--pie") options.pie = true;
        else if (value == "--trace-graph") options.trace_graph = true;
        else if (value == "--help" || value == "-h") options.show_help = true;
        else if (value == "--renderer" && index + 1 < args.size()) {
            const auto renderer_name = args[++index];
            if (!parse_renderer(renderer_name, options.renderer)) {
                options.option_error = "Unsupported renderer '" + renderer_name +
                    "'. Choose automatic, d3d11, d3d12, vulkan, metal, or null.";
            }
        }
        else if (value == "--renderer") options.option_error = "--renderer requires a backend name.";
        else if (value == "--renderer-capabilities") options.renderer_capabilities = true;
        else if (value == "--require-renderer") options.require_renderer = true;
        else if (options.scene.empty() && !value.starts_with("--")) options.scene = value;
        else if (value.starts_with("--")) options.option_error = "Unknown option '" + value + "'.";
    }
    return options;
}

void print_usage() {
    std::cout
        << "TC Player\n"
        << "Usage: tc_player --scene <file.tcruntime> [options]\n\n"
        << "  --headless                     Run without a window.\n"
        << "  --frames <count>               Stop after a fixed number of frames.\n"
        << "  --log <path>                   Write frame profiles and diagnostics.\n"
        << "  --renderer <backend>           automatic, d3d11, d3d12, vulkan, metal, or null.\n"
        << "  --renderer-capabilities        Print selected backend capabilities as JSON.\n"
        << "  --require-renderer             Fail instead of using the software fallback.\n"
        << "  --help                         Show this help.\n";
}

int print_renderer_capabilities(const Options& options) {
    tc::runtime::GpuRenderer renderer(options.renderer);
    const auto capabilities = renderer.capabilities();
    std::cout << "{\"backend\":\"" << capabilities.name
              << "\",\"available\":" << (capabilities.available ? "true" : "false")
              << ",\"presentation\":" << (capabilities.presentation ? "true" : "false")
              << ",\"gpu_skinning\":" << (capabilities.gpu_skinning ? "true" : "false")
              << ",\"compute\":" << (capabilities.compute ? "true" : "false")
              << ",\"ray_tracing\":" << (capabilities.ray_tracing ? "true" : "false") << "}\n";
    return capabilities.available ? 0 : 4;
}

void append_profile(const Options& options, const Runtime& runtime, int frame, const tc::runtime::GpuRenderer* gpu = nullptr) {
    if (options.log.empty()) return;
    std::ofstream stream(options.log, std::ios::app);
    const auto& profile = runtime.profile();
    stream << "{\"type\":\"frame\",\"frame\":" << frame
           << ",\"frame_ms\":" << profile.frame_ms
           << ",\"graph_ms\":" << profile.graph_ms
           << ",\"physics_ms\":" << profile.physics_ms
           << ",\"physics_integration_ms\":" << profile.physics_integration_ms
           << ",\"physics_joint_ms\":" << profile.physics_joint_ms
           << ",\"physics_collision_ms\":" << profile.physics_collision_ms
           << ",\"physics_joint_iterations\":" << profile.physics_joint_iterations
           << ",\"maximum_joint_position_error\":" << profile.maximum_joint_position_error
           << ",\"entities\":" << profile.entities
           << ",\"draw_calls\":" << profile.draw_calls
           << ",\"broadphase_pairs\":" << profile.broadphase_pairs
           << ",\"collision_contacts\":" << profile.collision_contacts
           << ",\"solver_islands\":" << profile.solver_islands
           << ",\"sleeping_bodies\":" << profile.sleeping_bodies;
    if (gpu && gpu->ready()) {
        const auto render = gpu->profile();
        stream << ",\"gpu_ms\":" << render.gpu_ms
               << ",\"render_scale\":" << render.render_scale
               << ",\"render_width\":" << render.render_width
               << ",\"render_height\":" << render.render_height
               << ",\"temporal\":" << (render.temporal ? "true" : "false")
               << ",\"dynamic_resolution\":" << (render.dynamic_resolution ? "true" : "false");
        stream << ",\"gpu_skinned_draws\":" << render.gpu_skinned_draws
               << ",\"cpu_skinned_draws\":" << render.cpu_skinned_draws;
    }
    stream << "}\n";
}

void append_traces(const Options& options, const Runtime& runtime, std::size_t& consumed) {
    if (options.log.empty() || consumed >= runtime.debug_trace().size()) return;
    std::ofstream stream(options.log, std::ios::app);
    while (consumed < runtime.debug_trace().size()) {
        const auto& trace = runtime.debug_trace()[consumed++];
        if (options.trace_graph || !trace.starts_with("OK ")) stream << trace << '\n';
    }
}

int run_headless(const Options& options) {
    Runtime runtime;
    std::string error;
    if (!runtime.load_manifest(options.scene, error)) {
        std::cerr << options.scene.string() << ":1: error TC0001: " << error << '\n';
        return 2;
    }
    runtime.begin_play();
    std::size_t consumed_traces = 0;
    const int frame_count = options.frames > 0 ? options.frames : 120;
    for (int frame = 0; frame < frame_count; ++frame) {
        runtime.set_input_axis(frame < frame_count / 2 ? 1.0F : 0.0F, 0.0F);
        runtime.tick(1.0F / 60.0F);
        append_profile(options, runtime, frame);
        append_traces(options, runtime, consumed_traces);
    }
    for (const auto& trace : runtime.debug_trace()) std::cout << trace << '\n';
    std::cout << "TC_PLAYER_OK frames=" << frame_count
              << " entities=" << runtime.world().entities().size()
              << " events=" << runtime.world().events.size() << '\n';
    return 0;
}

#if defined(_WIN32)

struct WindowState {
    explicit WindowState(tc::runtime::RenderBackend backend):gpu(backend){}
    Runtime runtime;
    Options options;
    Clock::time_point previous{Clock::now()};
    int frame{0};
    std::size_t played_events{0};
    std::size_t logged_traces{0};
    bool screenshot_written{false};
    tc::runtime::AudioMixer audio;
    tc::runtime::GpuRenderer gpu;
};

COLORREF color(float red, float green, float blue, float exposure = 1.0F) {
    auto channel = [exposure](float value) {
        const float mapped = 1.0F - std::exp(-std::max(0.0F, value) * exposure);
        return static_cast<BYTE>(std::clamp(std::pow(mapped, 1.0F / 2.2F) * 255.0F, 0.0F, 255.0F));
    };
    return RGB(channel(red), channel(green), channel(blue));
}

struct Vec3 { float x; float y; float z; };

Vec3 add(Vec3 a, Vec3 b) { return {a.x + b.x, a.y + b.y, a.z + b.z}; }
Vec3 subtract(Vec3 a, Vec3 b) { return {a.x - b.x, a.y - b.y, a.z - b.z}; }
Vec3 multiply(Vec3 value, float scale) { return {value.x * scale, value.y * scale, value.z * scale}; }
float dot(Vec3 a, Vec3 b) { return a.x * b.x + a.y * b.y + a.z * b.z; }
Vec3 cross(Vec3 a, Vec3 b) { return {a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x}; }
Vec3 normalize(Vec3 value) {
    const float length = std::sqrt(std::max(1.0e-8F, dot(value, value)));
    return multiply(value, 1.0F / length);
}

struct ViewProjection {
    Vec3 camera;
    Vec3 right;
    Vec3 up;
    Vec3 forward;
    float focal;
    int width;
    int height;
};

ViewProjection active_view(const tc::runtime::World& world, int width, int height) {
    Vec3 camera{0.0F, 4.0F, -14.0F};
    Vec3 target{0.0F, 1.0F, 0.0F};
    float field_of_view = 55.0F;
    for (const auto& [entity, component] : world.cameras) {
        if (!component.active || !world.transforms.contains(entity)) continue;
        const auto position = world.transforms.at(entity).position;
        camera = {static_cast<float>(position.x), static_cast<float>(position.y), static_cast<float>(position.z)};
        target = {static_cast<float>(component.look_at.x), static_cast<float>(component.look_at.y), static_cast<float>(component.look_at.z)};
        field_of_view = component.field_of_view_degrees;
        break;
    }
    const Vec3 forward = normalize(subtract(target, camera));
    const Vec3 right = normalize(cross(forward, {0.0F, 1.0F, 0.0F}));
    const Vec3 up = normalize(cross(right, forward));
    const float radians = std::clamp(field_of_view, 10.0F, 150.0F) * 3.14159265F / 180.0F;
    return {camera, right, up, forward, static_cast<float>(height) * 0.5F / std::tan(radians * 0.5F), width, height};
}

bool project(Vec3 point, const ViewProjection& view, POINT& screen, float& depth) {
    const Vec3 relative = subtract(point, view.camera);
    depth = dot(relative, view.forward);
    if (depth <= 0.05F) return false;
    screen = {
        static_cast<LONG>(view.width * 0.5F + dot(relative, view.right) * view.focal / depth),
        static_cast<LONG>(view.height * 0.5F - dot(relative, view.up) * view.focal / depth),
    };
    return true;
}

Vec3 pbr_face_color(
    const tc::runtime::Renderable& material,
    Vec3 normal,
    Vec3 world_position,
    Vec3 camera,
    const tc::runtime::World& world
) {
    const Vec3 base{material.base_color.x, material.base_color.y, material.base_color.z};
    Vec3 result = multiply(base, 0.035F);
    const Vec3 view_direction = normalize(subtract(camera, world_position));
    const float roughness = std::clamp(material.roughness, 0.045F, 1.0F);
    const float metallic = std::clamp(material.metallic, 0.0F, 1.0F);
    for (const auto& [unused, source] : world.lights) {
        static_cast<void>(unused);
        const Vec3 light_direction = normalize({-source.direction.x, -source.direction.y, -source.direction.z});
        const Vec3 half_direction = normalize(add(view_direction, light_direction));
        const float ndotl = std::max(0.0F, dot(normal, light_direction));
        const float ndotv = std::max(0.001F, dot(normal, view_direction));
        const float ndoth = std::max(0.0F, dot(normal, half_direction));
        const float vdoth = std::max(0.0F, dot(view_direction, half_direction));
        const float alpha = roughness * roughness;
        const float denominator = ndoth * ndoth * (alpha * alpha - 1.0F) + 1.0F;
        const float distribution = alpha * alpha / std::max(0.001F, 3.14159265F * denominator * denominator);
        const float k = (roughness + 1.0F) * (roughness + 1.0F) / 8.0F;
        const float geometry = (ndotv / (ndotv * (1.0F - k) + k)) * (ndotl / (ndotl * (1.0F - k) + k));
        const float fresnel_power = std::pow(1.0F - vdoth, 5.0F);
        const Vec3 f0 = add(multiply({0.04F, 0.04F, 0.04F}, 1.0F - metallic), multiply(base, metallic));
        const Vec3 fresnel = add(f0, multiply(subtract({1.0F, 1.0F, 1.0F}, f0), fresnel_power));
        const Vec3 specular = multiply(fresnel, distribution * geometry / std::max(0.004F, 4.0F * ndotv * ndotl));
        const Vec3 diffuse = multiply(base, (1.0F - metallic) / 3.14159265F);
        const float energy = source.intensity * ndotl;
        result = add(result, multiply({
            (diffuse.x + specular.x) * source.color.x,
            (diffuse.y + specular.y) * source.color.y,
            (diffuse.z + specular.z) * source.color.z,
        }, energy));
    }
    return result;
}

void draw_world(HDC target, RECT client, WindowState& state) {
    const int width = client.right - client.left;
    const int height = client.bottom - client.top;
    HDC buffer = CreateCompatibleDC(target);
    HBITMAP bitmap = CreateCompatibleBitmap(target, width, height);
    const HGDIOBJ old_bitmap = SelectObject(buffer, bitmap);

    HBRUSH background = CreateSolidBrush(RGB(9, 14, 20));
    FillRect(buffer, &client, background);
    DeleteObject(background);

    HPEN grid_pen = CreatePen(PS_SOLID, 1, RGB(28, 43, 54));
    const HGDIOBJ old_pen = SelectObject(buffer, grid_pen);
    for (int index = -12; index <= 12; ++index) {
        const int x = width / 2 + index * width / 24;
        MoveToEx(buffer, width / 2, height / 2, nullptr);
        LineTo(buffer, x, height);
    }
    for (int row = 0; row < 9; ++row) {
        const float t = static_cast<float>(row) / 8.0F;
        const int y = static_cast<int>(height * (0.55F + 0.43F * t * t));
        MoveToEx(buffer, 0, y, nullptr);
        LineTo(buffer, width, y);
    }
    SelectObject(buffer, old_pen);
    DeleteObject(grid_pen);

    const auto& world = state.runtime.world();
    const auto view = active_view(world, width, height);
    for (const auto& [entity, renderable] : world.renderables) {
        const auto transform_it = world.transforms.find(entity);
        if (transform_it == world.transforms.end()) continue;
        const auto& transform = transform_it->second;
        const Vec3 center{static_cast<float>(transform.position.x), static_cast<float>(transform.position.y), static_cast<float>(transform.position.z)};
        const Vec3 extent{transform.scale.x * 0.5F, transform.scale.y * 0.5F, transform.scale.z * 0.5F};
        const Vec3 vertices[8] = {
            add(center, {-extent.x, -extent.y, -extent.z}), add(center, {extent.x, -extent.y, -extent.z}),
            add(center, {extent.x, extent.y, -extent.z}), add(center, {-extent.x, extent.y, -extent.z}),
            add(center, {-extent.x, -extent.y, extent.z}), add(center, {extent.x, -extent.y, extent.z}),
            add(center, {extent.x, extent.y, extent.z}), add(center, {-extent.x, extent.y, extent.z}),
        };

        if (renderable.casts_shadow) {
            HBRUSH shadow = CreateSolidBrush(RGB(2, 4, 5));
            const HGDIOBJ prior = SelectObject(buffer, shadow);
            POINT shadow_center{};
            float shadow_depth = 0.0F;
            if (project({center.x + 0.7F, 0.01F, center.z + 0.45F}, view, shadow_center, shadow_depth)) {
                const int radius = std::max(3, static_cast<int>(view.focal * std::max(extent.x, extent.z) / shadow_depth));
                Ellipse(buffer, shadow_center.x - radius, shadow_center.y - radius / 4,
                        shadow_center.x + radius, shadow_center.y + radius / 4);
            }
            SelectObject(buffer, prior);
            DeleteObject(shadow);
        }

        struct Face { int indices[4]; Vec3 normal; float depth; };
        Face faces[6] = {
            {{0, 3, 2, 1}, {0.0F, 0.0F, -1.0F}, 0.0F}, {{4, 5, 6, 7}, {0.0F, 0.0F, 1.0F}, 0.0F},
            {{0, 4, 7, 3}, {-1.0F, 0.0F, 0.0F}, 0.0F}, {{1, 2, 6, 5}, {1.0F, 0.0F, 0.0F}, 0.0F},
            {{0, 1, 5, 4}, {0.0F, -1.0F, 0.0F}, 0.0F}, {{3, 7, 6, 2}, {0.0F, 1.0F, 0.0F}, 0.0F},
        };
        for (auto& face : faces) {
            face.depth = 0.0F;
            for (const int index : face.indices) face.depth += dot(subtract(vertices[index], view.camera), view.forward) * 0.25F;
        }
        std::sort(std::begin(faces), std::end(faces), [](const Face& left, const Face& right) { return left.depth > right.depth; });
        for (const auto& face_data : faces) {
            if (dot(face_data.normal, subtract(view.camera, center)) <= 0.0F) continue;
            POINT polygon[4]{};
            bool visible = true;
            for (int corner = 0; corner < 4; ++corner) {
                float projected_depth = 0.0F;
                visible = visible && project(vertices[face_data.indices[corner]], view, polygon[corner], projected_depth);
            }
            if (!visible) continue;
            const Vec3 shaded = pbr_face_color(renderable, face_data.normal, center, view.camera, world);
            HBRUSH face_brush = CreateSolidBrush(color(shaded.x, shaded.y, shaded.z, 0.62F));
            HPEN edge = CreatePen(PS_SOLID, 1, RGB(71, 155, 178));
            const HGDIOBJ prior_brush = SelectObject(buffer, face_brush);
            const HGDIOBJ prior_pen = SelectObject(buffer, edge);
            Polygon(buffer, polygon, 4);
            SelectObject(buffer, prior_brush);
            SelectObject(buffer, prior_pen);
            DeleteObject(face_brush);
            DeleteObject(edge);
        }
    }

    SetBkMode(buffer, TRANSPARENT);
    SetTextColor(buffer, RGB(220, 238, 241));
    const auto& profile = state.runtime.profile();
    const std::wstring title(state.runtime.world().hud_text.begin(), state.runtime.world().hud_text.end());
    TextOutW(buffer, 18, 16, title.c_str(), static_cast<int>(title.size()));
    std::wostringstream stats;
    stats << L"Frame " << state.frame << L"  " << std::fixed << std::setprecision(2)
          << profile.frame_ms << L" ms  Entities " << profile.entities << L"  Draws " << profile.draw_calls;
    const auto stats_text = stats.str();
    TextOutW(buffer, 18, 40, stats_text.c_str(), static_cast<int>(stats_text.size()));
    const wchar_t* help = L"WASD Move  |  F5 Save  |  Esc Exit";
    TextOutW(buffer, 18, height - 32, help, lstrlenW(help));

    BitBlt(target, 0, 0, width, height, buffer, 0, 0, SRCCOPY);

    if (!state.options.screenshot.empty() && !state.screenshot_written && state.frame >= 2) {
        BITMAPINFOHEADER header{};
        header.biSize = sizeof(header);
        header.biWidth = width;
        header.biHeight = height;
        header.biPlanes = 1;
        header.biBitCount = 24;
        header.biCompression = BI_RGB;
        const DWORD row_size = static_cast<DWORD>((width * 3 + 3) & ~3);
        std::vector<unsigned char> pixels(static_cast<std::size_t>(row_size) * height);
        BITMAPINFO info{};
        info.bmiHeader = header;
        GetDIBits(buffer, bitmap, 0, static_cast<UINT>(height), pixels.data(), &info, DIB_RGB_COLORS);
        BITMAPFILEHEADER file{};
        file.bfType = 0x4D42;
        file.bfOffBits = sizeof(file) + sizeof(header);
        file.bfSize = file.bfOffBits + static_cast<DWORD>(pixels.size());
        std::ofstream output(state.options.screenshot, std::ios::binary | std::ios::trunc);
        output.write(reinterpret_cast<const char*>(&file), sizeof(file));
        output.write(reinterpret_cast<const char*>(&header), sizeof(header));
        output.write(reinterpret_cast<const char*>(pixels.data()), static_cast<std::streamsize>(pixels.size()));
        state.screenshot_written = true;
    }

    SelectObject(buffer, old_bitmap);
    DeleteObject(bitmap);
    DeleteDC(buffer);
}

LRESULT CALLBACK window_proc(HWND window, UINT message, WPARAM wparam, LPARAM lparam) {
    auto* state = reinterpret_cast<WindowState*>(GetWindowLongPtrW(window, GWLP_USERDATA));
    if (message == WM_CREATE) {
        auto* create = reinterpret_cast<CREATESTRUCTW*>(lparam);
        auto* created_state = static_cast<WindowState*>(create->lpCreateParams);
        SetWindowLongPtrW(window, GWLP_USERDATA, reinterpret_cast<LONG_PTR>(created_state));
        RECT client{};
        GetClientRect(window, &client);
        std::string renderer_error;
        if (!created_state->gpu.initialize(window, client.right, client.bottom, renderer_error)) {
            OutputDebugStringA(("TC GPU fallback: " + renderer_error + "\n").c_str());
            if (created_state->options.require_renderer) return -1;
        }
        SetTimer(window, 1, 16, nullptr);
        return 0;
    }
    if (message == WM_TIMER && state != nullptr) {
        const auto now = Clock::now();
        const float delta = std::clamp(std::chrono::duration<float>(now - state->previous).count(), 0.0F, 0.066F);
        state->previous = now;
        const float x = (GetAsyncKeyState('D') < 0 ? 1.0F : 0.0F) - (GetAsyncKeyState('A') < 0 ? 1.0F : 0.0F);
        const float y = (GetAsyncKeyState('W') < 0 ? 1.0F : 0.0F) - (GetAsyncKeyState('S') < 0 ? 1.0F : 0.0F);
        state->runtime.set_input_axis(x, y);
        state->runtime.tick(delta);
        state->audio.update();
        ++state->frame;
        append_traces(state->options, state->runtime, state->logged_traces);
        while (state->played_events < state->runtime.world().events.size()) {
            const auto& event = state->runtime.world().events[state->played_events++];
            if (event.starts_with("Audio:")) {
                std::string source = event.substr(6);
                if (const auto asset = state->runtime.world().assets.find(source); asset != state->runtime.world().assets.end()) {
                    source = asset->second.source.string();
                }
                std::string audio_error;
                if (!state->audio.play(source, 1.0F, audio_error)) {
                    OutputDebugStringA(("TC Audio: " + audio_error + "\n").c_str());
                }
            } else if (event == "SaveRequested") {
                std::string error;
                const auto save = state->options.scene.parent_path() / (state->runtime.world().save_slot + ".tcsave");
                state->runtime.save(save, error);
            }
        }
        std::string renderer_error;
        if (state->gpu.ready()) {
            state->gpu.render(state->runtime.world(), renderer_error);
            if (!state->options.screenshot.empty() && !state->screenshot_written && state->frame >= state->options.screenshot_frame) {
                state->screenshot_written = state->gpu.capture_bmp(state->options.screenshot, renderer_error);
            }
        } else {
            InvalidateRect(window, nullptr, FALSE);
        }
        append_profile(state->options, state->runtime, state->frame, &state->gpu);
        if (state->options.frames > 0 && state->frame >= state->options.frames) {
            DestroyWindow(window);
        }
        return 0;
    }
    if (message == WM_KEYDOWN && state != nullptr) {
        if (wparam == VK_ESCAPE) PostMessageW(window, WM_CLOSE, 0, 0);
        if (wparam == VK_F5) {
            std::string error;
            const auto save = state->options.scene.parent_path() / (state->runtime.world().save_slot + ".tcsave");
            state->runtime.save(save, error);
        }
        return 0;
    }
    if (message == WM_PAINT && state != nullptr) {
        PAINTSTRUCT paint{};
        HDC dc = BeginPaint(window, &paint);
        RECT client{};
        GetClientRect(window, &client);
        if (!state->gpu.ready()) draw_world(dc, client, *state);
        EndPaint(window, &paint);
        return 0;
    }
    if (message == WM_SIZE && state != nullptr && state->gpu.ready() && wparam != SIZE_MINIMIZED) {
        std::string resize_error;
        state->gpu.resize(LOWORD(lparam), HIWORD(lparam), resize_error);
        return 0;
    }
    if (message == WM_DESTROY) {
        KillTimer(window, 1);
        PostQuitMessage(0);
        return 0;
    }
    return DefWindowProcW(window, message, wparam, lparam);
}

int run_windowed(const Options& options, HINSTANCE instance) {
    WindowState state(options.renderer);
    state.options = options;
    std::string error;
    if (!state.runtime.load_manifest(options.scene, error)) {
        MessageBoxA(nullptr, error.c_str(), "TC Player", MB_ICONERROR | MB_OK);
        return 2;
    }
    state.runtime.begin_play();
    state.audio.initialize(error);
    const wchar_t* class_name = L"TheEntireWorldTcPlayer";
    WNDCLASSW window_class{};
    window_class.lpfnWndProc = window_proc;
    window_class.hInstance = instance;
    window_class.hCursor = LoadCursor(nullptr, IDC_ARROW);
    window_class.lpszClassName = class_name;
    RegisterClassW(&window_class);
    const std::wstring title = options.pie ? L"TC Play In Editor" : L"The Entire World Player";
    HWND window = CreateWindowExW(0, class_name, title.c_str(), WS_OVERLAPPEDWINDOW | WS_VISIBLE,
                                  CW_USEDEFAULT, CW_USEDEFAULT, 1280, 720, nullptr, nullptr, instance, &state);
    if (window == nullptr) return 3;
    MSG message{};
    while (GetMessageW(&message, nullptr, 0, 0) > 0) {
        TranslateMessage(&message);
        DispatchMessageW(&message);
    }
    for (const auto& trace : state.runtime.debug_trace()) {
        OutputDebugStringA((trace + "\n").c_str());
    }
    return 0;
}

std::vector<std::string> windows_arguments() {
    int count = 0;
    LPWSTR* values = CommandLineToArgvW(GetCommandLineW(), &count);
    std::vector<std::string> result;
    for (int index = 0; index < count; ++index) {
        const int size = WideCharToMultiByte(CP_UTF8, 0, values[index], -1, nullptr, 0, nullptr, nullptr);
        std::string text(static_cast<std::size_t>(size), '\0');
        WideCharToMultiByte(CP_UTF8, 0, values[index], -1, text.data(), size, nullptr, nullptr);
        text.pop_back();
        result.push_back(std::move(text));
    }
    LocalFree(values);
    return result;
}

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE, PWSTR, int) {
    const auto options = parse_options(windows_arguments());
    if (options.show_help) { print_usage(); return 0; }
    if (!options.option_error.empty()) { std::cerr << options.option_error << '\n'; return 1; }
    if (options.renderer_capabilities) return print_renderer_capabilities(options);
    if (options.scene.empty()) {
        MessageBoxW(nullptr, L"Pass --scene <file.tcruntime>.", L"TC Player", MB_ICONINFORMATION | MB_OK);
        return 1;
    }
    return options.headless ? run_headless(options) : run_windowed(options, instance);
}

#else

int main(int argc, char** argv) {
    std::vector<std::string> arguments(argv, argv + argc);
    const auto options = parse_options(arguments);
    if (options.show_help) { print_usage(); return 0; }
    if (!options.option_error.empty()) { std::cerr << options.option_error << '\n'; return 1; }
    if (options.renderer_capabilities) return print_renderer_capabilities(options);
    if (options.scene.empty()) {
        std::cerr << "Pass --scene <file.tcruntime>.\n";
        return 1;
    }
    return run_headless(options);
}

#endif
