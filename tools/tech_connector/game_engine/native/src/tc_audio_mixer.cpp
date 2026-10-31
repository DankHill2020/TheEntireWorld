#include "tc_audio_mixer.h"

#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <mutex>
#include <string_view>
#include <unordered_set>
#include <utility>
#include <vector>

#if defined(_WIN32)
#include <windows.h>
#include <mmdeviceapi.h>
#include <objbase.h>
#include <xaudio2.h>
#endif

namespace tc::runtime {

#if defined(_WIN32)
namespace {

std::string path_utf8(const std::filesystem::path& path) {
    const auto text = path.u8string();
    return std::string(text.begin(), text.end());
}

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
    if (!stream) {
        error = "Audio asset could not be opened: " + path_utf8(path);
        return false;
    }
    stream.seekg(0, std::ios::end);
    const auto file_size = stream.tellg();
    stream.seekg(0);
    std::uint32_t riff = 0, size = 0, wave = 0;
    stream.read(reinterpret_cast<char*>(&riff), 4);
    stream.read(reinterpret_cast<char*>(&size), 4);
    stream.read(reinterpret_cast<char*>(&wave), 4);
    if (!stream || riff != fourcc('R', 'I', 'F', 'F') || wave != fourcc('W', 'A', 'V', 'E') ||
        size < 4 || file_size < 12 || static_cast<std::uint64_t>(file_size) < 8ULL + size) {
        error = "Audio asset is not a valid RIFF/WAVE file: " + path_utf8(path);
        return false;
    }
    bool has_format = false;
    bool has_samples = false;
    const std::uint64_t riff_end = 8ULL + size;
    while (stream && (!has_format || !has_samples) &&
           static_cast<std::uint64_t>(stream.tellg()) + 8ULL <= riff_end) {
        std::uint32_t chunk = 0, chunk_size = 0;
        stream.read(reinterpret_cast<char*>(&chunk), 4);
        stream.read(reinterpret_cast<char*>(&chunk_size), 4);
        const std::uint64_t chunk_end = static_cast<std::uint64_t>(stream.tellg()) +
            chunk_size + (chunk_size & 1U);
        if (!stream || chunk_size > 512U * 1024U * 1024U || chunk_end > riff_end) break;
        if (chunk == fourcc('f', 'm', 't', ' ')) {
            if (chunk_size != 16 && chunk_size != 18) break;
            std::vector<std::uint8_t> bytes(chunk_size);
            stream.read(reinterpret_cast<char*>(bytes.data()), chunk_size);
            if (!stream || (chunk_size == 18 && (bytes[16] != 0 || bytes[17] != 0))) break;
            const std::size_t copy_size = std::min(bytes.size(), sizeof(WAVEFORMATEX));
            std::copy_n(bytes.data(), copy_size, reinterpret_cast<std::uint8_t*>(&result.format));
            has_format = true;
        } else if (chunk == fourcc('d', 'a', 't', 'a')) {
            result.samples.resize(chunk_size);
            stream.read(reinterpret_cast<char*>(result.samples.data()), chunk_size);
            if (!stream) break;
            has_samples = true;
        } else {
            stream.seekg(chunk_size, std::ios::cur);
        }
        if ((chunk_size & 1U) != 0U) stream.seekg(1, std::ios::cur);
    }
    if (!has_format || !has_samples || result.samples.empty()) {
        error = "WAVE file is missing a format or sample-data chunk: " + path_utf8(path);
        return false;
    }
    if (result.format.wFormatTag != WAVE_FORMAT_PCM && result.format.wFormatTag != WAVE_FORMAT_IEEE_FLOAT) {
        error = "TC Audio currently supports uncompressed PCM or IEEE-float WAV assets.";
        return false;
    }
    const auto& format = result.format;
    const bool valid_depth = format.wFormatTag == WAVE_FORMAT_IEEE_FLOAT
        ? format.wBitsPerSample == 32
        : (format.wBitsPerSample == 8 || format.wBitsPerSample == 16 ||
           format.wBitsPerSample == 24 || format.wBitsPerSample == 32);
    const std::uint32_t expected_align =
        static_cast<std::uint32_t>(format.nChannels) * (format.wBitsPerSample / 8U);
    if (format.nChannels == 0 || format.nChannels > 8 || format.nSamplesPerSec < 8000 ||
        format.nSamplesPerSec > 192000 || !valid_depth || format.nBlockAlign != expected_align ||
        format.nAvgBytesPerSec != format.nSamplesPerSec * expected_align ||
        result.samples.size() % expected_align != 0) {
        error = "WAVE file has an invalid PCM format or unaligned sample data: " + path_utf8(path);
        return false;
    }
    if (format.wFormatTag == WAVE_FORMAT_IEEE_FLOAT) {
        for (std::size_t offset = 0; offset < result.samples.size(); offset += sizeof(float)) {
            float sample = 0.0F;
            std::memcpy(&sample, result.samples.data() + offset, sizeof(sample));
            if (!std::isfinite(sample)) {
                error = "WAVE file contains a non-finite float sample: " + path_utf8(path);
                return false;
            }
        }
    }
    error.clear();
    return true;
}

}  // namespace

