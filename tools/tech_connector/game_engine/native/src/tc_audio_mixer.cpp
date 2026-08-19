#include "tc_audio_mixer.h"

#include <algorithm>
#include <atomic>
#include <cstdint>
#include <fstream>
#include <mutex>
#include <unordered_set>
#include <vector>

#if defined(_WIN32)
#include <windows.h>
#include <xaudio2.h>
#endif

namespace tc::runtime {

#if defined(_WIN32)
namespace {

struct WaveData {
    WAVEFORMATEX format{};
    std::vector<std::uint8_t> samples;
};

std::uint32_t fourcc(char a, char b, char c, char d) {
    return static_cast<std::uint32_t>(static_cast<unsigned char>(a))
        | (static_cast<std::uint32_t>(static_cast<unsigned char>(b)) << 8U)
        | (static_cast<std::uint32_t>(static_cast<unsigned char>(c)) << 16U)
        | (static_cast<std::uint32_t>(static_cast<unsigned char>(d)) << 24U);
}

bool read_wave(const std::filesystem::path& path, WaveData& result, std::string& error) {
    std::ifstream stream(path, std::ios::binary);
    std::uint32_t riff = 0, size = 0, wave = 0;
    stream.read(reinterpret_cast<char*>(&riff), 4);
    stream.read(reinterpret_cast<char*>(&size), 4);
    stream.read(reinterpret_cast<char*>(&wave), 4);
    static_cast<void>(size);
    if (!stream || riff != fourcc('R', 'I', 'F', 'F') || wave != fourcc('W', 'A', 'V', 'E')) {
        error = "Audio asset is not a valid RIFF/WAVE file: " + path.string();
        return false;
    }
    bool has_format = false;
    bool has_samples = false;
    while (stream && (!has_format || !has_samples)) {
        std::uint32_t chunk = 0, chunk_size = 0;
        stream.read(reinterpret_cast<char*>(&chunk), 4);
        stream.read(reinterpret_cast<char*>(&chunk_size), 4);
        if (!stream || chunk_size > 512U * 1024U * 1024U) break;
        if (chunk == fourcc('f', 'm', 't', ' ')) {
            std::vector<std::uint8_t> bytes(chunk_size);
            stream.read(reinterpret_cast<char*>(bytes.data()), chunk_size);
            if (bytes.size() < 16) break;
            const std::size_t copy_size = std::min(bytes.size(), sizeof(WAVEFORMATEX));
            std::copy_n(bytes.data(), copy_size, reinterpret_cast<std::uint8_t*>(&result.format));
            has_format = true;
        } else if (chunk == fourcc('d', 'a', 't', 'a')) {
            result.samples.resize(chunk_size);
            stream.read(reinterpret_cast<char*>(result.samples.data()), chunk_size);
            has_samples = true;
        } else {
            stream.seekg(chunk_size, std::ios::cur);
        }
        if ((chunk_size & 1U) != 0U) stream.seekg(1, std::ios::cur);
    }
    if (!has_format || !has_samples || result.samples.empty()) {
        error = "WAVE file is missing a format or sample-data chunk: " + path.string();
        return false;
    }
    if (result.format.wFormatTag != WAVE_FORMAT_PCM && result.format.wFormatTag != WAVE_FORMAT_IEEE_FLOAT) {
        error = "TC Audio currently supports uncompressed PCM or IEEE-float WAV assets.";
        return false;
    }
    return true;
}

}  // namespace

class AudioMixer::Implementation {
public:
    struct Playback final : IXAudio2VoiceCallback {
        Implementation* owner{};
        IXAudio2SourceVoice* voice{};
        std::vector<std::uint8_t> samples;
        std::atomic_bool finished{false};

        void STDMETHODCALLTYPE OnVoiceProcessingPassStart(UINT32) override {}
        void STDMETHODCALLTYPE OnVoiceProcessingPassEnd() override {}
        void STDMETHODCALLTYPE OnStreamEnd() override {}
        void STDMETHODCALLTYPE OnBufferStart(void*) override {}
        void STDMETHODCALLTYPE OnLoopEnd(void*) override {}
        void STDMETHODCALLTYPE OnVoiceError(void*, HRESULT) override { finished.store(true); }
        void STDMETHODCALLTYPE OnBufferEnd(void*) override { finished.store(true); }
    };

    ~Implementation() { shutdown(); }

