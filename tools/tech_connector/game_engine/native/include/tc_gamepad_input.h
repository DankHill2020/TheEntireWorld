#ifndef TC_GAMEPAD_INPUT_H
#define TC_GAMEPAD_INPUT_H

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <iomanip>
#include <locale>
#include <sstream>
#include <string>
#include <string_view>
#include <utility>

namespace tc::runtime {

struct GamepadSnapshot {
    bool connected{false};
    std::int16_t left_x{0};
    std::int16_t left_y{0};
    std::uint16_t buttons{0};
};

struct GamepadActions {
    bool connected{false};
    float move_x{0.0F};
    float move_y{0.0F};
    bool jump{false};
    bool crouch{false};
    bool crawl{false};
};

inline constexpr std::uint16_t gamepad_dpad_up = 0x0001;
inline constexpr std::uint16_t gamepad_dpad_down = 0x0002;
inline constexpr std::uint16_t gamepad_dpad_left = 0x0004;
inline constexpr std::uint16_t gamepad_dpad_right = 0x0008;
inline constexpr std::uint16_t gamepad_menu = 0x0010;
// Platform adapters translate physical buttons to positions before gameplay sees them.
// XInput A/B/X and DualSense Cross/Circle/Square are south/east/west respectively.
inline constexpr std::uint16_t gamepad_face_south = 0x1000;
inline constexpr std::uint16_t gamepad_face_east = 0x2000;
inline constexpr std::uint16_t gamepad_face_west = 0x4000;
inline constexpr std::uint16_t gamepad_face_north = 0x8000;
inline constexpr std::uint16_t gamepad_left_shoulder = 0x0100;
inline constexpr std::uint16_t gamepad_right_shoulder = 0x0200;
inline constexpr std::uint16_t gamepad_a = gamepad_face_south;
inline constexpr std::uint16_t gamepad_b = gamepad_face_east;
inline constexpr std::uint16_t gamepad_x = gamepad_face_west;
inline constexpr float gamepad_left_deadzone = 7849.0F;

struct GamepadBindings {
    std::uint16_t jump{gamepad_face_south};
    std::uint16_t crouch{gamepad_face_east};
    std::uint16_t crawl{gamepad_face_west};
    std::uint16_t ui_confirm{gamepad_face_south};
    std::uint16_t ui_cancel{gamepad_face_east};
    std::uint16_t ui_menu{gamepad_menu};
};

inline std::uint16_t gamepad_button_mask(std::string_view name) {
    if (name == "SOUTH") return gamepad_face_south;
    if (name == "EAST") return gamepad_face_east;
    if (name == "WEST") return gamepad_face_west;
    if (name == "NORTH") return gamepad_face_north;
    if (name == "LEFT_SHOULDER") return gamepad_left_shoulder;
    if (name == "RIGHT_SHOULDER") return gamepad_right_shoulder;
    if (name == "MENU") return gamepad_menu;
    return 0;
}

inline std::string_view gamepad_button_name(std::uint16_t mask) {
    if (mask == gamepad_face_south) return "SOUTH";
    if (mask == gamepad_face_east) return "EAST";
    if (mask == gamepad_face_west) return "WEST";
    if (mask == gamepad_face_north) return "NORTH";
    if (mask == gamepad_left_shoulder) return "LEFT_SHOULDER";
    if (mask == gamepad_right_shoulder) return "RIGHT_SHOULDER";
    if (mask == gamepad_menu) return "MENU";
    return "UNKNOWN";
}

inline bool set_gamepad_binding(GamepadBindings& bindings, std::string_view action,
                                std::uint16_t mask) {
    if (mask == 0) return false;
    if (action == "jump") bindings.jump = mask;
    else if (action == "crouch") bindings.crouch = mask;
    else if (action == "crawl") bindings.crawl = mask;
    else if (action == "ui_confirm") bindings.ui_confirm = mask;
    else if (action == "ui_cancel") bindings.ui_cancel = mask;
    else if (action == "ui_menu") bindings.ui_menu = mask;
    else return false;
    return true;
}

inline bool valid_gamepad_bindings(const GamepadBindings& value) {
    return value.jump != value.crouch && value.jump != value.crawl &&
        value.crouch != value.crawl && value.ui_confirm != value.ui_cancel &&
        value.ui_confirm != value.ui_menu && value.ui_cancel != value.ui_menu &&
        value.jump != gamepad_menu && value.crouch != gamepad_menu &&
        value.crawl != gamepad_menu && value.jump != value.ui_menu &&
        value.crouch != value.ui_menu && value.crawl != value.ui_menu;
}

inline bool try_rebind_gamepad(GamepadBindings& bindings, std::string_view action,
                               std::uint16_t mask) {
    if (mask != gamepad_face_south && mask != gamepad_face_east &&
        mask != gamepad_face_west && mask != gamepad_face_north &&
        mask != gamepad_left_shoulder && mask != gamepad_right_shoulder &&
        mask != gamepad_menu) return false;
    if ((action == "jump" || action == "crouch" || action == "crawl") &&
        mask == gamepad_menu) return false;
    GamepadBindings candidate = bindings;
    if (!set_gamepad_binding(candidate, action, mask)) return false;
    if (!valid_gamepad_bindings(candidate)) return false;
    bindings = candidate;
    return true;
}

inline std::string encode_gamepad_profile(const GamepadBindings& bindings) {
    if (!valid_gamepad_bindings(bindings)) return {};
    std::ostringstream body;
    body.imbue(std::locale::classic());
    body << "TCINPUT\t1\n";
    for (const auto& [name, mask] : std::array<std::pair<std::string_view, std::uint16_t>, 6>{{
             {"jump", bindings.jump}, {"crouch", bindings.crouch}, {"crawl", bindings.crawl},
             {"ui_confirm", bindings.ui_confirm}, {"ui_cancel", bindings.ui_cancel},
             {"ui_menu", bindings.ui_menu}}}) {
        if (gamepad_button_name(mask) == "UNKNOWN") return {};
        body << name << '\t' << gamepad_button_name(mask) << '\n';
    }
    const std::string payload = body.str();
    std::uint64_t checksum = 1469598103934665603ULL;
    for (const unsigned char byte : payload) checksum = (checksum ^ byte) * 1099511628211ULL;
    body << "CHECKSUM\t" << std::hex << std::setw(16) << std::setfill('0') << checksum << '\n';
    return body.str();
}

inline bool decode_gamepad_profile(std::string_view encoded, GamepadBindings& bindings) {
    const auto footer_start = encoded.rfind("CHECKSUM\t");
    if (footer_start == std::string_view::npos || footer_start == 0 ||
        encoded[footer_start - 1] != '\n' || encoded.size() != footer_start + 26 ||
        encoded.back() != '\n') return false;
    std::uint64_t checksum = 1469598103934665603ULL;
    for (std::size_t index = 0; index < footer_start; ++index)
        checksum = (checksum ^ static_cast<unsigned char>(encoded[index])) * 1099511628211ULL;
    std::ostringstream expected;
    expected.imbue(std::locale::classic());
    expected << std::hex << std::setw(16) << std::setfill('0') << checksum;
    if (encoded.substr(footer_start + 9, 16) != expected.str()) return false;
    std::istringstream stream{std::string(encoded.substr(0, footer_start))};
    std::string line;
    if (!std::getline(stream, line) || line != "TCINPUT\t1") return false;
    GamepadBindings candidate = bindings;
    for (const auto name : std::array<std::string_view, 6>{
             "jump", "crouch", "crawl", "ui_confirm", "ui_cancel", "ui_menu"}) {
        if (!std::getline(stream, line)) return false;
        const auto separator = line.find('\t');
        if (separator == std::string::npos || line.substr(0, separator) != name ||
            !set_gamepad_binding(candidate, name, gamepad_button_mask(line.substr(separator + 1))))
            return false;
    }
    if (std::getline(stream, line) || !valid_gamepad_bindings(candidate)) return false;
    bindings = candidate;
    return true;
}

inline GamepadActions map_gamepad(GamepadSnapshot snapshot, const GamepadBindings& bindings = {}) {
    if (!snapshot.connected) return {};
    GamepadActions actions{};
    actions.connected = true;
    const float x = static_cast<float>(snapshot.left_x);
    const float y = static_cast<float>(snapshot.left_y);
    const float magnitude = std::sqrt(x * x + y * y);
    if (magnitude > gamepad_left_deadzone) {
        const float strength = std::clamp(
            (std::min(magnitude, 32767.0F) - gamepad_left_deadzone) /
            (32767.0F - gamepad_left_deadzone), 0.0F, 1.0F);
        actions.move_x = x / magnitude * strength;
        actions.move_y = y / magnitude * strength;
    }
    if (snapshot.buttons & (gamepad_dpad_left | gamepad_dpad_right)) {
        actions.move_x = (snapshot.buttons & gamepad_dpad_right ? 1.0F : 0.0F) -
                         (snapshot.buttons & gamepad_dpad_left ? 1.0F : 0.0F);
    }
    if (snapshot.buttons & (gamepad_dpad_up | gamepad_dpad_down)) {
        actions.move_y = (snapshot.buttons & gamepad_dpad_up ? 1.0F : 0.0F) -
                         (snapshot.buttons & gamepad_dpad_down ? 1.0F : 0.0F);
    }
    actions.jump = (snapshot.buttons & bindings.jump) != 0;
    actions.crouch = (snapshot.buttons & bindings.crouch) != 0;
    actions.crawl = (snapshot.buttons & bindings.crawl) != 0;
    return actions;
}

}  // namespace tc::runtime

#endif
