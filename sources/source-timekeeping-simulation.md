---
title: 仿真器中的高精度时间keeping — TSC、rdtsc、clock_gettime 与虚拟时钟
description: 系统分析 x86 TSC（Time Stamp Counter）指令在仿真器/虚拟机中的时间测量原理、Invariant TSC 与跨核一致性、clock_gettime(CLOCK_MONOTONIC) 的 vDSO 加速机制、以及 QEMU icount 虚拟时钟的确定性时间模型。为 RTL 仿真器多线程化中的时间基准选择提供决策框架。
source_url: "https://www.qemu.org/docs/master/devel/replay.html"
source_type: "doc"  # github-pr, github-issue, blog, doc, paper, competition
author: "QEMU Project / Linux Kernel / LTTng / PostgreSQL / 社区"
date: "2010-2026"
tags: ["rdtsc", "TSC", "invariant-tsc", "clock_gettime", "CLOCK_MONOTONIC", "high-resolution-timer", "timekeeping", "simulation", "QEMU", "icount", "vDSO"]
keywords: ["rdtsc simulation", "TSC frequency", "clock_gettime vDSO", "icount virtual clock", "deterministic time", "time stamp counter", "cross-CPU TSC sync", "HPET", "high resolution timer"]
capture_date: "2026-07-02"
---

# 仿真器中的高精度时间keeping — TSC、rdtsc、clock_gettime 与虚拟时钟

## 来源

- URL: https://www.qemu.org/docs/master/devel/replay.html
- 类型: doc
- 作者: QEMU Project
- 日期: 2026

- URL: https://lists.lttng.org/pipermail/lttng-dev/2010-July/014067.html
- 类型: mailing-list
- 作者: LTTng / Mathieu Desnoyers
- 日期: 2010-07

- URL: https://pganalyze.com/blog/5mins-postgres-19-reduced-timing-overhead-explain-analyze
- 类型: blog
- 作者: pganalyze (Lukas Fittl)
- 日期: 2026-04-11

- URL: https://aufather.wordpress.com/2010/09/08/high-performance-time-measuremen-in-linux/
- 类型: blog
- 作者: aufather
- 日期: 2010-09-08

- URL: https://blog.csdn.net/qq_33919450/article/details/137979409
- 类型: blog
- 作者: CSDN 博主
- 日期: 2024-04-22

## 摘要

在仿真器（RTL 仿真器、系统仿真器）中，时间测量是性能分析、调度决策和确定性重放的基础。x86 的 `rdtsc` 指令提供**亚纳秒级**分辨率（约 11.6 ns 一次读取），但受限于跨核一致性（non-Invariant TSC）和 CPU 频率缩放（SpeedStep/TurboBoost）。Linux 的 `clock_gettime(CLOCK_MONOTONIC)` 通过 vDSO 绕过系统调用，典型开销约 18.8 ns（Postgres 实测），但依赖于内核的时钟源选择（tsc / hpet / acpi_pm）。QEMU 的 `icount` 模式将时间基准从「墙上时间」彻底切换为「已执行指令数」，配合虚拟时钟（QEMU_CLOCK_VIRTUAL）实现完全确定性的时间推进，这是 record/replay 功能的核心。对于 RTL 仿真器，选择时间基准时必须在**精度、开销、确定性、跨核一致性**四者之间做权衡。

## 关键要点