bool validate_wave_asset(const std::filesystem::path& path, std::string& error) {
    WaveData wave;
    return read_wave(path, wave, error);
}

class AudioMixer::Implementation : public IXAudio2EngineCallback {
public:
    class EndpointNotification final : public IMMNotificationClient {
    public:
        EndpointNotification(Implementation* owner, std::wstring output_id)
            : owner_(owner), output_id_(std::move(output_id)) {}

        HRESULT STDMETHODCALLTYPE QueryInterface(REFIID id, void** result) override {
            if (result == nullptr) return E_POINTER;
            *result = nullptr;
            if (IsEqualIID(id, IID_IUnknown) || IsEqualIID(id, __uuidof(IMMNotificationClient))) {
                *result = static_cast<IMMNotificationClient*>(this);
                AddRef();
                return S_OK;
            }
            return E_NOINTERFACE;
        }
        ULONG STDMETHODCALLTYPE AddRef() override { return ++references_; }
        ULONG STDMETHODCALLTYPE Release() override {
            const ULONG remaining = --references_;
            if (remaining == 0) delete this;
            return remaining;
        }
        HRESULT STDMETHODCALLTYPE OnDeviceStateChanged(LPCWSTR id, DWORD state) override {
            if (state != DEVICE_STATE_ACTIVE) restart_if_current_output(id);
            return S_OK;
        }
        HRESULT STDMETHODCALLTYPE OnDeviceAdded(LPCWSTR) override { return S_OK; }
        HRESULT STDMETHODCALLTYPE OnDeviceRemoved(LPCWSTR id) override {
            restart_if_current_output(id);
            return S_OK;
        }
        HRESULT STDMETHODCALLTYPE OnDefaultDeviceChanged(EDataFlow flow, ERole role, LPCWSTR) override {
            if (flow == eRender && (role == eConsole || role == eMultimedia)) {
                request_restart();
            }
            return S_OK;
        }
        HRESULT STDMETHODCALLTYPE OnPropertyValueChanged(LPCWSTR, const PROPERTYKEY) override { return S_OK; }

        void detach() noexcept {
            std::lock_guard<std::mutex> lock(owner_mutex_);
            owner_ = nullptr;
        }

    private:
        void request_restart() noexcept {
            std::lock_guard<std::mutex> lock(owner_mutex_);
            if (owner_ != nullptr) owner_->request_output_restart();
        }
        void restart_if_current_output(LPCWSTR id) noexcept {
            if (id != nullptr && !output_id_.empty() &&
                std::wstring_view(id) == std::wstring_view(output_id_)) {
                request_restart();
            }
        }
        std::atomic<ULONG> references_{1};
        std::mutex owner_mutex_;
        Implementation* owner_;
        const std::wstring output_id_;
    };

    void STDMETHODCALLTYPE OnProcessingPassStart() override {}
    void STDMETHODCALLTYPE OnProcessingPassEnd() override {}
    void STDMETHODCALLTYPE OnCriticalError(HRESULT status) override {
        critical_error_.store(status);
    }

    struct Playback final : IXAudio2VoiceCallback {
        Implementation* owner{};
        IXAudio2SourceVoice* voice{};
        std::vector<std::uint8_t> samples;
        std::string source;
        std::atomic_bool finished{false};
        std::atomic_bool failed{false};
        std::atomic<HRESULT> failure_status{S_OK};

