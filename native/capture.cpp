// Windows audio capture for Whistle. stdout: 44.1 kHz stereo signed PCM16 that
// stays continuous in real time (stalled sources are filled with silence).
// stdin: any byte stops capture. stderr: READY, then status/errors only.
//
//   capture.exe --app PID        audio from PID and its child processes
//   capture.exe --system PID     all system audio except PID and its children
//   capture.exe --mic            the default microphone
//   capture.exe PID              same as --app (earlier helper interface)
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
#include <cstring>
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

static void usage() {
    fprintf(stderr, "Usage: capture.exe --app PID | --system EXCLUDED_PID | --mic\n");
    exit(1);
}

static ComPtr<IAudioClient> process_loopback(DWORD pid, PROCESS_LOOPBACK_MODE mode) {
    AUDIOCLIENT_ACTIVATION_PARAMS params{};
    params.ActivationType = AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK;
    params.ProcessLoopbackParams.TargetProcessId = pid;
    params.ProcessLoopbackParams.ProcessLoopbackMode = mode;
    PROPVARIANT variant{};
    variant.vt = VT_BLOB;
    variant.blob.cbSize = sizeof(params);
    variant.blob.pBlobData = reinterpret_cast<BYTE*>(&params);
    auto callback = Make<Completion>();
    ComPtr<IActivateAudioInterfaceAsyncOperation> activation;
    check(ActivateAudioInterfaceAsync(VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK,
        __uuidof(IAudioClient), &variant, callback.Get(), &activation), "Activate process audio");
    if (WaitForSingleObject(callback->ready, 15000) != WAIT_OBJECT_0) {
        fprintf(stderr, "Windows did not activate process audio within 15 seconds.\n"); exit(2);
    }
    check(callback->result, "Activate process audio result");
    return callback->client;
}

static ComPtr<IAudioClient> microphone() {
    ComPtr<IMMDeviceEnumerator> devices;
    check(CoCreateInstance(__uuidof(MMDeviceEnumerator), nullptr, CLSCTX_ALL, IID_PPV_ARGS(&devices)),
        "Open audio devices");
    ComPtr<IMMDevice> device;
    HRESULT hr = devices->GetDefaultAudioEndpoint(eCapture, eConsole, &device);
    if (hr == HRESULT_FROM_WIN32(ERROR_NOT_FOUND)) {
        fprintf(stderr, "No microphone is connected.\n"); exit(2);
    }
    check(hr, "Find default microphone");
    ComPtr<IAudioClient> client;
    check(device->Activate(__uuidof(IAudioClient), CLSCTX_ALL, nullptr,
        reinterpret_cast<void**>(client.GetAddressOf())), "Open microphone");
    return client;
}

int main(int argc, char** argv) {
    enum { App, System, Mic } source = App;
    DWORD pid = 0;
    if (argc == 2 && strcmp(argv[1], "--mic") == 0) {
        source = Mic;
    } else if (argc == 3 && (strcmp(argv[1], "--app") == 0 || strcmp(argv[1], "--system") == 0)) {
        source = strcmp(argv[1], "--app") == 0 ? App : System;
        pid = strtoul(argv[2], nullptr, 10);
        if (!pid) usage();
    } else if (argc == 2 && strtoul(argv[1], nullptr, 10)) {
        pid = strtoul(argv[1], nullptr, 10);
    } else {
        usage();
    }
    check(CoInitializeEx(nullptr, COINIT_MULTITHREADED), "COM initialization");
    _setmode(_fileno(stdout), _O_BINARY);

    ComPtr<IAudioClient> client = source == Mic ? microphone()
        : process_loopback(pid, source == App ? PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE
                                              : PROCESS_LOOPBACK_MODE_EXCLUDE_TARGET_PROCESS_TREE);
    WAVEFORMATEX format{};
    format.wFormatTag = WAVE_FORMAT_PCM;
    format.nChannels = 2;
    format.nSamplesPerSec = 44100;
    format.wBitsPerSample = 16;
    format.nBlockAlign = 4;
    format.nAvgBytesPerSec = 176400;
    // Microphones have their own mix format; Windows converts to ours in shared mode.
    DWORD flags = AUDCLNT_STREAMFLAGS_EVENTCALLBACK | (source == Mic
        ? AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM | AUDCLNT_STREAMFLAGS_SRC_DEFAULT_QUALITY
        : AUDCLNT_STREAMFLAGS_LOOPBACK);
    HRESULT initialized = client->Initialize(AUDCLNT_SHAREMODE_SHARED, flags, 200000, 0, &format, nullptr);
    if (source == Mic && initialized == E_ACCESSDENIED) {
        fprintf(stderr, "Microphone access denied by Windows privacy settings.\n"); return 2;
    }
    check(initialized, source == Mic ? "Initialize microphone" : "Initialize process audio");
    HANDLE event = CreateEventW(nullptr, FALSE, FALSE, nullptr);
    check(client->SetEventHandle(event), "Set audio event");
    ComPtr<IAudioCaptureClient> capture;
    check(client->GetService(IID_PPV_ARGS(&capture)), "Get capture service");
    std::atomic<bool> stop{false};
    std::thread input([&] { getchar(); stop = true; });
    check(client->Start(), "Start capture");
    fprintf(stderr, "READY\n"); fflush(stderr);

    // Loopback delivers no packets while nothing plays. Fill such gaps with
    // silence so recordings keep real time and parallel streams stay aligned.
    LARGE_INTEGER frequency, started, now, lastPacket;
    QueryPerformanceFrequency(&frequency);
    QueryPerformanceCounter(&started);
    lastPacket = started;
    unsigned long long written = 0;
    std::vector<BYTE> silence;
    while (!stop) {
        WaitForSingleObject(event, 50);
        UINT32 frames = 0;
        check(capture->GetNextPacketSize(&frames), "Get audio packet");
        bool received = frames != 0;
        while (frames) {
            BYTE* data = nullptr; DWORD bufferFlags = 0;
            check(capture->GetBuffer(&data, &frames, &bufferFlags, nullptr, nullptr), "Read audio");
            size_t size = static_cast<size_t>(frames) * format.nBlockAlign;
            if (bufferFlags & AUDCLNT_BUFFERFLAGS_SILENT) {
                silence.assign(size, 0); data = silence.data();
            }
            const auto count = fwrite(data, 1, size, stdout);
            written += frames;
            check(capture->ReleaseBuffer(frames), "Release audio");
            if (count != size) { stop = true; break; }
            check(capture->GetNextPacketSize(&frames), "Get next packet");
        }
        QueryPerformanceCounter(&now);
        if (received) {
            lastPacket = now;
        } else if ((now.QuadPart - lastPacket.QuadPart) * 5 > frequency.QuadPart) {
            const unsigned long long expected = static_cast<unsigned long long>(
                (now.QuadPart - started.QuadPart) * 44100 / frequency.QuadPart);
            if (expected > written) {
                const size_t gap = static_cast<size_t>(expected - written) * format.nBlockAlign;
                silence.assign(gap, 0);
                if (fwrite(silence.data(), 1, gap, stdout) != gap) stop = true;
                written = expected;
            }
        }
        fflush(stdout);
    }
    client->Stop();
    input.join();
    CloseHandle(event);
    return 0;
}
