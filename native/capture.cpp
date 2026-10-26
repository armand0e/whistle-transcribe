// Windows process-tree loopback. stdout: 44.1 kHz stereo signed PCM16.
// stdin: any byte stops capture. stderr: status/errors only.
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <audioclient.h>
#include <audioclientactivationparams.h>
#include <mmdeviceapi.h>
#include <wrl.h>
#include <wrl/implements.h>
#include <io.h>
#include <fcntl.h>
#include <atomic>
#include <thread>
#include <cstdio>
#include <cstdlib>
#include <vector>
using namespace Microsoft::WRL;

class Completion final : public RuntimeClass<RuntimeClassFlags<ClassicCom>,
    FtmBase, IActivateAudioInterfaceCompletionHandler> {
public:
    HANDLE ready = CreateEventW(nullptr, TRUE, FALSE, nullptr);
    HRESULT result = E_PENDING;
    ComPtr<IAudioClient> client;
    ~Completion() { CloseHandle(ready); }
    STDMETHODIMP ActivateCompleted(IActivateAudioInterfaceAsyncOperation* op) override {
        ComPtr<IUnknown> object;
        HRESULT activation = E_FAIL;
        result = op->GetActivateResult(&activation, &object);
        if (SUCCEEDED(result)) result = activation;
        if (SUCCEEDED(result)) result = object.As(&client);
        SetEvent(ready);
        return S_OK;
    }
};

static void check(HRESULT hr, const char* operation) {
    if (FAILED(hr)) {
        fprintf(stderr, "%s failed (0x%08lX)\n", operation, (unsigned long)hr);
        exit(2);
    }
}

int main(int argc, char** argv) {
    if (argc != 2 || !strtoul(argv[1], nullptr, 10)) {
        fprintf(stderr, "Usage: capture.exe PID\n"); return 1;
    }
    check(CoInitializeEx(nullptr, COINIT_MULTITHREADED), "COM initialization");
    _setmode(_fileno(stdout), _O_BINARY);
    AUDIOCLIENT_ACTIVATION_PARAMS params{};
    params.ActivationType = AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK;
    params.ProcessLoopbackParams.TargetProcessId = strtoul(argv[1], nullptr, 10);
    params.ProcessLoopbackParams.ProcessLoopbackMode = PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE;
    PROPVARIANT variant{};
    variant.vt = VT_BLOB;
    variant.blob.cbSize = sizeof(params);
    variant.blob.pBlobData = reinterpret_cast<BYTE*>(&params);
    auto callback = Make<Completion>();
    ComPtr<IActivateAudioInterfaceAsyncOperation> activation;
    check(ActivateAudioInterfaceAsync(VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK,
        __uuidof(IAudioClient), &variant, callback.Get(), &activation), "Activate process audio");
    if (WaitForSingleObject(callback->ready, 15000) != WAIT_OBJECT_0) {
        fprintf(stderr, "Windows did not activate process audio within 15 seconds.\n"); return 2;
    }
    check(callback->result, "Activate process audio result");
    auto client = callback->client;
    WAVEFORMATEX format{};
    format.wFormatTag = WAVE_FORMAT_PCM;
    format.nChannels = 2;
    format.nSamplesPerSec = 44100;
    format.wBitsPerSample = 16;
    format.nBlockAlign = 4;
    format.nAvgBytesPerSec = 176400;
    check(client->Initialize(AUDCLNT_SHAREMODE_SHARED,
        AUDCLNT_STREAMFLAGS_LOOPBACK | AUDCLNT_STREAMFLAGS_EVENTCALLBACK,
        200000, 0, &format, nullptr), "Initialize process audio");
    HANDLE event = CreateEventW(nullptr, FALSE, FALSE, nullptr);
    check(client->SetEventHandle(event), "Set audio event");
    ComPtr<IAudioCaptureClient> capture;
    check(client->GetService(IID_PPV_ARGS(&capture)), "Get capture service");
    std::atomic<bool> stop{false};
    std::thread input([&] { getchar(); stop = true; });
    check(client->Start(), "Start capture");
    fprintf(stderr, "READY\n"); fflush(stderr);
    while (!stop) {
        WaitForSingleObject(event, 50);
        UINT32 frames = 0;
        check(capture->GetNextPacketSize(&frames), "Get audio packet");
        while (frames) {
            BYTE* data = nullptr; DWORD flags = 0;
            check(capture->GetBuffer(&data, &frames, &flags, nullptr, nullptr), "Read audio");
            size_t size = static_cast<size_t>(frames) * format.nBlockAlign;
            std::vector<BYTE> silence;
            if (flags & AUDCLNT_BUFFERFLAGS_SILENT) { silence.resize(size); data = silence.data(); }
            const auto written = fwrite(data, 1, size, stdout);
            check(capture->ReleaseBuffer(frames), "Release audio");
            if (written != size) { stop = true; break; }
            check(capture->GetNextPacketSize(&frames), "Get next packet");
        }
        fflush(stdout);
    }
    client->Stop();
    input.join();
    CloseHandle(event);
    return 0;
}