    bool initialize(std::string& error) {
        if (engine_ != nullptr) return true;
        HRESULT status = XAudio2Create(&engine_, 0, XAUDIO2_DEFAULT_PROCESSOR);
        if (FAILED(status)) {
            error = "XAudio2Create failed with HRESULT " + std::to_string(static_cast<unsigned long>(status));
            return false;
        }
        status = engine_->CreateMasteringVoice(&mastering_voice_);
        if (FAILED(status)) {
            engine_->Release();
            engine_ = nullptr;
            error = "XAudio2 mastering voice creation failed.";
            return false;
        }
        error.clear();
        return true;
    }

    bool play(const std::filesystem::path& path, float volume, std::string& error) {
        if (!initialize(error)) return false;
        WaveData wave;
        if (!read_wave(path, wave, error)) return false;
        auto* playback = new Playback();
        playback->owner = this;
        playback->samples = std::move(wave.samples);
        HRESULT status = engine_->CreateSourceVoice(&playback->voice, &wave.format, 0, XAUDIO2_DEFAULT_FREQ_RATIO, playback);
        if (FAILED(status)) {
            delete playback;
            error = "XAudio2 source voice creation failed.";
            return false;
        }
        playback->voice->SetVolume(std::clamp(volume, 0.0F, 4.0F));
        XAUDIO2_BUFFER buffer{};
        buffer.Flags = XAUDIO2_END_OF_STREAM;
        buffer.AudioBytes = static_cast<UINT32>(playback->samples.size());
        buffer.pAudioData = playback->samples.data();
        {
            std::lock_guard lock(mutex_);
            playbacks_.insert(playback);
        }
        status = playback->voice->SubmitSourceBuffer(&buffer);
        if (SUCCEEDED(status)) status = playback->voice->Start();
        if (FAILED(status)) {
            release(playback);
            error = "XAudio2 could not submit or start the audio buffer.";
            return false;
        }
        error.clear();
        return true;
    }

    void stop_all() noexcept {
        std::vector<Playback*> active;
        {
            std::lock_guard lock(mutex_);
            active.assign(playbacks_.begin(), playbacks_.end());
            playbacks_.clear();
        }
        for (auto* playback : active) {
            playback->owner = nullptr;
            if (playback->voice != nullptr) {
                playback->voice->Stop();
                playback->voice->DestroyVoice();
            }
            delete playback;
        }
    }

    void update() noexcept {
        std::vector<Playback*> completed;
        {
            std::lock_guard lock(mutex_);
            for (auto iterator = playbacks_.begin(); iterator != playbacks_.end();) {
                if ((*iterator)->finished.load()) {
                    completed.push_back(*iterator);
                    iterator = playbacks_.erase(iterator);
                } else {
                    ++iterator;
                }
            }
        }
        for (auto* playback : completed) {
            playback->owner = nullptr;
            if (playback->voice != nullptr) playback->voice->DestroyVoice();
            delete playback;
        }
    }

    [[nodiscard]] std::size_t active_voices() const noexcept {
        std::lock_guard lock(mutex_);
        return playbacks_.size();
    }

private:
    void release(Playback* playback) noexcept {
        {
            std::lock_guard lock(mutex_);
            if (playbacks_.erase(playback) == 0) return;
        }
        playback->owner = nullptr;
        if (playback->voice != nullptr) playback->voice->DestroyVoice();
        delete playback;
    }

    void shutdown() noexcept {
        stop_all();
        if (mastering_voice_ != nullptr) mastering_voice_->DestroyVoice();
        mastering_voice_ = nullptr;
        if (engine_ != nullptr) engine_->Release();
        engine_ = nullptr;
    }

    IXAudio2* engine_{nullptr};
    IXAudio2MasteringVoice* mastering_voice_{nullptr};
    mutable std::mutex mutex_;
    std::unordered_set<Playback*> playbacks_;
};

#else

class AudioMixer::Implementation {
public:
    bool initialize(std::string& error) { error = "Native audio is available on Windows builds."; return false; }
    bool play(const std::filesystem::path&, float, std::string& error) { return initialize(error); }
    void update() noexcept {}
    void stop_all() noexcept {}
    [[nodiscard]] std::size_t active_voices() const noexcept { return 0; }
};

#endif

AudioMixer::AudioMixer() : implementation_(std::make_unique<Implementation>()) {}
AudioMixer::~AudioMixer() = default;
bool AudioMixer::initialize(std::string& error) { return implementation_->initialize(error); }
bool AudioMixer::play(const std::filesystem::path& path, float volume, std::string& error) { return implementation_->play(path, volume, error); }
void AudioMixer::update() noexcept { implementation_->update(); }
void AudioMixer::stop_all() noexcept { implementation_->stop_all(); }
std::size_t AudioMixer::active_voices() const noexcept { return implementation_->active_voices(); }

}  // namespace tc::runtime
