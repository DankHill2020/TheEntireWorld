#ifndef TC_AUDIO_MIXER_H
#define TC_AUDIO_MIXER_H

#include <cstddef>
#include <filesystem>
#include <memory>
#include <string>

namespace tc::runtime {

class AudioMixer {
public:
    AudioMixer();
    ~AudioMixer();
    AudioMixer(const AudioMixer&) = delete;
    AudioMixer& operator=(const AudioMixer&) = delete;

    bool initialize(std::string& error);
    bool play(const std::filesystem::path& path, float volume, std::string& error);
    void update() noexcept;
    void stop_all() noexcept;
    [[nodiscard]] std::size_t active_voices() const noexcept;

private:
    class Implementation;
    std::unique_ptr<Implementation> implementation_;
};

}  // namespace tc::runtime

#endif
