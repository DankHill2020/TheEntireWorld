#include "tc_runtime_core.h"
#include "tc_audio_mixer.h"
#include "tc_gamepad_input.h"
#include "tc_gpu_renderer.h"

#include <algorithm>
#include <array>
#include <chrono>
#include <cctype>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <iterator>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <thread>
#include <vector>

#if defined(_WIN32)
#include <windows.h>
#include <Xinput.h>
#include <mmsystem.h>
#include <psapi.h>
#include <shellapi.h>
#endif

using Clock = std::chrono::steady_clock;
using tc::runtime::EntityId;
using tc::runtime::Runtime;

std::filesystem::path sidecar_path(std::filesystem::path path, const char* suffix) {
    path += suffix;
    return path;
}

std::filesystem::path argument_path(const std::string& value) {
#if defined(_WIN32)
    // wWinMain converts UTF-16 arguments to UTF-8; path(string) interprets
    // those bytes as the local ANSI code page and corrupts non-ASCII names.
    return std::filesystem::path(std::u8string(value.begin(), value.end()));
#else
    return std::filesystem::path(value);
#endif
}

std::string path_utf8(const std::filesystem::path& path) {
#if defined(_WIN32)
    const auto text = path.u8string();
    return std::string(text.begin(), text.end());
#else
    return path.string();
#endif
}

struct Options {
    std::filesystem::path scene;
    std::filesystem::path screenshot;
    std::filesystem::path log;
    std::filesystem::path verify_save_roundtrip;
    std::filesystem::path debug_snapshot;
    std::filesystem::path debug_paused_screenshot;
    std::filesystem::path input_profile;
    std::filesystem::path audio_profile;
    std::filesystem::path save_dir;
    int frames{0};
    int screenshot_frame{2};
    int break_frame{-1};
    std::optional<double> break_player_x;
    int window_width{1280};
    int window_height{720};
    float ui_scale{1.0F};
    bool headless{false};
    bool pie{false};
    bool trace_graph{false};
    bool scripted_mode{false};
    bool scripted_input{false};
    bool scripted_dpi_change{false};
    bool scripted_motion_demo{false};
    bool scripted_reverse_into_canopy{false};
    bool scripted_motion_soak{false};
    bool scripted_debug_step{false};
    bool scripted_minimize_restore{false};
    bool scripted_gamepad_demo{false};
    bool scripted_gamepad_ui{false};
    bool scripted_gamepad_load_ui{false};
    bool scripted_gamepad_disconnect_ui{false};
    bool scripted_gamepad_disconnect_rebind{false};
    bool scripted_gamepad_switch_ui{false};
    bool scripted_keyboard_ui{false};
    bool scripted_focus_loss_rebind{false};
    bool scripted_rebind_ui{false};
    bool scripted_profile_check{false};
    bool scripted_audio_mute_ui{false};
    bool scripted_audio_mute_once{false};
    bool scripted_audio_profile_check{false};
    bool scripted_audio_restart{false};
    bool scripted_save_load{false};
    bool scripted_load_only{false};
    bool scripted_load_then_save{false};
    std::string scripted_rebind_action{"jump"};
    bool show_help{false};
    bool renderer_capabilities{false};
    bool require_renderer{false};
    bool benchmark_unsynced{false};
    bool cpu_skinning_diagnostic{false};
    bool borderless{false};
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
        if (value.rfind("--scripted-", 0) == 0) options.scripted_mode = true;
        if (value == "--scene" && index + 1 < args.size()) options.scene = argument_path(args[++index]);
        else if (value == "--frames" && index + 1 < args.size()) options.frames = std::stoi(args[++index]);
        else if (value == "--screenshot" && index + 1 < args.size()) options.screenshot = argument_path(args[++index]);
        else if (value == "--screenshot-frame" && index + 1 < args.size()) options.screenshot_frame = std::max(1, std::stoi(args[++index]));
        else if (value == "--break-frame" && index + 1 < args.size()) options.break_frame = std::max(1, std::stoi(args[++index]));
        else if (value == "--break-player-x" && index + 1 < args.size()) {
            try {
                const auto threshold = std::stod(args[++index]);
                if (!std::isfinite(threshold)) options.option_error = "--break-player-x requires a finite number.";
                else options.break_player_x = threshold;
            } catch (const std::exception&) {
                options.option_error = "--break-player-x requires a finite number.";
            }
        }
        else if (value == "--window-width" && index + 1 < args.size()) options.window_width = std::clamp(std::stoi(args[++index]), 320, 7680);
        else if (value == "--window-height" && index + 1 < args.size()) options.window_height = std::clamp(std::stoi(args[++index]), 240, 4320);
        else if (value == "--borderless") options.borderless = true;
        else if (value == "--ui-scale" && index + 1 < args.size()) {
            try {
                const auto scale = std::stof(args[++index]);
                if (!std::isfinite(scale) || scale < 0.75F || scale > 2.0F)
                    options.option_error = "--ui-scale must be between 0.75 and 2.0.";
                else options.ui_scale = scale;
            } catch (const std::exception&) {
                options.option_error = "--ui-scale requires a number between 0.75 and 2.0.";
            }
        }
        else if (value == "--log" && index + 1 < args.size())
            options.log = tc::runtime::save_io_path(argument_path(args[++index]));
        else if (value == "--verify-save-roundtrip" && index + 1 < args.size())
            options.verify_save_roundtrip = tc::runtime::save_io_path(argument_path(args[++index]));
        else if (value == "--debug-snapshot" && index + 1 < args.size()) options.debug_snapshot = argument_path(args[++index]);
        else if (value == "--debug-paused-screenshot" && index + 1 < args.size()) options.debug_paused_screenshot = argument_path(args[++index]);
        else if (value == "--input-profile" && index + 1 < args.size()) options.input_profile = argument_path(args[++index]);
        else if (value == "--audio-profile" && index + 1 < args.size()) options.audio_profile = argument_path(args[++index]);
        else if (value == "--save-dir" && index + 1 < args.size()) options.save_dir = argument_path(args[++index]);
        else if (value == "--headless") options.headless = true;
        else if (value == "--scripted-input") options.scripted_input = true;
        else if (value == "--scripted-dpi-change") options.scripted_dpi_change = true;
        else if (value == "--scripted-motion-demo") options.scripted_motion_demo = true;
        else if (value == "--scripted-reverse-into-canopy") options.scripted_reverse_into_canopy = true;
        else if (value == "--scripted-motion-soak") options.scripted_motion_soak = true;
        else if (value == "--scripted-debug-step") options.scripted_debug_step = true;
        else if (value == "--scripted-minimize-restore") options.scripted_minimize_restore = true;
        else if (value == "--scripted-gamepad-demo") options.scripted_gamepad_demo = true;
        else if (value == "--scripted-gamepad-ui") options.scripted_gamepad_ui = true;
        else if (value == "--scripted-gamepad-load-ui") options.scripted_gamepad_load_ui = true;
        else if (value == "--scripted-gamepad-disconnect-ui") options.scripted_gamepad_disconnect_ui = true;
        else if (value == "--scripted-gamepad-disconnect-rebind") options.scripted_gamepad_disconnect_rebind = true;
        else if (value == "--scripted-gamepad-switch-ui") options.scripted_gamepad_switch_ui = true;
        else if (value == "--scripted-keyboard-ui") options.scripted_keyboard_ui = true;
        else if (value == "--scripted-focus-loss-rebind") options.scripted_focus_loss_rebind = true;
        else if (value == "--scripted-rebind-ui") options.scripted_rebind_ui = true;
        else if (value == "--scripted-profile-check") options.scripted_profile_check = true;
        else if (value == "--scripted-audio-mute-ui") options.scripted_audio_mute_ui = true;
        else if (value == "--scripted-audio-mute-once") {
            options.scripted_audio_mute_ui = true;
            options.scripted_audio_mute_once = true;
        }
        else if (value == "--scripted-audio-profile-check") options.scripted_audio_profile_check = true;
        else if (value == "--scripted-audio-restart") options.scripted_audio_restart = true;
        else if (value == "--scripted-save-load") options.scripted_save_load = true;
        else if (value == "--scripted-load-only") options.scripted_load_only = true;
        else if (value == "--scripted-load-then-save") options.scripted_load_then_save = true;
        else if (value == "--scripted-rebind-action" && index + 1 < args.size()) {
            options.scripted_rebind_action = args[++index];
            if (options.scripted_rebind_action != "jump" && options.scripted_rebind_action != "crouch" &&
                options.scripted_rebind_action != "crawl")
                options.option_error = "--scripted-rebind-action must be jump, crouch, or crawl.";
        }
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
        else if (value == "--benchmark-unsynced") options.benchmark_unsynced = true;
        else if (value == "--cpu-skinning-diagnostic") options.cpu_skinning_diagnostic = true;
        else if (options.scene.empty() && !value.starts_with("--")) options.scene = argument_path(value);
        else if (value.starts_with("--")) options.option_error = "Unknown option '" + value + "'.";
    }
    if (options.benchmark_unsynced && (options.frames <= 0 || options.headless))
        options.option_error = "--benchmark-unsynced requires a finite windowed --frames run.";
    if (options.cpu_skinning_diagnostic && (options.frames <= 0 || options.headless))
        options.option_error = "--cpu-skinning-diagnostic requires a finite windowed --frames run.";
    if (options.scripted_audio_restart && (options.frames < 3 || options.headless || options.log.empty()))
        options.option_error = "--scripted-audio-restart requires a windowed --frames run of at least 3 frames and --log.";
    if (options.scripted_dpi_change && (!options.scripted_input || options.headless || options.frames < 8))
        options.option_error = "--scripted-dpi-change requires a windowed --scripted-input run of at least 8 frames.";
    if (options.scripted_load_then_save && (options.headless || options.frames < 8))
        options.option_error = "--scripted-load-then-save requires a windowed run of at least 8 frames.";
    if (options.scripted_keyboard_ui && (options.headless || options.frames < 8))
        options.option_error = "--scripted-keyboard-ui requires a windowed run of at least 8 frames.";
    if (options.scripted_focus_loss_rebind && (options.headless || options.frames < 10))
        options.option_error = "--scripted-focus-loss-rebind requires a windowed run of at least 10 frames.";
    if (options.scripted_minimize_restore && (options.headless || options.frames < 8))
        options.option_error = "--scripted-minimize-restore requires a windowed run of at least 8 frames.";
    return options;
}

void print_usage() {
    std::cout
        << "TC Player\n"
        << "Usage: tc_player --scene <file.tcruntime> [options]\n\n"
        << "  --headless                     Run without a window.\n"
        << "  --frames <count>               Stop after a fixed number of frames.\n"
        << "  --log <path>                   Write frame profiles and diagnostics.\n"
        << "  --window-width/--window-height Set window size for responsive UI checks.\n"
        << "  --borderless                   Use an exact-client-size borderless window.\n"
        << "  --ui-scale <0.75..2.0>       Scale HUD controls, text, and hit targets.\n"
        << "  --verify-save-roundtrip <path> Save and reload headless Player state.\n"
        << "  --save-dir <path>              Override the user save-game directory.\n"
        << "  --scripted-save-load           Exercise F5 save and F6 load in the window.\n"
        << "  --scripted-load-only           Exercise F6 load in a fresh player process.\n"
        << "  --debug-snapshot <path>       Write an F9 world-inspection JSON snapshot.\n"
        << "  --debug-paused-screenshot <path> Capture the paused in-app inspector.\n"
        << "  --scripted-input               Drive the windowed Player for acceptance testing.\n"
        << "  --scripted-dpi-change          Simulate a DPI change during scripted input.\n"
        << "  --scripted-load-then-save      Load an existing save, then save the restored state.\n"
        << "  --scripted-motion-demo         Exercise traversal, jump, and extended reverse travel.\n"
        << "  --scripted-reverse-into-canopy Probe reverse collision after the motion demo.\n"
        << "  --scripted-motion-soak         Repeat bounded movement and stance actions after the motion demo.\n"
        << "  --scripted-gamepad-demo        Exercise the same path through simulated Xbox controls.\n"
        << "  --scripted-gamepad-ui          Exercise runtime UI focus with simulated Xbox controls.\n"
        << "  --scripted-gamepad-load-ui     Exercise runtime Load button with simulated Xbox controls.\n"
        << "  --scripted-gamepad-disconnect-ui Exercise keyboard fallback after gamepad UI disconnect.\n"
        << "  --scripted-gamepad-disconnect-rebind Exercise pending rebind cancellation on disconnect.\n"
        << "  --scripted-gamepad-switch-ui   Exercise UI ownership handoff between simulated pads.\n"
        << "  --scripted-keyboard-ui         Exercise Tab/Enter/Escape UI navigation.\n"
        << "  --scripted-focus-loss-rebind   Verify focus loss cancels pending UI rebinding.\n"
        << "  --scripted-debug-step        Exercise pause, snapshot, single-step, and resume.\n"
        << "  --scripted-minimize-restore Exercise suspended simulation and renderer recovery.\n"
        << "  F9 snapshot, F10 pause/resume, F11 single-step while paused.\n"
        << "  PC controls: bound movement keys (WASD by default), Space jump, C crouch, V crawl.\n"
        << "  Hold right mouse button and drag to orbit the follow camera; left-click UI buttons.\n"
        << "  Tab/Shift+Tab focus UI, Enter activate, Esc dismiss or exit, F5 save, F6 load.\n"
        << "  --break-frame <n>            Pause before simulation frame n+1 for inspection.\n"
        << "  --break-player-x <n>         Pause when Player reaches x >= n.\n"
        << "  --scripted-rebind-ui           Exercise in-game Jump rebinding with simulated input.\n"
        << "  --input-profile <path>         Override the per-user gamepad binding profile.\n"
        << "  --scripted-profile-check       Verify a saved binding with simulated input.\n"
        << "  --scripted-audio-restart       Exercise output restart after the first audio event.\n"
        << "  --renderer <backend>           automatic, d3d11, d3d12, vulkan, metal, or null.\n"
        << "  --renderer-capabilities        Print selected backend capabilities as JSON.\n"
        << "  --require-renderer             Fail instead of using the software fallback.\n"
        << "  --benchmark-unsynced          Fixed-frame GPU-work probe; disables vsync, not a gameplay pacing test.\n"
        << "  --cpu-skinning-diagnostic      Force CPU skin fallback for graphical correctness testing.\n"
        << "  --help                         Show this help.\n";
}

