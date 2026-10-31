#ifndef TC_AUDIO_MIXER_H
#define TC_AUDIO_MIXER_H

#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <memory>
#include <string>
#include <vector>

namespace tc::runtime {

[[nodiscard]] bool validate_wave_asset(const std::filesystem::path& path, std::string& error);

struct AudioCompletion {
    std::string source;
    bool completed{false};
    std::string error;
};

class AudioMixer {
public:
    // Use initialize/play/update/destruction on the same owning thread.
    // XAudio2 callbacks only signal state and never use COM directly.
    AudioMixer();
    ~AudioMixer();
    AudioMixer(const AudioMixer&) = delete;
    AudioMixer& operator=(const AudioMixer&) = delete;

    bool initialize(std::string& error);
    bool play(const std::filesystem::path& path, float volume, std::string& error);
    bool set_muted(bool muted, std::string& error);
    // Pause the audio engine without discarding queued voices or playback cursors.
    bool set_suspended(bool suspended, std::string& error);
    [[nodiscard]] bool muted() const noexcept;
    [[nodiscard]] bool suspended() const noexcept;
    [[nodiscard]] bool monitoring_default_output() const noexcept;
    // Restart the output engine on the next update (for example, after an
    // explicit output-device change). Active voices receive failed receipts.
    void request_output_restart() noexcept;
    void update() noexcept;
    [[nodiscard]] std::vector<AudioCompletion> take_completions();
    void stop_all() noexcept;
    [[nodiscard]] std::size_t active_voices() const noexcept;
    // Diagnostic sum of active XAudio2 source-voice sample cursors.
    [[nodiscard]] std::uint64_t active_samples_played() const noexcept;

private:
    class Implementation;
    std::unique_ptr<Implementation> implementation_;
};

}  // namespace tc::runtime

#endif