        void STDMETHODCALLTYPE OnVoiceProcessingPassStart(UINT32) override {}
        void STDMETHODCALLTYPE OnVoiceProcessingPassEnd() override {}
        void STDMETHODCALLTYPE OnStreamEnd() override {}
        void STDMETHODCALLTYPE OnBufferStart(void*) override {}
        void STDMETHODCALLTYPE OnLoopEnd(void*) override {}
        void STDMETHODCALLTYPE OnVoiceError(void*, HRESULT status) override {
            failure_status.store(status);
            failed.store(true);
            finished.store(true);
        }
        void STDMETHODCALLTYPE OnBufferEnd(void*) override { finished.store(true); }
    };

    ~Implementation() { shutdown(); }

    bool initialize(std::string& error) {
        if (restart_requested_.load() || FAILED(critical_error_.load())) update();
        if (engine_ != nullptr) { error.clear(); return true; }
        if (!com_initialized_) {
            const HRESULT com_status = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
            if (FAILED(com_status) && com_status != RPC_E_CHANGED_MODE) {
                error = "COM initialization for XAudio2 failed with HRESULT " +
                    std::to_string(static_cast<unsigned long>(com_status));
                return false;
            }
            // A host-owned STA is already initialized; only balance our own
            // successful CoInitializeEx calls during shutdown.
            com_owned_ = SUCCEEDED(com_status);
            com_initialized_ = true;
        }
        HRESULT status = XAudio2Create(&engine_, 0, XAUDIO2_DEFAULT_PROCESSOR);
        if (FAILED(status)) {
            shutdown();
            error = "XAudio2Create failed with HRESULT " + std::to_string(static_cast<unsigned long>(status));
            return false;
        }
        status = engine_->RegisterForCallbacks(this);
        if (FAILED(status)) {
            shutdown();
            error = "XAudio2 engine callback registration failed with HRESULT " +
                std::to_string(static_cast<unsigned long>(status));
            return false;
        }
        callback_registered_ = true;
        status = engine_->CreateMasteringVoice(&mastering_voice_);
        if (FAILED(status)) {
            shutdown();
            error = "XAudio2 mastering voice creation failed with HRESULT " +
                std::to_string(static_cast<unsigned long>(status));
            return false;
        }
        status = mastering_voice_->SetVolume(muted_ ? 0.0F : 1.0F);
        if (FAILED(status)) {
            shutdown();
            error = "XAudio2 could not restore the saved mastering volume; HRESULT " +
                std::to_string(static_cast<unsigned long>(status));
            return false;
        }
        // A default-endpoint switch need not raise an XAudio2 critical error.
        // The COM callback only requests a restart; teardown stays on update().
        IMMDeviceEnumerator* enumerator = nullptr;
        if (SUCCEEDED(CoCreateInstance(__uuidof(MMDeviceEnumerator), nullptr,
                                       CLSCTX_INPROC_SERVER, __uuidof(IMMDeviceEnumerator),
                                       reinterpret_cast<void**>(&enumerator)))) {
            std::wstring output_id;
            IMMDevice* output = nullptr;
            if (SUCCEEDED(enumerator->GetDefaultAudioEndpoint(eRender, eConsole, &output))) {
                LPWSTR id = nullptr;
                if (SUCCEEDED(output->GetId(&id)) && id != nullptr) output_id = id;
                if (id != nullptr) CoTaskMemFree(id);
                output->Release();
            }
            auto* notification = new EndpointNotification(this, std::move(output_id));
            if (SUCCEEDED(enumerator->RegisterEndpointNotificationCallback(notification))) {
                endpoint_enumerator_ = enumerator;
                endpoint_notification_ = notification;
            } else {
                notification->Release();
                enumerator->Release();
            }
        }
        if (suspended_) engine_->StopEngine();
        error.clear();
        return true;
    }