void append_json_string(std::ostream& stream, const std::string& value) {
    constexpr char hex[] = "0123456789abcdef";
    stream << '"';
    for (const unsigned char character : value) {
        if (character == '"' || character == '\\') stream << '\\' << static_cast<char>(character);
        else if (character < 0x20U) stream << "\\u00" << hex[character >> 4U] << hex[character & 0x0fU];
        else stream << static_cast<char>(character);
    }
    stream << '"';
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

void append_profile(const Options& options, const Runtime& runtime, int frame,
                    const tc::runtime::GpuRenderer* gpu = nullptr, double frame_interval_ms = 0.0,
                    double simulation_delta_seconds = 0.0, double render_wall_ms = 0.0) {
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
    if (frame_interval_ms > 0.0) stream << ",\"frame_interval_ms\":" << frame_interval_ms;
    if (render_wall_ms > 0.0) stream << ",\"render_wall_ms\":" << render_wall_ms;
    if (simulation_delta_seconds > 0.0)
        stream << ",\"simulation_delta_seconds\":" << simulation_delta_seconds;
    const auto player = runtime.world().find_entity("Player");
    if (const auto found = runtime.world().transforms.find(player); player != 0U && found != runtime.world().transforms.end()) {
        stream << ",\"player_x\":" << found->second.position.x
               << ",\"player_y\":" << found->second.position.y
               << ",\"player_z\":" << found->second.position.z;
        const auto& clips = runtime.world().animation_clips;
        const auto active = clips.find(runtime.active_animation_id());
        if (active != clips.end()) {
            const auto skeleton = runtime.world().skeletons.find(active->second.skeleton_id);
            if (skeleton != runtime.world().skeletons.end()) {
                stream << ",\"ankle_model_positions\":{";
                bool first_ankle = true;
                for (const auto name : {"l_ankle", "r_ankle"}) {
                    const auto joint = std::find_if(skeleton->second.joints.begin(), skeleton->second.joints.end(),
                        [name](const auto& item) { return item.name == name; });
                    if (joint == skeleton->second.joints.end()) continue;
                    if (!first_ankle) stream << ',';
                    first_ankle = false;
                    append_json_string(stream, name);
                    stream << ":[" << joint->world[12] << ',' << joint->world[13] << ',' << joint->world[14] << ']';
                }
                stream << "},\"player_visual_scale\":[" << found->second.scale.x << ','
                       << found->second.scale.y << ',' << found->second.scale.z << ']'
                       << ",\"player_visual_rotation_degrees\":[" << found->second.rotation.x << ','
                       << found->second.rotation.y << ',' << found->second.rotation.z << ']';
            }
        }
    }
    stream << ",\"active_animation\":";
    append_json_string(stream, runtime.active_animation_id());
    stream << ",\"motion_match_searches\":" << runtime.motion_match_searches();
    stream << ",\"contact_pairs\":[";
    bool first_contact=true;
    for(const auto& contact:runtime.physics_contacts()){
        if(first_contact)first_contact=false;else stream << ',';
        append_json_string(stream,runtime.world().name(contact.first)+":"+runtime.world().name(contact.second));
    }
    stream << ']';
    if (gpu && gpu->ready()) {
        const auto render = gpu->profile();
        const auto adapter = gpu->adapter_info();
        stream << ",\"gpu_ms\":" << render.gpu_ms
               << ",\"present_wall_ms\":" << render.present_wall_ms
               << ",\"cpu_skin_wall_ms\":" << render.cpu_skin_wall_ms
               << ",\"shadow_wall_ms\":" << render.shadow_wall_ms
               << ",\"geometry_wall_ms\":" << render.geometry_wall_ms
               << ",\"post_wall_ms\":" << render.post_wall_ms
               << ",\"inverse_bind_reads\":" << render.inverse_bind_reads
               << ",\"inverse_bind_cache_hits\":" << render.inverse_bind_cache_hits
               << ",\"render_scale\":" << render.render_scale
               << ",\"render_width\":" << render.render_width
               << ",\"render_height\":" << render.render_height
               << ",\"temporal\":" << (render.temporal ? "true" : "false")
               << ",\"dynamic_resolution\":" << (render.dynamic_resolution ? "true" : "false");
        stream << ",\"vsync\":" << (render.vsync ? "true" : "false");
        stream << ",\"gpu_samples_ms\":[";
        for (std::size_t index = 0; index < render.gpu_sample_count; ++index) {
            if (index) stream << ',';
            stream << render.gpu_samples_ms[index];
        }
        stream << ']';
        stream << ",\"gpu_skinned_draws\":" << render.gpu_skinned_draws
               << ",\"cpu_skinned_draws\":" << render.cpu_skinned_draws
               << ",\"gpu_skin_stream_sets\":" << render.gpu_skin_stream_sets
               << ",\"gpu_skin_palette_sets\":" << render.gpu_skin_palette_sets
               << ",\"submitted_geometry_draws\":" << render.submitted_geometry_draws
               << ",\"submitted_shadow_draws\":" << render.submitted_shadow_draws
               << ",\"ui_compositions\":" << render.ui_compositions
               << ",\"ui_texture_creations\":" << render.ui_texture_creations
               << ",\"ui_image_decodes\":" << render.ui_image_decodes
               << ",\"ui_bitmap_ms\":" << render.ui_bitmap_ms
               << ",\"ui_draw_ms\":" << render.ui_draw_ms
               << ",\"ui_copy_ms\":" << render.ui_copy_ms
               << ",\"ui_text_ms\":" << render.ui_text_ms
               << ",\"ui_blend_ms\":" << render.ui_blend_ms
               << ",\"ui_upload_ms\":" << render.ui_upload_ms;
        stream << ",\"gpu_work_estimate_ms\":" << render.gpu_work_estimate_ms;
        stream << ",\"history_allocations\":" << render.history_allocations;
        stream << ",\"gpu_adapter_name\":";
        append_json_string(stream, adapter.name);
        stream << ",\"gpu_vendor_id\":" << adapter.vendor_id
               << ",\"gpu_device_id\":" << adapter.device_id
               << ",\"gpu_dedicated_video_memory_bytes\":" << adapter.dedicated_video_memory_bytes
               << ",\"gpu_software_adapter\":" << (adapter.software ? "true" : "false");
    }
#if defined(_WIN32)
    if (frame % 60 == 0) {
        PROCESS_MEMORY_COUNTERS_EX memory{};
        memory.cb = sizeof(memory);
        if (GetProcessMemoryInfo(GetCurrentProcess(),
            reinterpret_cast<PROCESS_MEMORY_COUNTERS*>(&memory), sizeof(memory))) {
            stream << ",\"working_set_bytes\":" << memory.WorkingSetSize
                   << ",\"private_bytes\":" << memory.PrivateUsage;
        }
    }
#endif
    stream << "}\n";
}

bool write_debug_snapshot(const Options& options, const Runtime& runtime, int frame) {
    const auto path = options.debug_snapshot.empty() ? options.scene.parent_path() / "debug-snapshot.json" : options.debug_snapshot;
    std::ofstream output(path, std::ios::binary | std::ios::trunc);
    if (!output) return false;
    output << "{\"schema\":\"tech_connector.runtime_debug_snapshot.v1\",\"frame\":" << frame
           << ",\"active_animation\":";
    append_json_string(output, runtime.active_animation_id());
    output << ",\"entities\":[";
    bool first = true;
    for (const auto entity : runtime.world().entities()) {
        if (!first) output << ',';
        first = false;
        output << "{\"name\":";
        append_json_string(output, runtime.world().name(entity));
        if (const auto found = runtime.world().transforms.find(entity); found != runtime.world().transforms.end()) {
            output << ",\"position\":[" << found->second.position.x << ',' << found->second.position.y
                   << ',' << found->second.position.z << ']';
        }
        output << '}';
    }
    output << "]}\n";
    return bool(output);
}

void append_traces(const Options& options, const Runtime& runtime, std::size_t& consumed) {
    if (options.log.empty()) return;
    const auto& traces = runtime.debug_trace();
    const auto start = runtime.debug_trace_start_index();
    if (consumed < start || consumed > start + traces.size()) consumed = start;
    if (consumed == start + traces.size()) return;
    std::ofstream stream;
    while (consumed < start + traces.size()) {
        const auto& trace = traces[consumed++ - start];
        if (options.trace_graph || !trace.starts_with("OK ")) {
            if (!stream.is_open()) stream.open(options.log, std::ios::app);
            stream << trace << '\n';
        }
    }
}

void append_audio_result(const Options& options, const std::string& source,
                         std::string_view status, const std::string& error,
                         std::size_t active_voices = 0) {
    if (options.log.empty()) return;
    std::ofstream stream(options.log, std::ios::app);
    stream << "{\"type\":\"audio_event\",\"status\":\"" << status << "\",\"source\":";
    append_json_string(stream, source);
    stream << ",\"error\":";
    append_json_string(stream, error);
    stream << ",\"active_voices\":" << active_voices << "}\n";
}

void append_audio_restart_result(const Options& options, std::string_view phase,
                                 bool succeeded, const std::string& error,
                                 std::size_t active_voices, bool muted,
                                 bool endpoint_monitoring) {
    if (options.log.empty()) return;
    std::ofstream stream(options.log, std::ios::app);
    stream << "{\"type\":\"audio_restart\",\"phase\":\"" << phase
           << "\",\"succeeded\":" << (succeeded ? "true" : "false") << ",\"error\":";
    append_json_string(stream, error);
    stream << ",\"active_voices\":" << active_voices
           << ",\"muted\":" << (muted ? "true" : "false")
           << ",\"endpoint_monitoring\":" << (endpoint_monitoring ? "true" : "false")
           << "}\n";
}

int run_headless(const Options& options) {
    if (!options.log.empty()) {
        std::ofstream log_probe(options.log, std::ios::app);
        if (!log_probe) {
            std::cerr << "error: cannot write headless profile log: " << path_utf8(options.log) << '\n';
            return 4;
        }
    }
    Runtime runtime;
    runtime.set_success_trace_enabled(options.trace_graph);
    std::string error;
    if (!runtime.load_manifest(options.scene, error)) {
        std::cerr << path_utf8(options.scene) << ":1: error TC0001: " << error << '\n';
        return 2;
    }
    runtime.begin_play();
    std::size_t consumed_traces = 0;
    const int frame_count = options.frames > 0 ? options.frames : 120;
    for (int frame = 0; frame < frame_count; ++frame) {
        runtime.set_input_axis(frame < frame_count / 2 ? 1.0F : 0.0F, 0.0F);
        runtime.set_jump_pressed(false);
        runtime.tick(1.0F / 60.0F);
        append_profile(options, runtime, frame, nullptr, 0.0, 1.0 / 60.0);
        append_traces(options, runtime, consumed_traces);
    }
    if (!options.verify_save_roundtrip.empty()) {
        const auto player = runtime.world().find_entity("Player");
        const auto original = runtime.world().transforms.find(player);
        if (player == 0U || original == runtime.world().transforms.end()) {
            std::cerr << "error: save roundtrip requires a Player transform\n";
            return 5;
        }
        if (!runtime.save(options.verify_save_roundtrip, error)) {
            std::cerr << "error: " << error << '\n';
            return 5;
        }
        Runtime restored;
        if (!restored.load_manifest(options.scene, error)) {
            std::cerr << "error: save roundtrip could not load scene: " << error << '\n';
            return 5;
        }
        restored.begin_play();
        if (!restored.load_save(options.verify_save_roundtrip, error)) {
            std::cerr << "error: save roundtrip could not load save: " << error << '\n';
            return 5;
        }
        const auto restored_player = restored.world().find_entity("Player");
        const auto loaded = restored.world().transforms.find(restored_player);
        const auto expected = original->second.position;
        if (restored_player == 0U || loaded == restored.world().transforms.end()
            || std::abs(loaded->second.position.x - expected.x) > 1.0e-9
            || std::abs(loaded->second.position.y - expected.y) > 1.0e-9
            || std::abs(loaded->second.position.z - expected.z) > 1.0e-9) {
            std::cerr << "error: Player position changed during save roundtrip\n";
            return 5;
        }
        std::cout << "TC_SAVE_ROUNDTRIP_OK player=" << restored.world().name(restored_player) << '\n';
        const auto legacy_path = sidecar_path(options.verify_save_roundtrip, ".legacy-v1");
        {
            std::ofstream legacy(legacy_path, std::ios::binary | std::ios::trunc);
            legacy << std::setprecision(17) << "TCSAVE\t1\nPOS\tPlayer\t"
                   << expected.x << '\t' << expected.y << '\t' << expected.z << '\n';
            if (!legacy) {
                std::cerr << "error: could not write legacy save fixture\n";
                return 5;
            }
        }
        Runtime migrated;
        if (!migrated.load_manifest(options.scene, error)) {
            std::cerr << "error: legacy migration could not load scene: " << error << '\n';
            return 5;
        }
        migrated.begin_play();
        if (!migrated.load_save(legacy_path, error)) {
            std::cerr << "error: legacy migration could not load v1 save: " << error << '\n';
            return 5;
        }
        const auto migrated_player = migrated.world().find_entity("Player");
        const auto migrated_position = migrated.world().transforms.find(migrated_player);
        if (migrated_player == 0U || migrated_position == migrated.world().transforms.end()
            || std::abs(migrated_position->second.position.x - expected.x) > 1.0e-9
            || std::abs(migrated_position->second.position.y - expected.y) > 1.0e-9
            || std::abs(migrated_position->second.position.z - expected.z) > 1.0e-9) {
            std::cerr << "error: legacy save changed Player position\n";
            return 5;
        }
        const auto migrated_path = sidecar_path(options.verify_save_roundtrip, ".migrated-v3");
        if (!migrated.save(migrated_path, error)) {
            std::cerr << "error: legacy migration could not write v3 save: " << error << '\n';
            return 5;
        }
        std::ifstream upgraded(migrated_path, std::ios::binary);
        std::string header;
        if (!std::getline(upgraded, header) || header != "TCSAVE\t3") {
            std::cerr << "error: legacy save did not upgrade to v3\n";
            return 5;
        }
        std::cout << "TC_SAVE_LEGACY_MIGRATION_OK from=1 to=3\n";
        const auto legacy_v2_path = sidecar_path(options.verify_save_roundtrip, ".legacy-v2");
        {
            std::ofstream legacy_v2(legacy_v2_path, std::ios::binary | std::ios::trunc);
            legacy_v2 << std::setprecision(17) << "TCSAVE\t2\nBODY\tPlayer\t"
                      << expected.x << '\t' << expected.y << '\t' << expected.z
                      << "\t0\t0\t0\t1\t1\t1\t0\t0\t0\t0\t0\t0\n";
        }
        Runtime migrated_v2;
        if (!migrated_v2.load_manifest(options.scene, error)) {
            std::cerr << "error: v2 migration could not load scene: " << error << '\n';
            return 5;
        }
        migrated_v2.begin_play();
        if (!migrated_v2.load_save(legacy_v2_path, error)
            || std::abs(migrated_v2.world().transforms.at(migrated_v2.world().find_entity("Player")).position.x - expected.x) > 1.0e-9) {
            std::cerr << "error: v2 migration could not restore Player state\n";
            return 5;
        }
        const auto upgraded_v2_path = sidecar_path(options.verify_save_roundtrip, ".v2-migrated-v3");
        if (!migrated_v2.save(upgraded_v2_path, error)) {
            std::cerr << "error: v2 migration could not write v3 save: " << error << '\n';
            return 5;
        }
        std::cout << "TC_SAVE_LEGACY_MIGRATION_OK from=2 to=3\n";
        const auto malformed_legacy_path = sidecar_path(options.verify_save_roundtrip, ".legacy-malformed");
        std::filesystem::remove(sidecar_path(malformed_legacy_path, ".tmp"));
        std::filesystem::remove(sidecar_path(malformed_legacy_path, ".bak"));
        for (const auto& payload : std::array<std::string_view, 3>{
                 "TCSAVE\t1\nPOS\tPlayer\tnan\t0\t0\n",
                 "TCSAVE\t2\nUNKNOWN\tPlayer\t0\n",
                 "TCSAVE\t2\nBODY\tPlayer\t0"}) {
            {
                std::ofstream invalid(malformed_legacy_path, std::ios::binary | std::ios::trunc);
                invalid << payload;
                if (!invalid) return 5;
            }
            Runtime legacy_probe;
            if (!legacy_probe.load_manifest(options.scene, error)) return 5;
            legacy_probe.begin_play();
            const auto probe_id = legacy_probe.world().find_entity("Player");
            const double original_x = legacy_probe.world().transforms.at(probe_id).position.x;
            if (legacy_probe.load_save(malformed_legacy_path, error) ||
                std::abs(legacy_probe.world().transforms.at(probe_id).position.x - original_x) > 1.0e-9) {
                std::cerr << "error: malformed legacy save was accepted or changed Player state\n";
                return 5;
            }
        }
        std::cout << "TC_SAVE_LEGACY_MALFORMED_REJECTED cases=3\n";
        std::filesystem::copy_file(options.verify_save_roundtrip,
            sidecar_path(malformed_legacy_path, ".bak"),
            std::filesystem::copy_options::overwrite_existing);
        Runtime legacy_backup_probe;
        if (!legacy_backup_probe.load_manifest(options.scene, error)) return 5;
        legacy_backup_probe.begin_play();
        if (!legacy_backup_probe.load_save(malformed_legacy_path, error) ||
            error != "Recovered previous TC save game from backup" ||
            std::abs(legacy_backup_probe.world().transforms.at(
                legacy_backup_probe.world().find_entity("Player")).position.x - expected.x) > 1.0e-9) {
            std::cerr << "error: malformed legacy primary did not recover valid backup\n";
            return 5;
        }
        std::cout << "TC_SAVE_LEGACY_BACKUP_RECOVERED\n";
        const auto corrupt_path = sidecar_path(options.verify_save_roundtrip, ".corrupt");
        {
            std::ofstream corrupt(corrupt_path, std::ios::binary | std::ios::trunc);
            corrupt << "TCSAVE\t999\nPOS\tPlayer\t0\t0\t0\n";
        }
        std::string corrupt_error;
        if (migrated.load_save(corrupt_path, corrupt_error)
            || std::abs(migrated.world().transforms.at(migrated_player).position.x - expected.x) > 1.0e-9) {
            std::cerr << "error: malformed save was accepted or changed Player state\n";
            return 5;
        }
        std::cout << "TC_SAVE_CORRUPTION_REJECTED\n";
        const auto recovery_path = sidecar_path(options.verify_save_roundtrip, ".recovery");
        if (!runtime.save(recovery_path, error)) {
            std::cerr << "error: recovery fixture could not write initial save: " << error << '\n';
            return 5;
        }
        runtime.world().transforms.at(player).position.x += 3.0;
        if (!runtime.save(recovery_path, error)) {
            std::cerr << "error: recovery fixture could not write replacement save: " << error << '\n';
            return 5;
        }
        std::string semantic_body;
        {
            std::ifstream source(recovery_path, std::ios::binary);
            semantic_body.assign(std::istreambuf_iterator<char>(source), std::istreambuf_iterator<char>());
        }
        const auto checksum_start = semantic_body.rfind("CHECKSUM\t");
        const auto player_body_start = semantic_body.find("BODY\tPlayer\t");
        if (checksum_start == std::string::npos || player_body_start == std::string::npos) {
            std::cerr << "error: recovery fixture has no checksummed Player body\n";
            return 5;
        }
        semantic_body.resize(checksum_start);
        const auto number_start = player_body_start + std::string("BODY\tPlayer\t").size();
        const auto number_end = semantic_body.find('\t', number_start);
        semantic_body.replace(number_start, number_end - number_start, "nan");
        std::uint64_t semantic_checksum = 1469598103934665603ULL;
        for (const unsigned char byte : semantic_body)
            semantic_checksum = (semantic_checksum ^ byte) * 1099511628211ULL;
        std::ostringstream semantic_checksum_text;
        semantic_checksum_text << std::hex << std::setw(16) << std::setfill('0') << semantic_checksum;
        const std::string semantic_payload = semantic_body + "CHECKSUM\t" + semantic_checksum_text.str() + '\n';
        {
            std::ofstream malformed(corrupt_path, std::ios::binary | std::ios::trunc);
            malformed << semantic_payload;
        }
        if (migrated.load_save(corrupt_path, error)
            || std::abs(migrated.world().transforms.at(migrated_player).position.x - expected.x) > 1.0e-9) {
            std::cerr << "error: checksummed non-finite save was accepted or changed Player state\n";
            return 5;
        }
        std::cout << "TC_SAVE_SEMANTIC_REJECTED\n";
        {
            std::ofstream malformed(recovery_path, std::ios::binary | std::ios::trunc);
            malformed << semantic_payload;
        }
        Runtime semantic_recovered;
        if (!semantic_recovered.load_manifest(options.scene, error)) return 5;
        semantic_recovered.begin_play();
        if (!semantic_recovered.load_save(recovery_path, error)
            || error != "Recovered previous TC save game from backup"
            || std::abs(semantic_recovered.world().transforms.at(
                semantic_recovered.world().find_entity("Player")).position.x - expected.x) > 1.0e-9) {
            std::cerr << "error: checksummed malformed save did not recover prior Player state\n";
            return 5;
        }
        std::cout << "TC_SAVE_SEMANTIC_RECOVERED\n";
        {
            std::ofstream torn(recovery_path, std::ios::binary | std::ios::trunc);
            torn << "TCSAVE\t3\nBODY\tPlayer\t0\n";
        }
        Runtime recovered;
        if (!recovered.load_manifest(options.scene, error)) {
            std::cerr << "error: recovery fixture could not load scene: " << error << '\n';
            return 5;
        }
        recovered.begin_play();
        if (!recovered.load_save(recovery_path, error)
            || error != "Recovered previous TC save game from backup"
            || std::abs(recovered.world().transforms.at(recovered.world().find_entity("Player")).position.x - expected.x) > 1.0e-9) {
            std::cerr << "error: incomplete save did not recover prior Player state\n";
            return 5;
        }
        std::cout << "TC_SAVE_PARTIAL_WRITE_RECOVERED\n";
        const auto pending_path = sidecar_path(options.verify_save_roundtrip, ".pending");
        std::filesystem::remove(pending_path);
        std::filesystem::remove(sidecar_path(pending_path, ".bak"));
        std::filesystem::copy_file(options.verify_save_roundtrip,
            sidecar_path(pending_path, ".tmp"),
            std::filesystem::copy_options::overwrite_existing);
        Runtime pending_recovered;
        if (!pending_recovered.load_manifest(options.scene, error)) return 5;
        pending_recovered.begin_play();
        if (!pending_recovered.load_save(pending_path, error) ||
            error != "Recovered pending TC save game from temporary file" ||
            std::abs(pending_recovered.world().transforms.at(
                pending_recovered.world().find_entity("Player")).position.x - expected.x) > 1.0e-9) {
            std::cerr << "error: valid pending save was not recovered\n";
            return 5;
        }
        std::cout << "TC_SAVE_PENDING_WRITE_RECOVERED\n";
        const auto rotation_path = sidecar_path(options.verify_save_roundtrip, ".rotation");
        std::filesystem::remove(rotation_path);
        std::filesystem::remove(sidecar_path(rotation_path, ".bak"));
        runtime.world().variables["save_rotation_marker"] = 1.0F;
        if (!runtime.save(rotation_path, error)) return 5;
        runtime.world().variables["save_rotation_marker"] = 2.0F;
        if (!runtime.save(rotation_path, error)) return 5;
        {
            std::ofstream damaged(rotation_path, std::ios::binary | std::ios::trunc);
            damaged << semantic_payload;
        }
        runtime.world().variables["save_rotation_marker"] = 3.0F;
        if (!runtime.save(rotation_path, error)) return 5;
        Runtime rotation_probe;
        if (!rotation_probe.load_manifest(options.scene, error)) return 5;
        rotation_probe.begin_play();
        if (!rotation_probe.load_save(sidecar_path(rotation_path, ".bak"), error) ||
            rotation_probe.world().variables["save_rotation_marker"] != 1.0F ||
            !rotation_probe.load_save(rotation_path, error) ||
            rotation_probe.world().variables["save_rotation_marker"] != 3.0F) {
            std::cerr << "error: checksum-valid malformed primary replaced the valid save backup\n";
            return 5;
        }
        std::cout << "TC_SAVE_BACKUP_PRESERVED\n";
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
    float ui_scale{1.0F};
    Clock::time_point previous{Clock::now()};
    int frame{0};
    int debug_timer_count{0};
    bool debug_paused{false};
    bool window_minimized{false};
    bool debug_step_pending{false};
    bool debug_breakpoint_fired{false};
    int debug_presented_frame{-1};
    bool debug_paused_screenshot_written{false};
    std::size_t played_events{0};
    std::size_t logged_traces{0};
    bool screenshot_written{false};
    bool render_failed{false};
    int gamepad_index{-1};
    int focused_ui_button{-1};
    std::string pending_rebind_action;
    std::filesystem::path input_profile;
    std::filesystem::path audio_profile;
    std::filesystem::path save_dir;
    std::string ui_status_original;
    int ui_status_expires_at{-1};
    std::uint16_t previous_gamepad_buttons{0};
    std::uint16_t suppressed_owner_buttons{0};
    bool awaiting_owner_stick_neutral{false};
    bool gamepad_was_connected{false};
    bool gamepad_input_was_lost{false};
    bool mouse_look_active{false};
    int mouse_last_x{0};
    int mouse_last_y{0};
    float camera_yaw_degrees{0.0F};
    float camera_pitch_degrees{0.0F};
    std::array<bool, 256> pressed_keys{};
    tc::runtime::AudioMixer audio;
    std::string restart_audio_source;
    bool audio_restart_requested{false};
    bool audio_restart_replayed{false};
    tc::runtime::GpuRenderer gpu;
};

bool present_debug_inspector(WindowState& state, HWND window, std::string& error) {
    if (!state.gpu.ready()) return true;
    auto& world = state.runtime.world();
    std::ostringstream details;
    details << "PAUSED  |  Frame " << state.frame << "  |  F10 resume  F11 step  F9 snapshot\n"
            << "Entities: " << world.entities().size() << "   Events: " << world.events.size();
    const auto player = world.find_entity("Player");
    if (const auto found = world.transforms.find(player); player != 0U && found != world.transforms.end()) {
        details << std::fixed << std::setprecision(2) << "\nPlayer: "
                << found->second.position.x << ", " << found->second.position.y << ", "
                << found->second.position.z;
    }
    const auto original_size = world.ui_widgets.size();
    RECT client{};
    GetClientRect(window, &client);
    const float panel_width = std::max(200.0F, std::min(500.0F, static_cast<float>(client.right - 40)));
    tc::runtime::World::UiWidget panel;
    panel.id = "__tc_debug_inspector_panel";
    panel.type = "panel";
    panel.responsive_layout = true;
    panel.anchor_x = panel.anchor_y = 1.0F;
    panel.pivot_x = panel.pivot_y = 1.0F;
    panel.offset_x = panel.offset_y = -20.0F;
    panel.layout_width = panel_width;
    panel.layout_height = 150.0F;
    world.ui_widgets.push_back(panel);
    tc::runtime::World::UiWidget label;
    label.id = "__tc_debug_inspector_text";
    label.type = "text";
    label.text = details.str();
    label.accessible_name = "Paused runtime inspector";
    label.responsive_layout = true;
    label.parent_id = panel.id;
    label.offset_x = 18.0F;
    label.offset_y = 15.0F;
    label.layout_width = panel_width - 36.0F;
    label.layout_height = 125.0F;
    world.ui_widgets.push_back(label);
    const auto* capture = state.debug_paused_screenshot_written ||
        state.options.debug_paused_screenshot.empty() ? nullptr : &state.options.debug_paused_screenshot;
    const bool rendered = state.gpu.render(world, error, capture);
    world.ui_widgets.resize(original_size);
    if (rendered && capture != nullptr) state.debug_paused_screenshot_written = true;
    return rendered;
}

std::filesystem::path default_input_profile(const std::filesystem::path& scene) {
    wchar_t local_data[32768]{};
    const DWORD length = GetEnvironmentVariableW(L"LOCALAPPDATA", local_data, 32768);
    if (length == 0 || length >= 32768) return {};
    const auto utf8_key = std::filesystem::absolute(scene).lexically_normal().generic_u8string();
    std::string key(utf8_key.begin(), utf8_key.end());
    std::transform(key.begin(), key.end(), key.begin(), [](unsigned char value) {
        return static_cast<char>(value >= 'A' && value <= 'Z' ? value + ('a' - 'A') : value);
    });
    std::uint64_t hash = 1469598103934665603ULL;
    for (const unsigned char value : key) hash = (hash ^ value) * 1099511628211ULL;
    std::ostringstream name;
    name << std::hex << std::setw(16) << std::setfill('0') << hash << ".tcinput";
    return std::filesystem::path(local_data) / L"TechConnector" / L"TCPlayer" /
           L"profiles" / name.str();
}

std::filesystem::path default_scene_profile(const std::filesystem::path& scene,
                                            const std::string& scene_id,
                                            const std::string& extension) {
    auto legacy = default_input_profile(scene);
    if (legacy.empty()) return {};
    if (scene_id.empty()) {
        legacy.replace_extension(extension);
        return legacy;
    }
    return legacy.parent_path() / (scene_id + extension);
}

std::filesystem::path default_save_dir(const std::filesystem::path& scene,
                                       const std::string& scene_id) {
    const auto profile = default_input_profile(scene);
    if (profile.empty()) return {};
    return profile.parent_path().parent_path() / L"saves" /
           (scene_id.empty() ? profile.stem() : std::filesystem::path(scene_id));
}

std::filesystem::path windowed_save_path(const WindowState& state) {
    const auto& slot = state.runtime.world().save_slot;
    if (state.save_dir.empty() || slot.empty() || slot.size() > 64 ||
        !std::all_of(slot.begin(), slot.end(), [](unsigned char character) {
            return std::isalnum(character) || character == '_' || character == '-';
        })) return {};
    std::string upper = slot;
    std::transform(upper.begin(), upper.end(), upper.begin(), [](unsigned char character) {
        return static_cast<char>(std::toupper(character));
    });
    if (upper == "CON" || upper == "PRN" || upper == "AUX" || upper == "NUL" ||
        (upper.size() == 4 && (upper.starts_with("COM") || upper.starts_with("LPT")) &&
         upper[3] >= '1' && upper[3] <= '9')) return {};
    return state.save_dir / (slot + ".tcsave");
}

void set_ui_status(WindowState& state, std::string_view message) {
    for (auto& widget : state.runtime.world().ui_widgets) {
        if (widget.id != "objective" || widget.type != "text") continue;
        if (state.ui_status_original.empty()) state.ui_status_original = widget.text;
        widget.text = std::string(message);
        state.ui_status_expires_at = state.frame + 180;
        std::cout << "TC_UI_STATUS text=" << message << '\n';
        break;
    }
}

bool save_windowed_game(WindowState& state, std::string_view source) {
    const auto path = windowed_save_path(state);
    if (path.empty()) {
        std::cerr << "TC_SAVE_FAILED source=" << source << " reason=invalid_save_location\n";
        set_ui_status(state, "Save failed");
        return false;
    }
    std::error_code filesystem_error;
    std::filesystem::create_directories(tc::runtime::save_io_path(path.parent_path()), filesystem_error);
    if (filesystem_error) {
        std::cerr << "TC_SAVE_FAILED source=" << source << " reason=create_directory_failed\n";
        set_ui_status(state, "Save failed");
        return false;
    }
    std::string error;
    if (!state.runtime.save(path, error)) {
        std::cerr << "TC_SAVE_FAILED source=" << source << " reason=" << error << '\n';
        set_ui_status(state, "Save failed");
        return false;
    }
    std::cout << "TC_SAVE_WRITTEN source=" << source << " path=" << path_utf8(path) << '\n';
    set_ui_status(state, "Saved");
    return true;
}

void update_rebind_labels(WindowState& state);

bool load_windowed_game(WindowState& state, std::string_view source) {
    const auto path = windowed_save_path(state);
    if (path.empty()) {
        std::cerr << "TC_LOAD_FAILED source=" << source << " reason=invalid_save_location\n";
        set_ui_status(state, "Load failed");
        return false;
    }
    std::string error;
    bool migration_failed = false;
    if (!state.runtime.load_save(path, error)) {
        const auto io_path = tc::runtime::save_io_path(path);
        const bool new_save_exists = std::filesystem::exists(io_path) ||
            std::filesystem::exists(sidecar_path(io_path, ".tmp")) ||
            std::filesystem::exists(sidecar_path(io_path, ".bak"));
        if (new_save_exists || !state.options.save_dir.empty() ||
            state.runtime.world().scene_id.empty()) {
            std::cerr << "TC_LOAD_FAILED source=" << source << " reason=" << error << '\n';
            set_ui_status(state, "Load failed");
            return false;
        }
        const auto legacy_directory = default_save_dir(state.options.scene, "");
        const auto legacy_path = legacy_directory / path.filename();
        const auto content_path = state.options.scene.parent_path() / path.filename();
        std::filesystem::path migrated_from;
        for (const auto& candidate : {legacy_path, content_path}) {
            if (candidate == path || !std::filesystem::exists(tc::runtime::save_io_path(candidate))) continue;
            if (state.runtime.load_save(candidate, error)) { migrated_from = candidate; break; }
        }
        if (migrated_from.empty()) {
            std::cerr << "TC_LOAD_FAILED source=" << source << " reason=" << error << '\n';
            set_ui_status(state, "Load failed");
            return false;
        }
        if (!save_windowed_game(state, "migration")) {
            migration_failed = true;
            std::cerr << "TC_SAVE_MIGRATION_FAILED from=" << path_utf8(migrated_from) << '\n';
        } else {
            std::cout << "TC_SAVE_MIGRATED from=" << path_utf8(migrated_from) << '\n';
        }
    } else if (!error.empty()) {
        std::cout << "TC_SAVE_RECOVERED source=" << source << " reason=" << error << '\n';
    }
    std::cout << "TC_SAVE_LOADED source=" << source << " path=" << path_utf8(path) << '\n';
    update_rebind_labels(state);
    set_ui_status(state, migration_failed ? "Upgrade failed" : "Loaded");
    return true;
}

bool write_input_profile(const std::filesystem::path& path,
                         const tc::runtime::GamepadBindings& bindings, std::string& error) {
    if (path.empty()) { error = "No writable input-profile path is configured."; return false; }
    const auto payload = tc::runtime::encode_gamepad_profile(bindings);
    if (payload.empty()) { error = "Gamepad bindings are invalid."; return false; }
    const auto io_path = tc::runtime::save_io_path(path);
    std::error_code filesystem_error;
    std::filesystem::create_directories(io_path.parent_path(), filesystem_error);
    if (filesystem_error) { error = "Could not create input-profile directory."; return false; }
    const auto temporary = sidecar_path(io_path, ".tmp");
    {
        std::ofstream stream(temporary, std::ios::binary | std::ios::trunc);
        stream << payload;
        stream.flush();
        if (!stream) { error = "Could not write temporary input profile."; return false; }
    }
    const auto backup = sidecar_path(io_path, ".bak");
    if (std::filesystem::is_regular_file(io_path, filesystem_error)) {
        std::ifstream existing(io_path, std::ios::binary);
        const std::string previous(std::istreambuf_iterator<char>{existing}, std::istreambuf_iterator<char>{});
        tc::runtime::GamepadBindings previous_bindings{};
        if (previous.size() <= 16384 && tc::runtime::decode_gamepad_profile(previous, previous_bindings)) {
            std::filesystem::copy_file(io_path, backup,
                std::filesystem::copy_options::overwrite_existing, filesystem_error);
            if (filesystem_error) {
                std::filesystem::remove(temporary);
                error = "Could not preserve previous input profile: " + filesystem_error.message();
                return false;
            }
        }
    }
    if (!MoveFileExW(temporary.c_str(), io_path.c_str(), MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH)) {
        std::filesystem::remove(temporary, filesystem_error);
        error = "Could not atomically replace input profile.";
        return false;
    }
    error.clear();
    return true;
}

bool read_input_profile(const std::filesystem::path& path,
                        tc::runtime::GamepadBindings& bindings, std::string& error) {
    const auto io_path = tc::runtime::save_io_path(path);
    auto read_candidate = [&bindings](const std::filesystem::path& candidate) {
        std::error_code filesystem_error;
        const auto size = std::filesystem::file_size(candidate, filesystem_error);
        if (filesystem_error || size == 0 || size > 16384) return false;
        std::ifstream stream(candidate, std::ios::binary);
        std::string payload(static_cast<std::size_t>(size), '\0');
        stream.read(payload.data(), static_cast<std::streamsize>(size));
        return static_cast<bool>(stream) && tc::runtime::decode_gamepad_profile(payload, bindings);
    };
    if (read_candidate(io_path)) {
        error.clear();
        return true;
    }
    if (read_candidate(sidecar_path(io_path, ".tmp"))) {
        error = "Recovered pending input profile from temporary file";
        return true;
    }
    if (read_candidate(sidecar_path(io_path, ".bak"))) {
        error = "Recovered previous input profile from backup";
        return true;
    }
    error = "Input profile is missing, malformed, or failed checksum validation.";
    return false;
}

std::string encode_audio_profile(bool muted) {
    std::string payload = std::string("TCAUDIO\t1\nMUTED\t") + (muted ? "1\n" : "0\n");
    std::uint64_t checksum = 1469598103934665603ULL;
    for (const unsigned char byte : payload) checksum = (checksum ^ byte) * 1099511628211ULL;
    std::ostringstream footer;
    footer << "CHECKSUM\t" << std::hex << std::setw(16) << std::setfill('0') << checksum << '\n';
    return payload + footer.str();
}

bool write_audio_profile(const std::filesystem::path& path, bool muted, std::string& error) {
    if (path.empty()) { error = "No writable audio-profile path is configured."; return false; }
    const auto io_path = tc::runtime::save_io_path(path);
    std::error_code filesystem_error;
    std::filesystem::create_directories(io_path.parent_path(), filesystem_error);
    if (filesystem_error) { error = "Could not create audio-profile directory."; return false; }
    const auto temporary = sidecar_path(io_path, ".tmp");
    {
        std::ofstream stream(temporary, std::ios::binary | std::ios::trunc);
        stream << encode_audio_profile(muted);
        stream.flush();
        if (!stream) { error = "Could not write temporary audio profile."; return false; }
    }
    const auto backup = sidecar_path(io_path, ".bak");
    if (std::filesystem::is_regular_file(io_path, filesystem_error)) {
        std::ifstream existing(io_path, std::ios::binary);
        const std::string previous(std::istreambuf_iterator<char>{existing}, std::istreambuf_iterator<char>{});
        if (previous == encode_audio_profile(false) || previous == encode_audio_profile(true)) {
            std::filesystem::copy_file(io_path, backup,
                std::filesystem::copy_options::overwrite_existing, filesystem_error);
            if (filesystem_error) {
                std::filesystem::remove(temporary);
                error = "Could not preserve previous audio profile: " + filesystem_error.message();
                return false;
            }
        }
    }
    if (!MoveFileExW(temporary.c_str(), io_path.c_str(), MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH)) {
        std::filesystem::remove(temporary, filesystem_error);
        error = "Could not atomically replace audio profile.";
        return false;
    }
    error.clear();
    return true;
}

bool read_audio_profile(const std::filesystem::path& path, bool& muted, std::string& error) {
    const auto io_path = tc::runtime::save_io_path(path);
    auto read_candidate = [&muted](const std::filesystem::path& candidate) {
        std::error_code filesystem_error;
        const auto size = std::filesystem::file_size(candidate, filesystem_error);
        if (filesystem_error || size == 0 || size > 1024) return false;
        std::ifstream stream(candidate, std::ios::binary);
        std::string payload(static_cast<std::size_t>(size), '\0');
        stream.read(payload.data(), static_cast<std::streamsize>(size));
        if (!stream || (payload != encode_audio_profile(false) && payload != encode_audio_profile(true)))
            return false;
        muted = payload == encode_audio_profile(true);
        return true;
    };
    if (read_candidate(io_path)) {
        error.clear();
        return true;
    }
    if (read_candidate(sidecar_path(io_path, ".tmp"))) {
        error = "Recovered pending audio profile from temporary file";
        return true;
    }
    if (read_candidate(sidecar_path(io_path, ".bak"))) {
        error = "Recovered previous audio profile from backup";
        return true;
    }
    error = "Audio profile is missing, malformed, or failed checksum validation.";
    return false;
}

tc::runtime::GamepadSnapshot scripted_gamepad_snapshot(int frame,
                                                        const tc::runtime::GamepadBindings& bindings) {
    tc::runtime::GamepadSnapshot snapshot{};
    snapshot.connected = true;
    if (frame < 230) snapshot.left_y = 32767;
    if (frame >= 40 && frame < 80) snapshot.buttons = bindings.crouch;
    if (frame >= 80 && frame < 225) snapshot.buttons = bindings.crawl;
    if (frame == 250) snapshot.buttons = bindings.jump;
    return snapshot;
}

tc::runtime::GamepadSnapshot scripted_gamepad_ui_snapshot(int frame,
                                                           const tc::runtime::GamepadBindings& bindings,
                                                           bool load_button = false) {
    tc::runtime::GamepadSnapshot snapshot{};
    snapshot.connected = true;
    if (frame == 0 || (!load_button && frame == 4)) snapshot.buttons = bindings.ui_menu;
    if (load_button && frame == 2) snapshot.buttons = tc::runtime::gamepad_dpad_down;
    if (frame == (load_button ? 4 : 2)) snapshot.buttons = bindings.ui_confirm;
    return snapshot;
}

tc::runtime::GamepadSnapshot scripted_gamepad_disconnect_snapshot(int frame,
                                                                   const tc::runtime::GamepadBindings& bindings,
                                                                   bool rebind) {
    tc::runtime::GamepadSnapshot snapshot{};
    snapshot.connected = rebind ? (frame < 8 || frame >= 22) : (frame < 2 || frame >= 16);
    if (frame == 0 || (rebind ? (frame >= 22 && frame <= 23) || frame == 26 :
                      (frame >= 16 && frame <= 18) || frame == 24))
        snapshot.buttons = bindings.ui_menu;
    if (!rebind && frame >= 16 && frame <= 19) snapshot.left_y = 32767;
    if (!rebind && frame >= 21 && frame <= 22) snapshot.left_y = 32767;
    if (rebind && (frame == 2 || frame == 4)) snapshot.buttons = tc::runtime::gamepad_dpad_down;
    if (rebind && frame == 6) snapshot.buttons = bindings.ui_confirm;
    return snapshot;
}

tc::runtime::GamepadSnapshot scripted_gamepad_switch_snapshot(int frame,
                                                               const tc::runtime::GamepadBindings& bindings) {
    tc::runtime::GamepadSnapshot snapshot{};
    snapshot.connected = true;
    if (frame == 0 || (frame >= 2 && frame <= 4) || frame == 16)
        snapshot.buttons = bindings.ui_menu;
    if (frame >= 2 && frame <= 5) {
        snapshot.buttons |= bindings.crouch;
        snapshot.left_y = 32767;
    }
    if (frame >= 10 && frame <= 12) snapshot.left_y = 32767;
    return snapshot;
}

tc::runtime::GamepadSnapshot scripted_rebind_snapshot(int frame) {
    tc::runtime::GamepadSnapshot snapshot{};
    snapshot.connected = true;
    if (frame == 5 || frame == 7) snapshot.buttons = tc::runtime::gamepad_face_south;
    return snapshot;
}

tc::runtime::GamepadSnapshot scripted_focus_loss_rebind_snapshot(int frame) {
    tc::runtime::GamepadSnapshot snapshot{};
    snapshot.connected = true;
    if (frame == 7) snapshot.buttons = tc::runtime::gamepad_face_south;
    return snapshot;
}

void focus_ui_button(WindowState& state, HWND window, int direction) {
    state.mouse_look_active = false;
    if (GetCapture() == window) ReleaseCapture();
    auto& widgets = state.runtime.world().ui_widgets;
    RECT client{};
    GetClientRect(window, &client);
    const auto layout = tc::runtime::layout_ui_widgets(
        state.runtime.world(), static_cast<float>(client.right), static_cast<float>(client.bottom),
        state.ui_scale);
    std::vector<int> buttons;
    for (std::size_t index = 0; index < widgets.size(); ++index)
        if (layout[index].visible && widgets[index].type == "button" && !widgets[index].on_activate.empty())
            buttons.push_back(static_cast<int>(index));
    if (buttons.empty()) return;
    const auto current = std::find(buttons.begin(), buttons.end(), state.focused_ui_button);
    const int position = current == buttons.end() ? (direction >= 0 ? 0 : static_cast<int>(buttons.size()) - 1)
        : (static_cast<int>(current - buttons.begin()) + direction + static_cast<int>(buttons.size())) %
          static_cast<int>(buttons.size());
    state.focused_ui_button = buttons[static_cast<std::size_t>(position)];
    for (std::size_t index = 0; index < widgets.size(); ++index)
        widgets[index].focused = static_cast<int>(index) == state.focused_ui_button;
    std::cout << "TC_UI_FOCUS id=" << widgets[static_cast<std::size_t>(state.focused_ui_button)].id << '\n';
}

void close_ui_focus(WindowState& state) {
    state.focused_ui_button = -1;
    for (auto& widget : state.runtime.world().ui_widgets) widget.focused = false;
}

bool focused_ui_visible(const WindowState& state, HWND window) {
    if (state.focused_ui_button < 0) return false;
    RECT client{};
    GetClientRect(window, &client);
    const auto layout = tc::runtime::layout_ui_widgets(
        state.runtime.world(), static_cast<float>(client.right), static_cast<float>(client.bottom),
        state.ui_scale);
    const auto index = static_cast<std::size_t>(state.focused_ui_button);
    return index < layout.size() && layout[index].visible;
}

void activate_ui_widget(WindowState& state, const tc::runtime::World::UiWidget& widget) {
    // Loading a save replaces World (and its widget vector); do not retain a
    // reference into that vector across an action that may restore the world.
    const std::string widget_id = widget.id;
    const std::string action = widget.on_activate;
    std::cout << "TC_UI_ACTIVATED id=" << widget_id << " event=" << action << '\n';
    if (action == "rebind_jump" || action == "rebind_crouch" ||
        action == "rebind_crawl") {
        if (!state.gamepad_was_connected) {
            for (auto& item : state.runtime.world().ui_widgets)
                if (item.id == widget_id) item.text = "Connect gamepad";
            std::cout << "TC_GAMEPAD_REBIND_UNAVAILABLE action=" << action.substr(7)
                      << " reason=no_controller\n";
        } else {
            state.pending_rebind_action = action.substr(7);
            for (auto& item : state.runtime.world().ui_widgets)
                if (item.id == widget_id) item.text = "Press gamepad button";
            std::cout << "TC_GAMEPAD_REBIND_PENDING action=" << state.pending_rebind_action << '\n';
        }
    }
    if (action == "save_game") {
        save_windowed_game(state, "ui");
    }
    if (action == "load_game") load_windowed_game(state, "ui");
    if (action == "audio_toggle") {
        std::string audio_error;
        const bool previous = state.audio.muted();
        if (!state.audio.set_muted(!previous, audio_error)) {
            std::cerr << "TC_AUDIO_MUTE_FAILED reason=" << audio_error << '\n';
        } else if (!state.audio_profile.empty() &&
                   !write_audio_profile(state.audio_profile, state.audio.muted(), audio_error)) {
            std::string rollback_error;
            if (!state.audio.set_muted(previous, rollback_error))
                std::cerr << "TC_AUDIO_MUTE_ROLLBACK_FAILED reason=" << rollback_error << '\n';
            std::cerr << "TC_AUDIO_MUTE_FAILED reason=" << audio_error << '\n';
        } else {
            for (auto& item : state.runtime.world().ui_widgets) if (item.id == widget_id) {
                item.text = state.audio.muted() ? "Audio: Muted" : "Audio: On";
                item.accessible_name = state.audio.muted() ? "Unmute audio" : "Mute audio";
            }
            if (!state.audio_profile.empty())
                std::cout << "TC_AUDIO_PROFILE_SAVED muted=" << (state.audio.muted() ? 1 : 0) << '\n';
            std::cout << "TC_AUDIO_MUTED muted=" << (state.audio.muted() ? 1 : 0) << '\n';
        }
    }
}

const char* gamepad_button_name(std::uint16_t mask) {
    using namespace tc::runtime;
    if (mask == gamepad_face_south) return "SOUTH";
    if (mask == gamepad_face_east) return "EAST";
    if (mask == gamepad_face_west) return "WEST";
    if (mask == gamepad_face_north) return "NORTH";
    if (mask == gamepad_left_shoulder) return "LEFT_SHOULDER";
    if (mask == gamepad_right_shoulder) return "RIGHT_SHOULDER";
    if (mask == gamepad_menu) return "MENU";
    return "UNKNOWN";
}

std::string keyboard_button_name(int key) {
    if (key == VK_SPACE) return "SPACE";
    if (key == VK_CONTROL) return "CTRL";
    if (key == VK_SHIFT) return "SHIFT";
    if (key == VK_MENU) return "ALT";
    if (key == VK_TAB) return "TAB";
    if (key == VK_RETURN) return "ENTER";
    if ((key >= 'A' && key <= 'Z') || (key >= '0' && key <= '9'))
        return std::string(1, static_cast<char>(key));
    return "KEY " + std::to_string(key);
}

void update_rebind_labels(WindowState& state) {
    const auto& world = state.runtime.world();
    const auto& bindings = world.gamepad_bindings;
    const auto display_name = [](std::uint16_t mask) -> const char* {
        if (mask == tc::runtime::gamepad_left_shoulder) return "LB/L1";
        if (mask == tc::runtime::gamepad_right_shoulder) return "RB/R1";
        return gamepad_button_name(mask);
    };
    for (auto& widget : state.runtime.world().ui_widgets) {
        std::uint16_t mask = 0;
        const char* label = nullptr;
        const char* action = nullptr;
        if (widget.on_activate == "rebind_jump") { mask = bindings.jump; label = "Jump"; action = "jump"; }
        else if (widget.on_activate == "rebind_crouch") { mask = bindings.crouch; label = "Crouch"; action = "crouch"; }
        else if (widget.on_activate == "rebind_crawl") { mask = bindings.crawl; label = "Crawl"; action = "crawl"; }
        if (label == nullptr) continue;
        const auto keyboard = world.input_bindings.find(action);
        const std::string key_name = keyboard == world.input_bindings.end() ? "UNBOUND" :
            keyboard_button_name(keyboard->second);
        // A controller-only rebind must not masquerade as an actionable
        // keyboard control when no controller is connected.
        widget.type = state.gamepad_was_connected ? "button" : "text";
        widget.text = std::string(label) + ": " +
            (state.gamepad_was_connected ? display_name(mask) : key_name);
        widget.accessible_name = state.gamepad_was_connected ?
            "Rebind controller " + std::string(label) + "; keyboard " + key_name :
            "Controller disconnected; keyboard " + std::string(label) + " uses " + key_name;
    }
}

tc::runtime::GamepadSnapshot poll_xbox_controller(int& selected_index) {
    const auto read = [](DWORD index, tc::runtime::GamepadSnapshot& snapshot) {
        XINPUT_STATE state{};
        if (XInputGetState(index, &state) != ERROR_SUCCESS) return false;
        snapshot = {true, state.Gamepad.sThumbLX, state.Gamepad.sThumbLY,
                    state.Gamepad.wButtons};
        return true;
    };
    tc::runtime::GamepadSnapshot snapshot{};
    if (selected_index >= 0 && read(static_cast<DWORD>(selected_index), snapshot))
        return snapshot;
    selected_index = -1;
    for (DWORD index = 0; index < XUSER_MAX_COUNT; ++index) {
        if (read(index, snapshot)) {
            selected_index = static_cast<int>(index);
            return snapshot;
        }
    }
    return {};
}

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
    const auto key_name = [&state](const char* action) {
        const auto found = state.runtime.world().input_bindings.find(action);
        return found == state.runtime.world().input_bindings.end() ? std::string("?") : keyboard_button_name(found->second);
    };
    const std::string help_ascii = "Move " + key_name("move_forward") + key_name("move_left") +
        key_name("move_backward") + key_name("move_right") + "  Jump " + key_name("jump") +
        "  RMB Look  Tab UI  F5 Save  Esc Exit";
    const std::wstring help(help_ascii.begin(), help_ascii.end());
    TextOutW(buffer, 18, height - 32, help.c_str(), static_cast<int>(help.size()));

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
        const UINT dpi = GetDpiForWindow(window);
        created_state->ui_scale = std::clamp(created_state->options.ui_scale *
            static_cast<float>(dpi == 0 ? 96U : dpi) / 96.0F, 0.75F, 10.0F);
        created_state->gpu.set_ui_scale(created_state->ui_scale);
        created_state->gpu.set_cpu_skinning_diagnostic(created_state->options.cpu_skinning_diagnostic);
        const bool per_monitor_v2 = AreDpiAwarenessContextsEqual(
            GetWindowDpiAwarenessContext(window), DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
        std::cout << "TC_DPI_INITIAL dpi=" << dpi << " ui_scale=" << created_state->ui_scale
                  << " awareness=" << (per_monitor_v2 ? "per_monitor_v2" : "other") << '\n';
        RECT client{};
        GetClientRect(window, &client);
        std::string renderer_error;
        if (!created_state->gpu.initialize(window, client.right, client.bottom, renderer_error)) {
            OutputDebugStringA(("TC GPU fallback: " + renderer_error + "\n").c_str());
            if (created_state->options.require_renderer) return -1;
        }
        // Present(1) paces D3D11 frames; a second 16 ms timer delay skips refreshes.
        SetTimer(window, 1, 1, nullptr);
        return 0;
    }
    if (message == WM_TIMER && state != nullptr) {
        const bool trace_capture_frame = !state->options.screenshot.empty() &&
            !state->screenshot_written && state->frame + 1 == state->options.screenshot_frame &&
            GetEnvironmentVariableA("TC_CAPTURE_TRACE", nullptr, 0) > 0;
        const auto capture_stage = [trace_capture_frame](const char* stage) {
            if (trace_capture_frame) std::cerr << "TC_CAPTURE_STAGE " << stage << '\n' << std::flush;
        };
        capture_stage("timer_begin");
        const auto now = Clock::now();
        const double frame_interval_ms = std::chrono::duration<double, std::milli>(
            now - state->previous).count();
        const bool deterministic_motion_demo = state->options.scripted_motion_demo ||
            state->options.scripted_motion_soak || state->options.scripted_gamepad_demo;
        // Scripted acceptance routes must cover the same world path even when
        // Present pacing differs between the vsynced and GPU-work probes.
        const float delta = state->options.scripted_input ? (1.0F / 60.0F) :
            deterministic_motion_demo ? (state->frame == 0 ? 0.066F : 0.025F) :
            std::clamp(static_cast<float>(frame_interval_ms / 1000.0), 0.0F, 0.066F);
        state->previous = now;
        ++state->debug_timer_count;
        if (state->options.scripted_minimize_restore) {
            if (state->debug_timer_count == 3) ShowWindow(window, SW_MINIMIZE);
            if (state->debug_timer_count == 6) ShowWindow(window, SW_RESTORE);
        }
        if (state->window_minimized) {
            state->audio.update();
            return 0;
        }
        if (state->options.break_frame == state->frame && !state->debug_breakpoint_fired) {
            state->debug_breakpoint_fired = true;
            state->debug_paused = true;
            std::cout << "TC_DEBUG_BREAK frame=" << state->frame << '\n';
        }
        if (state->options.scripted_debug_step) {
            if (state->debug_timer_count == 2 && state->options.break_frame < 0 &&
                !state->options.break_player_x && !state->debug_breakpoint_fired)
                SendMessageW(window, WM_KEYDOWN, VK_F10, 0);
            if (state->debug_timer_count == 5) SendMessageW(window, WM_KEYDOWN, VK_F9, 0);
            if (state->debug_timer_count == 6) SendMessageW(window, WM_KEYDOWN, VK_F11, 0);
            if (state->debug_timer_count == 9) SendMessageW(window, WM_KEYDOWN, VK_F10, 0);
        }
        if (state->debug_paused && !state->debug_step_pending) {
            state->audio.update();
            if (state->debug_presented_frame != state->frame) {
                std::string inspector_error;
                if (!present_debug_inspector(*state, window, inspector_error)) {
                    std::cerr << "error: paused inspector render failed: " << inspector_error << '\n';
                    state->render_failed = true;
                    DestroyWindow(window);
                    return 0;
                }
                state->debug_presented_frame = state->frame;
                std::cout << "TC_DEBUG_INSPECTOR frame=" << state->frame << '\n';
            }
            return 0;
        }
        // A UI load can replace World during this timer callback. Keep the
        // bindings used by the current frame independent of that replacement.
        const auto bindings = state->runtime.world().input_bindings;
        const auto bound_key = [&bindings](const char* action) { return bindings.at(action); };
        if (state->options.scripted_input && state->frame == 0)
            SendMessageW(window, WM_KEYDOWN, static_cast<WPARAM>(bound_key("move_right")), 0);
        if (state->options.scripted_dpi_change && state->frame == 1) {
            RECT suggested{};
            GetWindowRect(window, &suggested);
            SendMessageW(window, WM_DPICHANGED, MAKEWPARAM(144, 144),
                         reinterpret_cast<LPARAM>(&suggested));
        }
        if (state->options.scripted_input && state->frame == state->options.frames / 2)
            SendMessageW(window, WM_KEYUP, static_cast<WPARAM>(bound_key("move_right")), 0);
        if (state->options.scripted_input && !state->options.scripted_debug_step && state->frame == 4)
            SendMessageW(window, WM_KEYDOWN, VK_F9, 0);
        if (state->options.scripted_motion_demo || state->options.scripted_motion_soak) {
            const auto key_event = [window](bool down, int key) {
                SendMessageW(window, down ? WM_KEYDOWN : WM_KEYUP, static_cast<WPARAM>(key), 0);
            };
            if (state->frame == 0) key_event(true, bound_key("move_forward"));
            if (state->frame == 40) key_event(true, bound_key("crouch"));
            if (state->frame == 80) {
                key_event(false, bound_key("crouch"));
                key_event(true, bound_key("crawl"));
            }
            if (state->frame == 225) {
                key_event(false, bound_key("crawl"));
            }
            if (state->frame == 230) {
                key_event(false, bound_key("move_forward"));
            }
            if (state->frame == 250) key_event(true, bound_key("jump"));
            if (state->frame == 251) key_event(false, bound_key("jump"));
            // An extended demo run moves clear of the low canopy before
            // reversing, without changing the original 380-frame baseline.
            if (state->options.scripted_motion_demo && state->options.scripted_reverse_into_canopy) {
                if (state->frame == 380) key_event(true, bound_key("move_backward"));
                if (state->frame == 410) key_event(false, bound_key("move_backward"));
            } else if (state->options.scripted_motion_demo) {
                if (state->frame == 380) key_event(true, bound_key("move_forward"));
                if (state->frame == 400) {
                    key_event(false, bound_key("move_forward"));
                    key_event(true, bound_key("move_backward"));
                }
                if (state->frame == 430) key_event(false, bound_key("move_backward"));
            }
            if (state->options.scripted_motion_soak && state->frame >= 380) {
                const int phase = (state->frame - 380) % 240;
                const int right = bound_key("move_right");
                const int left = bound_key("move_left");
                const bool lead_right = ((state->frame - 380) / 240) % 2 == 0;
                const int lead = lead_right ? right : left;
                const int trail = lead_right ? left : right;
                const int crouch = bound_key("crouch");
                const int crawl = bound_key("crawl");
                if (phase == 0) key_event(true, lead);
                if (phase == 30) { key_event(false, lead); key_event(true, trail); }
                if (phase == 60) {
                    key_event(false, trail); key_event(true, lead); key_event(true, crouch);
                }
                if (phase == 90) { key_event(false, lead); key_event(true, trail); }
                if (phase == 120) {
                    key_event(false, trail); key_event(false, crouch);
                    key_event(true, lead); key_event(true, crawl);
                }
                if (phase == 150) { key_event(false, lead); key_event(true, trail); }
                if (phase == 180) {
                    key_event(false, trail); key_event(false, crawl);
                    key_event(true, bound_key("jump"));
                }
                if (phase == 181) key_event(false, bound_key("jump"));
            }
        }
        if (state->options.scripted_save_load) {
            if (state->frame == 0) SendMessageW(window, WM_KEYDOWN, static_cast<WPARAM>(bound_key("move_right")), 0);
            if (state->frame == 4) SendMessageW(window, WM_KEYDOWN, VK_F5, 0);
            if (state->frame == 8) SendMessageW(window, WM_KEYDOWN, VK_F6, 0);
            if (state->frame == 9) SendMessageW(window, WM_KEYUP, static_cast<WPARAM>(bound_key("move_right")), 0);
        }
        if (state->options.scripted_load_only && state->frame == 2)
            SendMessageW(window, WM_KEYDOWN, VK_F6, 0);
        if (state->options.scripted_load_then_save) {
            if (state->frame == 2) SendMessageW(window, WM_KEYDOWN, VK_F6, 0);
            if (state->frame == 5) SendMessageW(window, WM_KEYDOWN, VK_F5, 0);
        }
        if (state->options.scripted_keyboard_ui) {
            if (state->frame == 0 || state->frame == 2)
                SendMessageW(window, WM_KEYDOWN, VK_TAB, 0);
            if (state->frame == 1 || state->frame == 3)
                SendMessageW(window, WM_KEYDOWN, VK_RETURN, 0);
            if (state->frame == 4) SendMessageW(window, WM_KEYDOWN, VK_ESCAPE, 0);
            if (state->frame == 5) SendMessageW(window, WM_KEYDOWN, VK_RETURN, 0);
        }
        if (state->options.scripted_focus_loss_rebind) {
            if (state->frame <= 2) SendMessageW(window, WM_KEYDOWN, VK_TAB, 0);
            if (state->frame == 3 || state->frame == 5)
                SendMessageW(window, WM_KEYDOWN, VK_RETURN, 0);
            if (state->frame == 4) SendMessageW(window, WM_KILLFOCUS, 0, 0);
        }
        if (state->options.scripted_gamepad_disconnect_ui ||
            state->options.scripted_gamepad_disconnect_rebind ||
            state->options.scripted_gamepad_switch_ui) {
            const int key_down = state->options.scripted_gamepad_disconnect_rebind ? 10 : 4;
            const int key_up = state->options.scripted_gamepad_disconnect_rebind ? 20 : 14;
            if (state->frame == key_down)
                SendMessageW(window, WM_KEYDOWN, static_cast<WPARAM>(bound_key("move_right")), 0);
            if (state->frame == key_up)
                SendMessageW(window, WM_KEYUP, static_cast<WPARAM>(bound_key("move_right")), 0);
        }
        const auto held = [state](int key) { return key >= 0 && key < 256 && state->pressed_keys[static_cast<std::size_t>(key)]; };
        tc::runtime::GamepadSnapshot gamepad_snapshot{};
        const int previous_pad_index = state->gamepad_index;
        if (state->options.scripted_gamepad_demo || state->options.scripted_gamepad_ui ||
            state->options.scripted_gamepad_load_ui ||
            state->options.scripted_gamepad_disconnect_ui ||
            state->options.scripted_gamepad_disconnect_rebind ||
            state->options.scripted_gamepad_switch_ui ||
            state->options.scripted_rebind_ui || state->options.scripted_profile_check ||
            state->options.scripted_focus_loss_rebind) {
            gamepad_snapshot = state->options.scripted_focus_loss_rebind ?
                scripted_focus_loss_rebind_snapshot(state->frame) :
                state->options.scripted_gamepad_switch_ui ?
                scripted_gamepad_switch_snapshot(state->frame, state->runtime.world().gamepad_bindings) :
                (state->options.scripted_gamepad_disconnect_ui ||
                                state->options.scripted_gamepad_disconnect_rebind) ?
                scripted_gamepad_disconnect_snapshot(state->frame, state->runtime.world().gamepad_bindings,
                                                     state->options.scripted_gamepad_disconnect_rebind) :
                (state->options.scripted_rebind_ui || state->options.scripted_profile_check) ?
                scripted_rebind_snapshot(state->frame) :
                (state->options.scripted_gamepad_ui || state->options.scripted_gamepad_load_ui ?
                    scripted_gamepad_ui_snapshot(state->frame, state->runtime.world().gamepad_bindings,
                                                 state->options.scripted_gamepad_load_ui) :
                    scripted_gamepad_snapshot(state->frame, state->runtime.world().gamepad_bindings));
            state->gamepad_index = state->options.scripted_gamepad_switch_ui && state->frame >= 2 ? 1 : 0;
            if (state->options.scripted_gamepad_switch_ui) gamepad_snapshot.connected = true;
        } else if (!state->options.scripted_input && !state->options.scripted_keyboard_ui &&
                   !state->options.scripted_motion_demo &&
                   !state->options.scripted_motion_soak &&
                   !state->options.scripted_save_load && !state->options.scripted_load_only &&
                   !state->options.scripted_load_then_save &&
                   !state->options.scripted_audio_mute_ui &&
                   !state->options.scripted_audio_profile_check &&
                   !state->options.scripted_audio_restart &&
                   GetForegroundWindow() == window) {
            const int previous_index = state->gamepad_index;
            gamepad_snapshot = poll_xbox_controller(state->gamepad_index);
            if (state->gamepad_index != previous_index)
                std::cout << "TC_GAMEPAD_" << (gamepad_snapshot.connected ? "CONNECTED" : "DISCONNECTED")
                          << " index=" << (gamepad_snapshot.connected ? state->gamepad_index : previous_index) << '\n';
        } else {
            state->gamepad_index = -1;
        }
        const bool owner_changed = state->gamepad_was_connected && gamepad_snapshot.connected &&
            previous_pad_index >= 0 && state->gamepad_index != previous_pad_index;
        const bool reconnected = !state->gamepad_was_connected && gamepad_snapshot.connected &&
            state->gamepad_input_was_lost;
        const std::uint16_t owner_buttons_on_switch = gamepad_snapshot.buttons;
        if (owner_changed || reconnected) {
            state->suppressed_owner_buttons = owner_buttons_on_switch;
            state->awaiting_owner_stick_neutral =
                std::hypot(static_cast<float>(gamepad_snapshot.left_x),
                           static_cast<float>(gamepad_snapshot.left_y)) > tc::runtime::gamepad_left_deadzone;
        }
        if ((state->gamepad_was_connected && !gamepad_snapshot.connected) || owner_changed || reconnected) {
            close_ui_focus(*state);
            if (!state->pending_rebind_action.empty()) {
                state->pending_rebind_action.clear();
                update_rebind_labels(*state);
            }
            if (owner_changed || reconnected) {
                if (owner_changed)
                    std::cout << "TC_GAMEPAD_OWNER_CHANGED from=" << previous_pad_index
                              << " to=" << state->gamepad_index << "\n";
                else
                    std::cout << "TC_GAMEPAD_RECONNECTED neutral_guard=1\n";
                gamepad_snapshot.left_x = 0;
                gamepad_snapshot.left_y = 0;
                gamepad_snapshot.buttons = 0;
            } else {
                state->suppressed_owner_buttons = 0;
                state->awaiting_owner_stick_neutral = false;
                state->gamepad_input_was_lost = true;
                std::cout << "TC_GAMEPAD_INPUT_LOST keyboard_fallback=1\n";
            }
        }
        if (reconnected) state->gamepad_input_was_lost = false;
        const bool connection_changed = state->gamepad_was_connected != gamepad_snapshot.connected;
        state->gamepad_was_connected = gamepad_snapshot.connected;
        if (connection_changed && state->pending_rebind_action.empty()) update_rebind_labels(*state);
        const std::uint16_t buttons = gamepad_snapshot.connected ? gamepad_snapshot.buttons : 0;
        std::uint16_t newly_pressed = buttons & ~state->previous_gamepad_buttons;
        state->previous_gamepad_buttons = (owner_changed || reconnected) ? owner_buttons_on_switch : buttons;
        state->suppressed_owner_buttons &= (owner_changed || reconnected) ? owner_buttons_on_switch : buttons;
        gamepad_snapshot.buttons &= static_cast<std::uint16_t>(~state->suppressed_owner_buttons);
        if (state->awaiting_owner_stick_neutral) {
            if (!owner_changed && !reconnected &&
                std::hypot(static_cast<float>(gamepad_snapshot.left_x),
                           static_cast<float>(gamepad_snapshot.left_y)) <= tc::runtime::gamepad_left_deadzone)
                state->awaiting_owner_stick_neutral = false;
            else {
                gamepad_snapshot.left_x = 0;
                gamepad_snapshot.left_y = 0;
            }
        }
        if (!state->pending_rebind_action.empty() && newly_pressed != 0) {
            const std::uint16_t candidate = static_cast<std::uint16_t>(
                newly_pressed & (static_cast<unsigned>(~newly_pressed) + 1U));
            auto proposed_bindings = state->runtime.world().gamepad_bindings;
            if (tc::runtime::try_rebind_gamepad(proposed_bindings,
                                                state->pending_rebind_action, candidate)) {
                bool persisted = true;
                if (!state->input_profile.empty()) {
                    std::string profile_error;
                    persisted = write_input_profile(state->input_profile, proposed_bindings, profile_error);
                    if (persisted)
                        std::cout << "TC_GAMEPAD_PROFILE_SAVED path=" << path_utf8(state->input_profile) << '\n';
                    else
                        std::cerr << "TC_GAMEPAD_PROFILE_SAVE_FAILED reason=" << profile_error << '\n';
                }
                if (persisted) {
                    state->runtime.world().gamepad_bindings = proposed_bindings;
                    std::cout << "TC_GAMEPAD_REBOUND action=" << state->pending_rebind_action
                              << " button=" << gamepad_button_name(candidate) << '\n';
                    update_rebind_labels(*state);
                    state->pending_rebind_action.clear();
                    close_ui_focus(*state);
                } else {
                    std::cout << "TC_GAMEPAD_REBIND_REJECTED action=" << state->pending_rebind_action
                              << " button=" << gamepad_button_name(candidate)
                              << " reason=profile_save_failed\n";
                    update_rebind_labels(*state);
                    state->pending_rebind_action.clear();
                    close_ui_focus(*state);
                }
            } else {
                std::cout << "TC_GAMEPAD_REBIND_REJECTED action=" << state->pending_rebind_action
                          << " button=" << gamepad_button_name(candidate) << '\n';
            }
            newly_pressed = 0;
        }
        const auto gamepad_bindings = state->runtime.world().gamepad_bindings;
        if (newly_pressed & gamepad_bindings.ui_menu) {
            if (state->focused_ui_button >= 0) close_ui_focus(*state);
            else focus_ui_button(*state, window, 1);
        }
        if (state->focused_ui_button >= 0) {
            if (newly_pressed & tc::runtime::gamepad_dpad_down) focus_ui_button(*state, window, 1);
            if (newly_pressed & tc::runtime::gamepad_dpad_up) focus_ui_button(*state, window, -1);
            if (newly_pressed & gamepad_bindings.ui_cancel) close_ui_focus(*state);
            else if ((newly_pressed & gamepad_bindings.ui_confirm) &&
                     focused_ui_visible(*state, window)) {
                capture_stage("ui_activate_begin");
                activate_ui_widget(*state, state->runtime.world().ui_widgets[
                    static_cast<std::size_t>(state->focused_ui_button)]);
                capture_stage("ui_activate_complete");
            }
        }
        capture_stage("input_complete");
        const auto gamepad = tc::runtime::map_gamepad(gamepad_snapshot, gamepad_bindings);
        const bool scripted_action_held =
            (state->options.scripted_rebind_action == "jump" && gamepad.jump) ||
            (state->options.scripted_rebind_action == "crouch" && gamepad.crouch) ||
            (state->options.scripted_rebind_action == "crawl" && gamepad.crawl);
        if (state->frame == 7 && scripted_action_held && state->options.scripted_rebind_ui)
            std::cout << "TC_GAMEPAD_REBIND_USED action=" << state->options.scripted_rebind_action
                      << " button=SOUTH\n";
        if (state->frame == 7 && scripted_action_held && state->options.scripted_profile_check)
            std::cout << "TC_GAMEPAD_PROFILE_USED action=" << state->options.scripted_rebind_action
                      << " button=SOUTH\n";
        // An acceptance-script route is frame-driven, not a physical held key:
        // WM_KILLFOCUS may clear key state when another test window appears.
        const bool scripted_move_right = state->options.scripted_input &&
            state->frame < state->options.frames / 2;
        const float keyboard_x = ((scripted_move_right || held(bound_key("move_right"))) ? 1.0F : 0.0F) -
                                 (held(bound_key("move_left")) ? 1.0F : 0.0F);
        const float keyboard_y = (held(bound_key("move_forward")) ? 1.0F : 0.0F) -
                                 (held(bound_key("move_backward")) ? 1.0F : 0.0F);
        const float x = std::abs(gamepad.move_x) > 0.001F ? gamepad.move_x : keyboard_x;
        const float y = std::abs(gamepad.move_y) > 0.001F ? gamepad.move_y : keyboard_y;
        if (gamepad.connected && state->frame == 0 && state->options.scripted_gamepad_demo)
            std::cout << "TC_GAMEPAD_INPUT source=simulated index=0\n";
        const bool ui_active = state->focused_ui_button >= 0;
        state->runtime.set_input_axis(ui_active ? 0.0F : x, ui_active ? 0.0F : y);
        state->runtime.set_jump_pressed(!ui_active && (held(bound_key("jump")) || gamepad.jump));
        state->runtime.set_stance_pressed(!ui_active && (held(bound_key("crouch")) || gamepad.crouch),
                                          !ui_active && (held(bound_key("crawl")) || gamepad.crawl));
        state->runtime.tick(delta);
        if (state->debug_step_pending) {
            state->debug_step_pending = false;
            std::cout << "TC_DEBUG_STEP frame=" << state->frame + 1 << '\n';
        }
        capture_stage("runtime_tick_complete");
        state->audio.update();
        capture_stage("audio_update_complete");
        for (const auto& completion : state->audio.take_completions())
            append_audio_result(state->options, completion.source,
                                completion.completed ? "completed" : "failed", completion.error);
        if (state->options.scripted_audio_restart && state->audio_restart_requested &&
            !state->audio_restart_replayed) {
            std::string audio_error;
            const bool replayed = state->audio.play(argument_path(state->restart_audio_source),
                                                    1.0F, audio_error);
            append_audio_restart_result(state->options, "replay", replayed, audio_error,
                                        state->audio.active_voices(), state->audio.muted(),
                                        state->audio.monitoring_default_output());
            state->audio_restart_replayed = true;
        }
        ++state->frame;
        if (state->options.break_player_x && !state->debug_breakpoint_fired) {
            const auto& world = state->runtime.world();
            const auto player = world.find_entity("Player");
            const auto found = world.transforms.find(player);
            if (player != 0U && found != world.transforms.end() &&
                found->second.position.x >= *state->options.break_player_x) {
                state->debug_breakpoint_fired = true;
                state->debug_paused = true;
                state->debug_presented_frame = -1;
                std::cout << "TC_DEBUG_BREAK condition=player_x frame=" << state->frame
                          << " player_x=" << found->second.position.x << '\n';
            }
        }
        if (state->ui_status_expires_at >= 0 && state->frame >= state->ui_status_expires_at) {
            for (auto& widget : state->runtime.world().ui_widgets)
                if (widget.id == "objective" && widget.type == "text") {
                    widget.text = state->ui_status_original;
                    break;
                }
            state->ui_status_expires_at = -1;
        }
        append_traces(state->options, state->runtime, state->logged_traces);
        capture_stage("event_trace_complete");
        while (state->played_events < state->runtime.world().events.size()) {
            const auto& event = state->runtime.world().events[state->played_events++];
            if (event.starts_with("Audio:")) {
                std::string source = event.substr(6);
                if (const auto asset = state->runtime.world().assets.find(source); asset != state->runtime.world().assets.end()) {
                    source = path_utf8(asset->second.source);
                }
                std::string audio_error;
                const bool submitted = state->audio.play(argument_path(source), 1.0F, audio_error);
                append_audio_result(state->options, source, submitted ? "submitted" : "failed",
                                    audio_error, state->audio.active_voices());
                if (state->options.scripted_audio_restart && submitted &&
                    state->restart_audio_source.empty()) state->restart_audio_source = source;
                if (!submitted) {
                    OutputDebugStringA(("TC Audio: " + audio_error + "\n").c_str());
                }
            } else if (event == "SaveRequested") {
                save_windowed_game(*state, "event");
            }
        }
        if (state->options.scripted_audio_restart && !state->audio_restart_requested &&
            !state->restart_audio_source.empty()) {
            const auto active = state->audio.active_voices();
            std::string audio_error;
            const bool mute_applied = state->audio.set_muted(true, audio_error);
            state->audio.request_output_restart();
            append_audio_restart_result(state->options, "requested", active > 0 && mute_applied,
                                        audio_error, active,
                                        state->audio.muted(),
                                        state->audio.monitoring_default_output());
            state->audio_restart_requested = true;
        }
        std::string renderer_error;
        capture_stage("render_call_begin");
        const auto render_start = Clock::now();
        if (state->gpu.ready()) {
            const bool capture_this_frame = !state->options.screenshot.empty() &&
                !state->screenshot_written && state->frame >= state->options.screenshot_frame;
            const auto* capture_path = capture_this_frame ? &state->options.screenshot : nullptr;
            if (!state->gpu.render(state->runtime.world(), renderer_error, capture_path)) {
                std::cerr << "error: renderer frame failed: " << renderer_error << '\n';
                state->render_failed = true;
                DestroyWindow(window);
                return 0;
            }
            if (capture_this_frame) state->screenshot_written = true;
        } else {
            InvalidateRect(window, nullptr, FALSE);
        }
        const double render_wall_ms = std::chrono::duration<double, std::milli>(
            Clock::now() - render_start).count();
        if ((state->options.scripted_input || state->options.scripted_rebind_ui ||
             state->options.scripted_audio_mute_ui) &&
            (state->frame == 3 || (state->options.scripted_audio_mute_ui &&
                                   !state->options.scripted_audio_mute_once && state->frame == 10))) {
            const auto& world = state->runtime.world();
            RECT client{};
            GetClientRect(window, &client);
            const auto layout = tc::runtime::layout_ui_widgets(
                world, static_cast<float>(client.right), static_cast<float>(client.bottom),
                state->ui_scale);
            for (std::size_t index = 0; index < world.ui_widgets.size(); ++index) {
                const auto& widget = world.ui_widgets[index];
                if (!layout[index].visible || widget.type != "button" || widget.on_activate.empty() ||
                    (state->options.scripted_rebind_ui &&
                     widget.on_activate != "rebind_" + state->options.scripted_rebind_action) ||
                    (state->options.scripted_audio_mute_ui && widget.on_activate != "audio_toggle")) continue;
                const auto& bounds = layout[index];
                const int click_x = static_cast<int>(bounds.x + bounds.width * 0.5F);
                const int click_y = static_cast<int>(bounds.y + bounds.height * 0.5F);
                PostMessageW(window, WM_LBUTTONUP, 0, MAKELPARAM(click_x, click_y));
                break;
            }
        }
        append_profile(state->options, state->runtime, state->frame, &state->gpu,
                       frame_interval_ms, delta, render_wall_ms);
        if (state->options.frames > 0 && state->frame >= state->options.frames) {
            DestroyWindow(window);
        }
        return 0;
    }
    if (message == WM_KEYDOWN && state != nullptr) {
        if (wparam == VK_TAB) {
            if ((lparam & (1LL << 30)) == 0)
                focus_ui_button(*state, window, (GetKeyState(VK_SHIFT) & 0x8000) ? -1 : 1);
            return 0;
        }
        if (state->focused_ui_button >= 0 && (wparam == VK_RETURN || wparam == VK_SPACE)) {
            if ((lparam & (1LL << 30)) == 0 && focused_ui_visible(*state, window))
                activate_ui_widget(*state, state->runtime.world().ui_widgets[
                    static_cast<std::size_t>(state->focused_ui_button)]);
            return 0;
        }
        if (wparam < state->pressed_keys.size()) state->pressed_keys[static_cast<std::size_t>(wparam)] = true;
        if ((state->options.scripted_input || state->options.scripted_gamepad_disconnect_ui ||
             state->options.scripted_gamepad_disconnect_rebind ||
             state->options.scripted_gamepad_switch_ui) &&
            static_cast<int>(wparam) == state->runtime.world().input_bindings.at("move_right"))
            std::cout << "TC_INPUT_BINDING_USED action=move_right key=" << wparam << '\n';
        if (wparam == VK_ESCAPE) {
            // One physical press performs one dismissal; key auto-repeat must
            // not immediately turn a mouse-look cancel into an app exit.
            if ((lparam & (1LL << 30)) != 0) return 0;
            if (state->mouse_look_active) {
                state->mouse_look_active = false;
                if (GetCapture() == window) ReleaseCapture();
            } else if (state->focused_ui_button >= 0) close_ui_focus(*state);
            else PostMessageW(window, WM_CLOSE, 0, 0);
        }
        if (wparam == VK_F5) {
            save_windowed_game(*state, "hotkey");
        }
        if (wparam == VK_F6) load_windowed_game(*state, "hotkey");
        if (wparam == VK_F9) {
            if (write_debug_snapshot(state->options, state->runtime, state->frame))
                std::cout << "TC_DEBUG_SNAPSHOT_OK frame=" << state->frame << '\n';
            else
                std::cerr << "error: could not write runtime debug snapshot\n";
        }
        if (wparam == VK_F10 && (lparam & (1LL << 30)) == 0) {
            state->debug_paused = !state->debug_paused;
            state->debug_step_pending = false;
            state->debug_presented_frame = -1;
            state->previous = Clock::now();
            std::cout << (state->debug_paused ? "TC_DEBUG_PAUSED frame=" : "TC_DEBUG_RESUMED frame=")
                      << state->frame << '\n';
        }
        if (wparam == VK_F11 && state->debug_paused && (lparam & (1LL << 30)) == 0)
            state->debug_step_pending = true;
        return 0;
    }
    if (message == WM_KEYUP && state != nullptr) {
        if (wparam < state->pressed_keys.size()) state->pressed_keys[static_cast<std::size_t>(wparam)] = false;
        return 0;
    }
    if (message == WM_RBUTTONDOWN && state != nullptr && !state->options.scripted_mode &&
        state->focused_ui_button < 0) {
        RECT client{};
        GetClientRect(window, &client);
        const float x = static_cast<float>(static_cast<short>(LOWORD(lparam)));
        const float y = static_cast<float>(static_cast<short>(HIWORD(lparam)));
        const auto layout = tc::runtime::layout_ui_widgets(
            state->runtime.world(), static_cast<float>(client.right),
            static_cast<float>(client.bottom), state->ui_scale);
        for (const auto& bounds : layout) {
            if (bounds.visible && x >= bounds.x && x <= bounds.x + bounds.width &&
                y >= bounds.y && y <= bounds.y + bounds.height)
                return 0;
        }
        state->mouse_look_active = true;
        state->mouse_last_x = static_cast<short>(LOWORD(lparam));
        state->mouse_last_y = static_cast<short>(HIWORD(lparam));
        SetCapture(window);
        return 0;
    }
    if (message == WM_MOUSEMOVE && state != nullptr && state->mouse_look_active) {
        const int x = static_cast<short>(LOWORD(lparam));
        const int y = static_cast<short>(HIWORD(lparam));
        const int dx = std::clamp(x - state->mouse_last_x, -50, 50);
        const int dy = std::clamp(y - state->mouse_last_y, -50, 50);
        state->mouse_last_x = x;
        state->mouse_last_y = y;
        state->camera_yaw_degrees = std::remainder(state->camera_yaw_degrees + 0.18F * dx, 360.0F);
        state->camera_pitch_degrees = std::clamp(state->camera_pitch_degrees - 0.18F * dy, -60.0F, 60.0F);
        state->runtime.set_camera_orbit(state->camera_yaw_degrees, state->camera_pitch_degrees);
        return 0;
    }
    if (message == WM_RBUTTONUP && state != nullptr) {
        state->mouse_look_active = false;
        if (GetCapture() == window) ReleaseCapture();
        return 0;
    }
    if (message == WM_CAPTURECHANGED && state != nullptr) {
        state->mouse_look_active = false;
        return 0;
    }
    if (message == WM_KILLFOCUS && state != nullptr) {
        // Automation opens many short-lived Player windows. Only the explicit
        // focus-loss scenario should let an external focus switch interrupt a
        // frame-scripted UI sequence; ordinary play keeps the safety behavior.
        if (state->options.scripted_mode && !state->options.scripted_focus_loss_rebind)
            return 0;
        state->pressed_keys.fill(false);
        state->mouse_look_active = false;
        if (GetCapture() == window) ReleaseCapture();
        state->previous_gamepad_buttons = 0;
        if (state->focused_ui_button >= 0 || !state->pending_rebind_action.empty()) {
            const bool cancelled_rebind = !state->pending_rebind_action.empty();
            state->pending_rebind_action.clear();
            update_rebind_labels(*state);
            close_ui_focus(*state);
            std::cout << "TC_UI_FOCUS_LOST pending_rebind_cancelled="
                      << (cancelled_rebind ? 1 : 0) << '\n';
        }
        return 0;
    }
    if (message == WM_LBUTTONUP && state != nullptr) {
        RECT client{};
        GetClientRect(window, &client);
        const auto& world = state->runtime.world();
        if (client.right > 0 && client.bottom > 0) {
            const float x = static_cast<float>(static_cast<short>(LOWORD(lparam)));
            const float y = static_cast<float>(static_cast<short>(HIWORD(lparam)));
            const auto layout = tc::runtime::layout_ui_widgets(
                world, static_cast<float>(client.right), static_cast<float>(client.bottom),
                state->ui_scale);
            for (std::size_t index = world.ui_widgets.size(); index-- > 0;) {
                const auto& bounds = layout[index];
                const auto& widget = world.ui_widgets[index];
                if (!bounds.visible || widget.type != "button" || x < bounds.x || x > bounds.x + bounds.width ||
                    y < bounds.y || y > bounds.y + bounds.height) continue;
                state->mouse_look_active = false;
                if (GetCapture() == window) ReleaseCapture();
                activate_ui_widget(*state, widget);
                return 0;
            }
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
    if (message == WM_DPICHANGED && state != nullptr) {
        const UINT dpi = HIWORD(wparam);
        state->ui_scale = std::clamp(state->options.ui_scale *
            static_cast<float>(dpi == 0 ? 96U : dpi) / 96.0F, 0.75F, 10.0F);
        state->gpu.set_ui_scale(state->ui_scale);
        const auto* suggested = reinterpret_cast<const RECT*>(lparam);
        if (suggested != nullptr)
            SetWindowPos(window, nullptr, suggested->left, suggested->top,
                         suggested->right - suggested->left,
                         suggested->bottom - suggested->top, SWP_NOZORDER | SWP_NOACTIVATE);
        if (state->focused_ui_button >= 0 && !focused_ui_visible(*state, window))
            close_ui_focus(*state);
        std::cout << "TC_DPI_CHANGED dpi=" << dpi << " ui_scale=" << state->ui_scale << '\n';
        return 0;
    }
    if (message == WM_SIZE && state != nullptr && wparam != SIZE_MINIMIZED &&
        state->focused_ui_button >= 0 && !focused_ui_visible(*state, window))
        close_ui_focus(*state);
    if (message == WM_SIZE && state != nullptr) {
        const bool minimized = wparam == SIZE_MINIMIZED;
        if (minimized != state->window_minimized) {
            state->window_minimized = minimized;
            state->previous = Clock::now();
            std::cout << (minimized ? "TC_WINDOW_MINIMIZED frame=" : "TC_WINDOW_RESTORED frame=")
                      << state->frame << '\n';
            std::string audio_error;
            if (state->audio.set_suspended(minimized, audio_error))
                std::cout << (minimized ? "TC_AUDIO_SUSPENDED frame=" : "TC_AUDIO_RESUMED frame=")
                          << state->frame << '\n';
            else
                std::cerr << "error: audio window lifecycle failed: " << audio_error << '\n';
        }
    }
    if (message == WM_SIZE && state != nullptr && state->gpu.ready() && wparam != SIZE_MINIMIZED) {
        std::string resize_error;
        if (!state->gpu.resize(LOWORD(lparam), HIWORD(lparam), resize_error)) {
            std::cerr << "error: renderer resize failed: " << resize_error << '\n';
            state->render_failed = true;
            DestroyWindow(window);
        }
        state->debug_presented_frame = -1;
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
    state.runtime.set_success_trace_enabled(options.trace_graph);
    state.ui_scale = options.ui_scale;
    state.gpu.set_vsync(!options.benchmark_unsynced);
    state.gpu.set_ui_scale(options.ui_scale);
    std::string error;
    if (!state.runtime.load_manifest(options.scene, error)) {
        std::cerr << path_utf8(options.scene) << ":1: error TC0001: " << error << '\n';
        if (options.frames <= 0)
            MessageBoxA(nullptr, error.c_str(), "TC Player", MB_ICONERROR | MB_OK);
        return 2;
    }
    if (!options.save_dir.empty()) state.save_dir = std::filesystem::absolute(options.save_dir);
    else if (options.scripted_input || options.scripted_keyboard_ui ||
             options.scripted_focus_loss_rebind ||
             options.scripted_motion_demo || options.scripted_motion_soak ||
             options.scripted_gamepad_demo || options.scripted_gamepad_ui ||
             options.scripted_gamepad_load_ui ||
             options.scripted_gamepad_disconnect_ui ||
             options.scripted_gamepad_disconnect_rebind ||
             options.scripted_gamepad_switch_ui ||
             options.scripted_rebind_ui || options.scripted_profile_check ||
             options.scripted_audio_mute_ui || options.scripted_audio_profile_check ||
             options.scripted_audio_restart)
        state.save_dir = options.scene.parent_path();
    else state.save_dir = default_save_dir(options.scene, state.runtime.world().scene_id);
    if (!options.input_profile.empty()) state.input_profile = std::filesystem::absolute(options.input_profile);
    else if (!options.scripted_input && !options.scripted_keyboard_ui &&
             !options.scripted_focus_loss_rebind &&
             !options.scripted_motion_demo &&
             !options.scripted_motion_soak &&
             !options.scripted_gamepad_demo && !options.scripted_gamepad_ui &&
             !options.scripted_gamepad_load_ui &&
             !options.scripted_gamepad_disconnect_ui &&
             !options.scripted_gamepad_disconnect_rebind &&
             !options.scripted_gamepad_switch_ui &&
             !options.scripted_rebind_ui && !options.scripted_profile_check &&
             !options.scripted_audio_mute_ui && !options.scripted_audio_profile_check &&
             !options.scripted_audio_restart)
        state.input_profile = default_scene_profile(options.scene, state.runtime.world().scene_id, ".tcinput");
    if (options.input_profile.empty() && !state.runtime.world().scene_id.empty() &&
        !state.input_profile.empty() && !std::filesystem::exists(state.input_profile) &&
        !std::filesystem::exists(sidecar_path(state.input_profile, ".tmp")) &&
        !std::filesystem::exists(sidecar_path(state.input_profile, ".bak"))) {
        const auto legacy = default_input_profile(options.scene);
        if (std::filesystem::exists(legacy) ||
            std::filesystem::exists(sidecar_path(legacy, ".bak"))) {
            auto bindings = state.runtime.world().gamepad_bindings;
            std::string migration_error;
            if (read_input_profile(legacy, bindings, migration_error) &&
                write_input_profile(state.input_profile, bindings, migration_error))
                std::cout << "TC_GAMEPAD_PROFILE_MIGRATED from=" << path_utf8(legacy) << '\n';
            else
                std::cerr << "TC_GAMEPAD_PROFILE_MIGRATION_FAILED reason=" << migration_error << '\n';
        }
    }
    if (!state.input_profile.empty() &&
        (std::filesystem::exists(state.input_profile) ||
         std::filesystem::exists(sidecar_path(state.input_profile, ".tmp")) ||
         std::filesystem::exists(sidecar_path(state.input_profile, ".bak")))) {
        if (read_input_profile(state.input_profile, state.runtime.world().gamepad_bindings, error)) {
            std::cout << "TC_GAMEPAD_PROFILE_LOADED path=" << path_utf8(state.input_profile) << '\n';
            if (!error.empty()) std::cout << "TC_GAMEPAD_PROFILE_RECOVERED source="
                                          << (error.find("pending") != std::string::npos ? "pending" : "backup") << '\n';
        } else
            std::cerr << "TC_GAMEPAD_PROFILE_REJECTED reason=" << error << '\n';
    }
    update_rebind_labels(state);
    state.runtime.begin_play();
    if (!options.audio_profile.empty()) state.audio_profile = std::filesystem::absolute(options.audio_profile);
    else if (!options.scripted_input && !options.scripted_keyboard_ui &&
             !options.scripted_focus_loss_rebind &&
             !options.scripted_motion_demo &&
             !options.scripted_motion_soak &&
             !options.scripted_gamepad_demo && !options.scripted_gamepad_ui &&
             !options.scripted_gamepad_load_ui &&
             !options.scripted_gamepad_disconnect_ui &&
             !options.scripted_gamepad_disconnect_rebind &&
             !options.scripted_gamepad_switch_ui &&
             !options.scripted_rebind_ui && !options.scripted_profile_check &&
             !options.scripted_audio_mute_ui && !options.scripted_audio_profile_check &&
             !options.scripted_audio_restart) {
        state.audio_profile = default_scene_profile(options.scene, state.runtime.world().scene_id, ".tcaudio");
    }
    if (options.audio_profile.empty() && !state.runtime.world().scene_id.empty() &&
        !state.audio_profile.empty() && !std::filesystem::exists(state.audio_profile) &&
        !std::filesystem::exists(sidecar_path(state.audio_profile, ".tmp")) &&
        !std::filesystem::exists(sidecar_path(state.audio_profile, ".bak"))) {
        auto legacy = default_input_profile(options.scene);
        if (!legacy.empty()) legacy.replace_extension(L".tcaudio");
        if (std::filesystem::exists(legacy) ||
            std::filesystem::exists(sidecar_path(legacy, ".bak"))) {
            bool muted = false;
            std::string migration_error;
            if (read_audio_profile(legacy, muted, migration_error) &&
                write_audio_profile(state.audio_profile, muted, migration_error))
                std::cout << "TC_AUDIO_PROFILE_MIGRATED from=" << path_utf8(legacy) << '\n';
            else
                std::cerr << "TC_AUDIO_PROFILE_MIGRATION_FAILED reason=" << migration_error << '\n';
        }
    }
    if (!state.audio_profile.empty() &&
        (std::filesystem::exists(state.audio_profile) ||
         std::filesystem::exists(sidecar_path(state.audio_profile, ".tmp")) ||
         std::filesystem::exists(sidecar_path(state.audio_profile, ".bak")))) {
        bool persisted_muted = false;
        if (read_audio_profile(state.audio_profile, persisted_muted, error)) {
            const bool recovered_profile = !error.empty();
            const bool recovered_pending_profile = error.find("pending") != std::string::npos;
            if (state.audio.set_muted(persisted_muted, error)) {
                std::cout << "TC_AUDIO_PROFILE_LOADED muted=" << (persisted_muted ? 1 : 0) << '\n';
                if (recovered_profile) std::cout << "TC_AUDIO_PROFILE_RECOVERED source="
                                                 << (recovered_pending_profile ? "pending" : "backup") << '\n';
            } else
                std::cerr << "TC_AUDIO_PROFILE_REJECTED reason=" << error << '\n';
        } else {
            std::cerr << "TC_AUDIO_PROFILE_REJECTED reason=" << error << '\n';
        }
    }
    for (auto& widget : state.runtime.world().ui_widgets) if (widget.on_activate == "audio_toggle") {
        widget.text = state.audio.muted() ? "Audio: Muted" : "Audio: On";
        widget.accessible_name = state.audio.muted() ? "Unmute audio" : "Mute audio";
    }
    std::cout << "TC_AUDIO_PROFILE_STATE muted=" << (state.audio.muted() ? 1 : 0) << '\n';
    const wchar_t* class_name = L"TheEntireWorldTcPlayer";
    WNDCLASSW window_class{};
    window_class.lpfnWndProc = window_proc;
    window_class.hInstance = instance;
    window_class.hCursor = LoadCursor(nullptr, IDC_ARROW);
    window_class.lpszClassName = class_name;
    RegisterClassW(&window_class);
    const std::wstring title = options.pie ? L"TC Play In Editor" : L"The Entire World Player";
    HWND window = CreateWindowExW(0, class_name, title.c_str(),
                                  (options.borderless ? WS_POPUP : WS_OVERLAPPEDWINDOW) | WS_VISIBLE,
                                  options.borderless ? 0 : CW_USEDEFAULT,
                                  options.borderless ? 0 : CW_USEDEFAULT,
                                  options.window_width, options.window_height,
                                  nullptr, nullptr, instance, &state);
    if (window == nullptr) return 3;
    MSG message{};
    while (GetMessageW(&message, nullptr, 0, 0) > 0) {
        TranslateMessage(&message);
        DispatchMessageW(&message);
    }
    for (const auto& trace : state.runtime.debug_trace()) {
        OutputDebugStringA((trace + "\n").c_str());
    }
    return state.render_failed ? 4 : 0;
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
    if (!options.headless &&
        !SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2) &&
        !AreDpiAwarenessContextsEqual(GetThreadDpiAwarenessContext(),
                                      DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2))
        std::cerr << "TC_DPI_AWARENESS_UNAVAILABLE error=" << GetLastError() << '\n';
    if (options.scene.empty()) {
        std::cerr << "Pass --scene <file.tcruntime>.\n";
        if (options.frames <= 0)
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