- **`rdtsc` 的分辨率与开销**：`rdtsc` 在 x86 上读取 Time Stamp Counter，典型延迟约 11.6 ns（Postgres 19 实测），标准差约 1.66 ns；`rdtscp`（带序列化）约 16.9 ns；`clock_gettime(CLOCK_MONOTONIC)` 约 18.8 ns（通过 vDSO 路径）。对于仿真器内部循环的高频计时，`rdtsc` 的低开销具有显著优势。
- **Invariant TSC 的判别**：现代 CPU 通过 CPUID leaf 0x80000007, EDX[8]（Invariant TSC）保证 TSC 在所有 P-State/C-State 下频率不变。若该标志未设置，则 TSC 会随 CPU 频率缩放而变化，不能直接换算为纳秒时间。在多核系统上，还需通过 `cpuid` 或内核日志检查 `constant_tsc` 和 `nonstop_tsc`。
- **跨核 TSC 一致性风险**：即使 `rdtsc` 本身可用，SMP 系统上不同物理核的 TSC 可能存在偏移（skew）。如果仿真器线程被调度器迁移到不同 CPU，两次 `rdtsc` 读数可能来自不同步的计数器。解决方案是将线程绑定到固定 CPU（`sched_setaffinity` / `taskset`），或使用 `rdtscp`（隐含 `cpuid` 序列化屏障）+ 内核同步后的 TSC。
- **`clock_gettime` 的 vDSO 加速**：Linux 内核的 vDSO（virtual dynamic shared object）将 `clock_gettime` 的常用路径（CLOCK_REALTIME、CLOCK_MONOTONIC）直接映射到用户空间，避免真实的 `syscall` 陷入。vDSO 内部优先使用 TSC（如果内核判定为可靠时钟源），通过 seqlock 同步内核时间校准数据，性能接近纯 `rdtsc`。
- **QEMU 的四种时钟模型**：QEMU 内部区分 Real time clock（真实时间，不影响 guest 状态）、Virtual clock（仿真期间运行，icount 模式下完全由指令计数计算，确定性）、Host clock（模拟真实时间源，如 RTC 芯片，非确定性）、Virtual real time clock（VM 睡眠时推进虚拟时间，非确定性）。**只有 Virtual clock 在 icount 模式下是确定性的**。
- **icount 与虚拟时间的换算**：`shift` 参数定义 `2^shift` 条指令 = 1 ns 虚拟时间。`shift=auto` 让 QEMU 动态调整以匹配主机性能（初始猜测 125 MIPS，即 `shift=3`）。`icount` 模式使虚拟时间完全脱离主机时间，允许「主机暂停 1 秒，虚拟机只前进少量指令」的精确时间控制。

## 对 RTL 仿真器多线程化的启示

- **时间基准的「绑定即正确」原则**：如果 RTL 仿真器（如 Verilator）使用 `rdtsc` 做 cycle-accurate 的延迟测量，必须确保采样线程固定在单一 CPU 上运行。否则跨核 TSC 不同步会导致计时噪声掩盖真实的性能特征。推荐在初始化时调用 `sched_setaffinity` 将主线程绑定到已验证具有 Invariant TSC 的 CPU。
- **确定性仿真中的「冻结时间」**：在需要**可重复复现**的 RTL 仿真中（如 CI/CD 回归测试），不应依赖 `clock_gettime(CLOCK_MONOTONIC)` 或 `rdtsc` 作为仿真进度的时间源，因为主机负载变化会影响它们的绝对值。应当采用类似 QEMU `icount` 的「指令计数时间」：以仿真模型执行的逻辑 cycle 数或 eval 批次数为时间基准，完全脱离主机时间。
- **性能剖析的混合策略**：在 profiling 场景（非确定性可接受），可以采用 `rdtscp`（带序列化）+ `cpuid` 检测 Invariant TSC 的组合；在确定性场景（如 record/replay 辅助调试），采用逻辑 cycle 计数。两者不应混用——混用会导致重放时 profiler 数据不可复现。
- **vDSO 作为 `clock_gettime` 的透明加速**：如果仿真器代码已经使用 `clock_gettime(CLOCK_MONOTONIC)` 做粗略计时（如每秒打印一次吞吐量），无需修改代码即可获得 vDSO 加速。但要确保不混用 `CLOCK_REALTIME`（可能被 NTP 调整，非单调）。对于需要单调性保证的测量，`CLOCK_MONOTONIC` 是安全选择，但需注意 `CLOCK_MONOTONIC` 在 vDSO 中的实现仍然依赖 TSC，若 TSC 被判定为不可靠会 fallback 到 `syscall`。
- **QEMU icount 的借鉴**：RTL 仿真器若需要与外部模型（如 QEMU 系统模型）进行协同仿真，可以约定以「指令计数」或「固定时间片」作为同步点，而非真实时间。例如每仿真 10,000 个 cycle 与 QEMU 交换一次状态，这样无论主机性能如何，仿真逻辑的行为完全一致。

## 原文摘录

> rdtsc 平均延迟 242.2 ns，标准差 1.66 ns；clock_gettime 平均延迟 272.5 ns，标准差 2.34 ns。TSC 的稳定性（标准差更小）使其在高频采样场景下更有优势。—— LTTng 开发者邮件列表 (2010)