    bool play(const std::filesystem::path& path, float volume, std::string& error) {
        if (!std::isfinite(volume)) {
            error = "Audio playback volume must be finite.";
            return false;
        }
        WaveData wave;
        if (!read_wave(path, wave, error)) return false;
        if (!initialize(error)) return false;
        auto* playback = new Playback();
        playback->owner = this;
        playback->samples = std::move(wave.samples);
        playback->source = path_utf8(path);
        HRESULT status = engine_->CreateSourceVoice(&playback->voice, &wave.format, 0, XAUDIO2_DEFAULT_FREQ_RATIO, playback);
        if (FAILED(status)) {
            delete playback;
            error = "XAudio2 source voice creation failed with HRESULT " +
                std::to_string(static_cast<unsigned long>(status));
            return false;
        }
        status = playback->voice->SetVolume(std::clamp(volume, 0.0F, 4.0F));
        if (FAILED(status)) {
            playback->voice->DestroyVoice();
            delete playback;
            error = "XAudio2 could not set source voice volume; HRESULT " +
                std::to_string(static_cast<unsigned long>(status));
            return false;
        }
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
            error = "XAudio2 could not submit or start the audio buffer; HRESULT " +
                std::to_string(static_cast<unsigned long>(status));
            return false;
        }
        error.clear();
        return true;
    }

    bool set_muted(bool muted, std::string& error) {
        // Preferences are meaningful even when no output device is available yet.
        // initialize() applies the desired level when a device appears later.
        if (mastering_voice_ != nullptr) {
            const HRESULT status = mastering_voice_->SetVolume(muted ? 0.0F : 1.0F);
            if (FAILED(status)) {
                error = "XAudio2 mastering voice volume change failed with HRESULT " +
                    std::to_string(static_cast<unsigned long>(status));
                return false;
            }
        }
        muted_ = muted;
        error.clear();
        return true;
    }

    bool set_suspended(bool suspended, std::string& error) {
        if (suspended == suspended_) { error.clear(); return true; }
        if (engine_ != nullptr) {
            if (suspended) engine_->StopEngine();
            else {
                const HRESULT status = engine_->StartEngine();
                if (FAILED(status)) {
                    suspended_ = false;
                    request_output_restart();
                    error = "XAudio2 could not resume after suspension; HRESULT " +
                        std::to_string(static_cast<unsigned long>(status));
                    return false;
                }
            }
        }
        suspended_ = suspended;
        error.clear();
        return true;
    }

    [[nodiscard]] bool muted() const noexcept { return muted_; }
    [[nodiscard]] bool suspended() const noexcept { return suspended_; }
    [[nodiscard]] bool monitoring_default_output() const noexcept {
        return endpoint_enumerator_ != nullptr && endpoint_notification_ != nullptr;
    }

    void request_output_restart() noexcept {
        // Use the same main-thread teardown path as an asynchronous engine
        // failure. No XAudio2 voice is destroyed from the calling thread.
        restart_requested_.store(true);
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
        const bool requested_restart = restart_requested_.exchange(false);
        const HRESULT engine_status = critical_error_.exchange(S_OK);
        const HRESULT critical_status = FAILED(engine_status) ? engine_status
            : (requested_restart ? E_ABORT : S_OK);
        if (FAILED(critical_status)) {
            std::lock_guard lock(mutex_);
            for (auto* playback : playbacks_) {
                playback->failure_status.store(critical_status);
                playback->failed.store(true);
                playback->finished.store(true);
            }
        }
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
            const bool failed = playback->failed.load();
            const AudioCompletion receipt{
                playback->source, !failed,
                failed ? (requested_restart && critical_status == E_ABORT
                    ? "XAudio2 output restart requested"
                    : "XAudio2 voice error HRESULT " +
                        std::to_string(static_cast<unsigned long>(playback->failure_status.load()))) : ""};
            delete playback;
            std::lock_guard lock(mutex_);
            completions_.push_back(receipt);
        }
        if (FAILED(critical_status)) shutdown();
    }

    [[nodiscard]] std::vector<AudioCompletion> take_completions() {
        std::lock_guard lock(mutex_);
        std::vector<AudioCompletion> result;
        result.swap(completions_);
        return result;
    }

    [[nodiscard]] std::size_t active_voices() const noexcept {
        std::lock_guard lock(mutex_);
        return playbacks_.size();
    }

    [[nodiscard]] std::uint64_t active_samples_played() const noexcept {
        std::lock_guard lock(mutex_);
        std::uint64_t total = 0;
        for (const auto* playback : playbacks_) {
            if (playback->voice == nullptr) continue;
            XAUDIO2_VOICE_STATE state{};
            playback->voice->GetState(&state);
            total += state.SamplesPlayed;
        }
        return total;
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
        if (endpoint_notification_ != nullptr) endpoint_notification_->detach();
        if (endpoint_enumerator_ != nullptr && endpoint_notification_ != nullptr)
            endpoint_enumerator_->UnregisterEndpointNotificationCallback(endpoint_notification_);
        if (endpoint_notification_ != nullptr) endpoint_notification_->Release();
        endpoint_notification_ = nullptr;
        if (endpoint_enumerator_ != nullptr) endpoint_enumerator_->Release();
        endpoint_enumerator_ = nullptr;
        if (engine_ != nullptr && callback_registered_) {
            engine_->UnregisterForCallbacks(this);
            callback_registered_ = false;
        }
        stop_all();
        if (mastering_voice_ != nullptr) mastering_voice_->DestroyVoice();
        mastering_voice_ = nullptr;
        if (engine_ != nullptr) engine_->Release();
        engine_ = nullptr;
        if (com_owned_) CoUninitialize();
        com_owned_ = false;
        com_initialized_ = false;
    }

    IXAudio2* engine_{nullptr};
    IMMDeviceEnumerator* endpoint_enumerator_{nullptr};
    EndpointNotification* endpoint_notification_{nullptr};
    IXAudio2MasteringVoice* mastering_voice_{nullptr};
    std::atomic<HRESULT> critical_error_{S_OK};
    std::atomic_bool restart_requested_{false};
    bool callback_registered_{false};
    bool com_initialized_{false};
    bool com_owned_{false};
    bool muted_{false};
    bool suspended_{false};
    mutable std::mutex mutex_;
    std::unordered_set<Playback*> playbacks_;
    std::vector<AudioCompletion> completions_;
};

