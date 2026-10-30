"""Z-A must import its physical window, never reuse the preallocated Zelda heap (no GPU or game files needed)."""
import os
from pathlib import Path
import shlex
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
source = (root / 'runtime/nvn/vulkan/exec.c').read_text()
prepare = source[source.index('void backend_guest_heap_prepare('):source.index('\nstatic uint64_t gmem_tried;')]
info = source[source.index('static VkDescriptorBufferInfo gmem_info(void) {'):source.index('\n// ---- the guest heap for shaders in chunks')]
main = (root / 'runtime/main.c').read_text()
assert 'backend_guest_heap_prepare(root);' in main

harness = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define LOG(...) printf(__VA_ARGS__)
#define ENV getenv
#define MB (1ull << 20)
typedef struct { int buffer; uint64_t offset, range; } VkDescriptorBufferInfo;
typedef struct { int buf; uint64_t off; } VkSpan;
static struct { int dev, host_import; struct { uint32_t vendorID; } props; } g_vk = {1, 1, {0x1002}};
static bool gmem_userptr, gmem_dmabuf, gc_lazy;
static int gmem_buf, driver_calls, import_calls, tracking_calls;
static uint64_t gmem_size, gmem_lo, gmem_window = 256 * MB;
static const uint64_t gwin_max = 3221 * MB;
static const char *selected;
static bool game_files_are_la(const char *dir) {
    assert(!strcmp(dir, selected));
    return !strcmp(dir, "/games/zelda");
}
static bool guest_heap_dmabuf(void) {
    driver_calls++;
    gmem_dmabuf = true;
    gmem_buf = 1;
    gmem_size = 3328 * MB;
    return true;
}
static uint32_t gmem_chunk_shift(void) { return 0; }
static void plat_write_tracking_off(const char *why) { assert(why && *why); tracking_calls++; }
static uint64_t gwin_want(void) { return gwin_max; }
static void gmem_window_get(uint64_t *lo, uint64_t *len) {
    *lo = gwin_max - gmem_window;
    *len = gmem_window;
}
static bool gmem_import(uint64_t lo, uint64_t size) {
    assert(lo == gwin_max - gmem_window && size == gmem_window);
    import_calls++;
    gmem_buf = 2;
    gmem_lo = lo;
    gmem_size = size;
    return true;
}
static VkSpan vk_transient_copy(const void *p, uint64_t size, uint64_t align) {
    (void)p; (void)size; (void)align;
    assert(!"shader memory must not fall back to zeros");
    return (VkSpan){0};
}
''' + prepare + info + r'''
int main(void) {
    selected = "/custom/game-root/za";
    backend_guest_heap_prepare(selected);
    assert(driver_calls == 0 && !gmem_dmabuf && gmem_userptr);
    assert(tracking_calls == 1);
    VkDescriptorBufferInfo bi = gmem_info();
    assert(import_calls == 1 && bi.buffer == 2 && bi.range == 256 * MB);
    bi = gmem_info();
    assert(import_calls == 1 && bi.buffer == 2);

    gmem_buf = 0; gmem_size = gmem_lo = 0; gmem_userptr = false;
    selected = "/games/zelda";
    backend_guest_heap_prepare(selected);
    assert(driver_calls == 1 && gmem_dmabuf && !gmem_userptr && gmem_buf == 1);
    assert(tracking_calls == 2);
    puts("PASS: Z-A imports its own physical window; Zelda retains its driver heap");
}
'''
with tempfile.TemporaryDirectory(prefix='gmem-game-window-') as temporary:
    temporary = Path(temporary)
    cfile = temporary / 'window.c'
    cfile.write_text(harness)
    exe = temporary / 'window'
    subprocess.run(shlex.split(os.environ.get('CC', 'clang')) +
                   ['-D__linux__', '-std=gnu11', '-Wall', '-Wextra', '-Werror', str(cfile), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True, timeout=5)