> Postgres 19 的 pg_test_timing 实测：RDTSC 约 11.6 ns，RDTSCP 约 16.9 ns，clock_gettime 约 18.8 ns。如果 TSC 以某种方式被模拟导致测量不稳定，则应显式设置 `timing_clock_source = system`。—— pganalyze Blog

> QEMU 的虚拟时钟（Virtual clock）在 icount 模式下完全由已执行指令计数计算，因此是完全确定性的，不需要记录到日志中。—— QEMU Record/Replay 文档

> 绑定进程到 CPU1 以消除双核 TSC 不匹配：用 `sched_setaffinity` 设置 `cpuMask = 2`，然后校准 `g_TicksPerNanoSec`（通过 `clock_gettime` 和 `rdtsc` 的联合采样）。—— aufather Blog

> Invariant TSC 的 CPUID 检测：leaf 0x80000007, EDX[8] = 1 表示 Invariant TSC 可用。CPUID leaf 0x15 的 EAX/EBX/ECX 可用于计算 TSC 频率。—— CSDN TSC Timer 实现

## 配置命令行示例

### 1. 检测 Invariant TSC 与 CPU 绑定（C/C++）

```cpp
#include <iostream>
#include <ctime>
#include <cstdint>
#include <sched.h>

#define BIT(nr) (1UL << (nr))

static inline uint64_t rdtsc(void) {
    unsigned long long low, high;
    asm volatile("rdtsc" : "=a"(low), "=d"(high));
    return low | (high << 32);
}

static inline bool isInvariantTSC(void) {
    uint32_t a = 0x80000007, b, c, d;
    asm volatile("cpuid"
                 : "=a"(a), "=b"(b), "=c"(c), "=d"(d)
                 : "0"(a), "1"(b), "2"(c), "3"(d));
    return (d & BIT(8)) != 0;  // EDX[8] = Invariant TSC
}

static inline uint64_t tscFreq(void) {
    uint32_t a = 0x15, b, c, d;
    asm volatile("cpuid"
                 : "=a"(a), "=b"(b), "=c"(c), "=d"(d)
                 : "0"(a), "1"(b), "2"(c), "3"(d));
    if (c != 0) return (uint64_t)b / a * c;
    return 0;  // fallback
}

static void bindToCpu(int cpu) {
    cpu_set_t set;
    CPU_ZERO(&set);
    CPU_SET(cpu, &set);
    if (sched_setaffinity(0, sizeof(set), &set) != 0) {
        perror("sched_setaffinity");
    }
}

static double calibrateTicksPerNs() {
    struct timespec ts_start, ts_end;
    uint64_t tsc_start, tsc_end;
    
    clock_gettime(CLOCK_MONOTONIC, &ts_start);
    tsc_start = rdtsc();
    for (volatile uint64_t i = 0; i < 100000000ULL; i++);  // CPU-intensive loop
    tsc_end = rdtsc();
    clock_gettime(CLOCK_MONOTONIC, &ts_end);
    
    uint64_t ns = (ts_end.tv_sec - ts_start.tv_sec) * 1000000000ULL
                + (ts_end.tv_nsec - ts_start.tv_nsec);
    return static_cast<double>(tsc_end - tsc_start) / static_cast<double>(ns);
}

int main() {
    if (!isInvariantTSC()) {
        fprintf(stderr, "警告：非 Invariant TSC，rdtsc 可能随频率变化\n");
    }
    
    bindToCpu(1);  // 绑定到 CPU 1，避免跨核 TSC 不同步
    double ticksPerNs = calibrateTicksPerNs();
    uint64_t freq = tscFreq();
    
    printf("TSC 频率: %lu Hz\n", freq);
    printf("校准值: %.3f ticks/ns\n", ticksPerNs);
    
    uint64_t t0 = rdtsc();
    // ... 仿真器核心循环 ...
    uint64_t t1 = rdtsc();
    double elapsed_ns = (t1 - t0) / ticksPerNs;
    printf("耗时: %.0f ns\n", elapsed_ns);
    
    return 0;
}
```

### 2. 使用 `rdtscp` 替代 `rdtsc`（带序列化与 CPU ID）

