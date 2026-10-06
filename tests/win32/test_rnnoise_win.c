/* Minimal rnnoise.dll smoke test (mirrors RNNoiseEngine's ctypes usage).
 *
 * Loads rnnoise.dll from the exe directory, creates a state with the
 * built-in model (NULL), pushes sine + silence frames through
 * rnnoise_process_frame, and sanity-checks the results.
 * Returns 0 on PASS, non-zero on FAIL.
 *
 * Build and run (Linux with mingw + Wine, e.g. Heroic's GE-Proton wine):
 *   x86_64-w64-mingw32-gcc -O2 -o test_rnnoise.exe test_rnnoise_win.c
 *   cp ../../stream_denoiser/native/rnnoise.dll .
 *   WINEPREFIX=/tmp/wineprefix WINEDEBUG=-all wine test_rnnoise.exe
 */
#include <math.h>
#include <stdio.h>
#include <windows.h>

typedef int (*get_frame_size_fn)(void);
typedef void *(*create_fn)(void *);
typedef void (*destroy_fn)(void *);
typedef float (*process_frame_fn)(void *, float *, const float *);

#define CHECK(cond, msg)                                  \
    do {                                                  \
        if (!(cond)) { printf("FAIL: %s\n", msg); rc = 1; \
                       goto done; }                       \
    } while (0)

int main(void) {
    int rc = 0;
    HMODULE lib = LoadLibraryA("rnnoise.dll");
    CHECK(lib != NULL, "LoadLibraryA(rnnoise.dll)");

    get_frame_size_fn get_frame_size =
        (get_frame_size_fn)(void *)GetProcAddress(lib, "rnnoise_get_frame_size");
    create_fn create = (create_fn)(void *)GetProcAddress(lib, "rnnoise_create");
    destroy_fn destroy = (destroy_fn)(void *)GetProcAddress(lib, "rnnoise_destroy");
    process_frame_fn process_frame =
        (process_frame_fn)(void *)GetProcAddress(lib, "rnnoise_process_frame");
    CHECK(get_frame_size && create && destroy && process_frame,
          "GetProcAddress for all 4 API functions");

    int n = get_frame_size();
    printf("frame_size=%d\n", n);
    CHECK(n == 480, "frame size is 480");

    void *st = create(NULL);
    CHECK(st != NULL, "rnnoise_create(NULL)");

    static float in[480], out[480];
    for (int f = 0; f < 20; f++) {
        int silent = f >= 10;
        for (int i = 0; i < n; i++) {
            /* 16-bit range samples, like the Python engine feeds them. */
            in[i] = silent ? 0.0f
                    : 10000.0f * sinf(2.0f * 3.14159265f * 440.0f *
                                      (f * n + i) / 48000.0f);
        }
        float prob = process_frame(st, out, in);
        CHECK(prob >= 0.0f && prob <= 1.0f, "speech prob in [0, 1]");
        for (int i = 0; i < n; i++) {
            CHECK(out[i] == out[i] && out[i] < 1e10f && out[i] > -1e10f,
                  "output finite");
        }
        if (f == 0) printf("first_frame_prob=%f\n", prob);
    }

    destroy(st);
    printf("PASS\n");
done:
    if (lib) FreeLibrary(lib);
    return rc;
}