#else

bool validate_wave_asset(const std::filesystem::path&, std::string& error) {
    error = "Native audio is available on Windows builds.";
    return false;
}

class AudioMixer::Implementation {
public:
    bool initialize(std::string& error) { error = "Native audio is available on Windows builds."; return false; }
    bool play(const std::filesystem::path&, float, std::string& error) { return initialize(error); }
    bool set_muted(bool, std::string& error) { return initialize(error); }
    bool set_suspended(bool, std::string& error) { return initialize(error); }
    [[nodiscard]] bool muted() const noexcept { return false; }
    [[nodiscard]] bool suspended() const noexcept { return false; }
    [[nodiscard]] bool monitoring_default_output() const noexcept { return false; }
    void request_output_restart() noexcept {}
    void update() noexcept {}
    [[nodiscard]] std::vector<AudioCompletion> take_completions() { return {}; }
    void stop_all() noexcept {}
    [[nodiscard]] std::size_t active_voices() const noexcept { return 0; }
    [[nodiscard]] std::uint64_t active_samples_played() const noexcept { return 0; }
};

#endif

AudioMixer::AudioMixer() : implementation_(std::make_unique<Implementation>()) {}
AudioMixer::~AudioMixer() = default;
bool AudioMixer::initialize(std::string& error) { return implementation_->initialize(error); }
bool AudioMixer::play(const std::filesystem::path& path, float volume, std::string& error) { return implementation_->play(path, volume, error); }
bool AudioMixer::set_muted(bool muted, std::string& error) { return implementation_->set_muted(muted, error); }
bool AudioMixer::set_suspended(bool suspended, std::string& error) { return implementation_->set_suspended(suspended, error); }
bool AudioMixer::muted() const noexcept { return implementation_->muted(); }
bool AudioMixer::suspended() const noexcept { return implementation_->suspended(); }
bool AudioMixer::monitoring_default_output() const noexcept {
    return implementation_->monitoring_default_output();
}
void AudioMixer::request_output_restart() noexcept { implementation_->request_output_restart(); }
void AudioMixer::update() noexcept { implementation_->update(); }
std::vector<AudioCompletion> AudioMixer::take_completions() { return implementation_->take_completions(); }
void AudioMixer::stop_all() noexcept { implementation_->stop_all(); }
std::size_t AudioMixer::active_voices() const noexcept { return implementation_->active_voices(); }
std::uint64_t AudioMixer::active_samples_played() const noexcept { return implementation_->active_samples_played(); }

}  // namespace tc::runtime