```cpp
#include <stdint.h>

static inline uint64_t rdtscp(uint32_t *aux) {
    uint64_t rax, rdx;
    asm volatile("rdtscp\n"
                 "shl $32, %%rdx\n"
                 "or %%rdx, %0\n"
                 "lfence"
                 : "=a"(rax), "=d"(rdx), "=c"(*aux)
                 :: "memory");
    return rax;
}

// 使用场景：必须确保前后指令严格按序执行时
uint64_t measure_critical_section() {
    uint32_t aux_start, aux_end;
    uint64_t start = rdtscp(&aux_start);
    // ... 被测量的代码 ...
    uint64_t end = rdtscp(&aux_end);
    
    if (aux_start != aux_end) {
        fprintf(stderr, "警告：测量期间线程被迁移到 CPU %u -> %u\n", aux_start, aux_end);
    }
    return end - start;
}
```

### 3. `clock_gettime` 与 `rdtsc` 混合校准（Linux）

```bash
# 查看当前系统使用的时钟源
cat /sys/devices/system/clocksource/clocksource0/current_clocksource
# 输出: tsc  (理想) 或 hpet / acpi_pm / jiffies

# 查看可用时钟源
cat /sys/devices/system/clocksource/clocksource0/available_clocksource

# 临时切换时钟源（需 root）
echo hpet | sudo tee /sys/devices/system/clocksource/clocksource0/current_clocksource

# 查看 vDSO 是否可用（内核 2.6.32+ 默认启用）
ldd /bin/date | grep linux-vdso
# 输出: linux-vdso.so.1 (0x00007fff...) 表示 vDSO 已加载

# 使用 perf 测试 gettime 开销
perf stat -e cycles,instructions ./test_gettime
```

### 4. QEMU icount 模式与虚拟时钟配置

```bash
# 基础 icount 模式（确定性执行，适合 record/replay）
qemu-system-x86_64 -icount shift=auto,rr=record

# 显式指定 shift（2^shift 条指令 = 1ns）
# shift=3 表示 8 条指令 = 1ns，即 125 MIPS 虚拟速度
qemu-system-x86_64 -icount shift=3

# 关闭 sleep（idle 时虚拟时间不推进，适合精确控制）
qemu-system-x86_64 -icount shift=auto,sleep=off

# 启用虚拟时钟的「warp」控制（VM idle 时虚拟时间是否按真实时间推进）
qemu-system-x86_64 -icount shift=auto,align=on

# 在 QEMU monitor 中查看虚拟时钟状态
(QEMU) info icount
```

### 5. 内核参数：TSC 与时钟源优化

```bash
# 在 /etc/default/grub 的 GRUB_CMDLINE_LINUX 中添加：
# 强制使用 TSC 作为时钟源，标记为可靠，禁用 NMI watchdog
clocksource=tsc tsc=reliable nmi_watchdog=0

# 对于非 Invariant TSC 的老旧 CPU，可能需要：
notsc  # 完全禁用 TSC，回退到 HPET

# 查看启动后的时钟源状态
dmesg | grep -i tsc
dmesg | grep -i clocksource

# 查看 CPU 的 TSC 相关 flags
cat /proc/cpuinfo | grep -o 'constant_tsc\|nonstop_tsc\|tsc_adjust\|tsc_deadline_timer\|rdtscp' | sort -u
```

## 相关链接

- [QEMU Docs: Record/Replay — Timers and Clocks](https://www.qemu.org/docs/master/devel/replay.html)
- [QEMU Docs: System Record/Replay](https://www.qemu.org/docs/master/system/replay.html)
- [LTTng-dev: UST clock rdtsc vs clock_gettime](https://lists.lttng.org/pipermail/lttng-dev/2010-July/014067.html)
- [Postgres 19: Reduced timing overhead with RDTSC](https://pganalyze.com/blog/5mins-postgres-19-reduced-timing-overhead-explain-analyze)
- [High Performance Time Measurement in Linux (RDTSC vs HPET)](https://aufather.wordpress.com/2010/09/08/high-performance-time-measuremen-in-linux/)
- [CSDN: TSC Timer 实现与 CPUID 检测](https://blog.csdn.net/qq_33919450/article/details/137979409)
- [GitHub: ZhongUncle/TSC_Timer](https://github.com/ZhongUncle/TSC_Timer)
- [Linux Kernel: Timekeeping](https://www.kernel.org/doc/html/latest/core-api/timekeeping.html)
- [Wikipedia: Time Stamp Counter](https://en.wikipedia.org/wiki/Time_Stamp_Counter)
