import micropython, time

@micropython.viper
def viper_loop(n: int) -> int:
    s: int = 0
    i: int = 0
    while i < n:
        s += i
        i += 1
    return s

@micropython.native
def native_loop(n: int) -> int:
    s = 0
    i = 0
    while i < n:
        s += i
        i += 1
    return s

def python_loop(n):
    s = 0
    i = 0
    while i < n:
        s += i
        i += 1
    return s

@micropython.viper
def viper_memcpy(dst: ptr8, src: ptr8, n: int):
    i: int = 0
    while i < n:
        dst[i] = src[i]
        i += 1

# pure-loop math test
N = 1_000_000

t0 = time.ticks_us()
viper_loop(N)
v = time.ticks_diff(time.ticks_us(), t0)

t0 = time.ticks_us()
native_loop(N)
nt = time.ticks_diff(time.ticks_us(), t0)

t0 = time.ticks_us()
python_loop(N)
p = time.ticks_diff(time.ticks_us(), t0)

print("loop math:")
print("  viper :", v, "us  (ratio %.1fx vs python)" % (p/max(v,1)))
print("  native:", nt, "us  (ratio %.1fx vs python)" % (p/max(nt,1)))
print("  python:", p, "us")

# memcpy bench: PSRAM-allocated bytearrays
src_psram = bytearray(b"x" * 9600)
dst_psram = bytearray(9600)

t0 = time.ticks_us()
viper_memcpy(dst_psram, src_psram, 9600)
mc_psram = time.ticks_diff(time.ticks_us(), t0)
print("memcpy 9600B (psram->psram):", mc_psram, "us = %.2f MB/s" % (9.6/(mc_psram/1e6)))

# Try forcing internal SRAM via small early alloc
src_sram = bytearray(b"y" * 9600)
dst_sram = bytearray(9600)
t0 = time.ticks_us()
viper_memcpy(dst_sram, src_sram, 9600)
mc_sram = time.ticks_diff(time.ticks_us(), t0)
print("memcpy 9600B (gc heap):", mc_sram, "us = %.2f MB/s" % (9.6/(mc_sram/1e6)))
