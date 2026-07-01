---
title: 操作系统调度与多线程调试
description: 系统梳理 Linux 调度器隔离机制（isolcpus、cgroups v2 cpuset、taskset+chrt、PREEMPT_RT）、多线程调试工具链（GDB 线程断点、rr 记录重放、QEMU icount 确定性重放、死锁定位），以及高精度时间基准（rdtsc/rdtscp/clock_gettime）的选型与陷阱。为 RTL 仿真器多线程化提供可落地的 OS 层调优方案与部署前检查清单。
refs: [source-os-scheduling, source-multithread-debugging, source-timekeeping-simulation]
author: "Wiki 合成"
date: "2026-07-02"
tags: ["linux-scheduler", "multithread-debugging", "rdtsc", "rr", "GDB", "cpuset", "PREEMPT_RT", "isolcpus", "real-time", "checklist"]
---

# 操作系统调度与多线程调试

> **TL;DR**：RTL 仿真器多线程化后，OS 调度器是性能抖动的最大外部变量。本章给出从内核启动参数到线程绑定的完整 toolchain，以及调试 Heisenbug 的 record/replay 方案。核心原则：**绑定线程到 CPU → 隔离实时核 → 用 rdtscp 做微基准 → 用 rr 抓 race bug**。

---

## 1. Linux 调度器与 CPU 隔离

### 1.1 isolcpus 陷阱：仿真器线程的「亲和性盲区」

`isolcpus` 将指定 CPU 从 CFS 调度域中移除，但**仿真器线程（emulator threads）**在没有显式亲和性设置时，会被 CFS 调度器**全部集中到第一个可用、最低索引的 pCPU** 上运行。这会导致该物理核上的 vCPU 与仿真器线程产生严重资源争用，反而降低仿真性能。

> Red Hat 文档原文：「使用 isolcpus 时，CFS 调度程序被禁用，所有仿真程序线程都将在第一个可用、最低索引的 pCPU 上运行。」

**对 RTL 仿真器的启示**：Verilator、Questa 等仿真器启用多线程后，主调度线程和 worker 线程如果未显式分配 CPU 掩码，在 `isolcpus` 环境中会集中到默认 pCPU 形成瓶颈。必须**为所有线程**（主线程、事件循环线程、I/O 线程）显式设置亲和性。

### 1.2 cgroups v2 cpuset：运行时的动态隔离

cgroups v2 无需重启即可创建动态 CPU 分区，关键步骤是设置 `cpuset.cpus.partition` 为 `isolated`，这相当于运行时的 `isolcpus`。

```bash
# 启用 cpuset 控制器
echo "+cpuset" | sudo tee /sys/fs/cgroup/cgroup.subtree_control

# 创建实时 cgroup
sudo mkdir /sys/fs/cgroup/rt-sim

# 分配隔离核（CPU 2、3）
echo "2-3" | sudo tee /sys/fs/cgroup/rt-sim/cpuset.cpus

# 分配内存节点
echo "0" | sudo tee /sys/fs/cgroup/rt-sim/cpuset.mems

# 设置为 isolated 分区（禁用负载均衡）
echo "isolated" | sudo tee /sys/fs/cgroup/rt-sim/cpuset.cpus.partition

# 将仿真器进程移入 cgroup
echo $(pgrep -f verilator) | sudo tee /sys/fs/cgroup/rt-sim/cgroup.procs

# 验证
ps -eo pid,psr,comm | grep verilator
```

### 1.3 taskset + chrt：线程级绑定与实时优先级

```bash
# 启动仿真器并绑定到 CPU 2，同时赋予 FIFO 实时优先级 80
taskset -c 2 chrt -f 80 ./verilator_sim --threads 4

# 对已在运行的多线程进程绑定 PID
taskset -a -c 2-3 -p <PID>
# -a = 所有线程, -c = CPU 列表, -p = PID

# 验证所有线程的 affinity
ps -To 'pid,lwp,psr,cmd' -p <PID>
```

### 1.4 PREEMPT_RT 与内核启动参数

Intel ECI 推荐的最小启动参数组合：

```
isolcpus=2,3 irqaffinity=0,1 rcu_nocbs=2,3 nohz_full=2,3
```

| 参数 | 作用 |
|------|------|
| `isolcpus=2,3` | 将 CPU 2、3 从 CFS 调度域移除 |
| `irqaffinity=0,1` | 将中断绑定到非实时核（CPU 0、1） |
| `rcu_nocbs=2,3` | 禁止 RCU 回调在实时核上执行 |
| `nohz_full=2,3` | 单任务运行时关闭调度时钟中断 |
| `clocksource=tsc tsc=reliable` | 强制使用 TSC 作为时钟源 |

完整 GRUB 配置示例：

```bash
# 编辑 /etc/default/grub
GRUB_CMDLINE_LINUX_DEFAULT="quiet splash isolcpus=2,3 nohz_full=2,3 rcu_nocbs=2,3 irqaffinity=0,1 intel_pstate=disable nosoftlockup nmi_watchdog=0 clocksource=tsc tsc=reliable"

sudo update-grub
sudo reboot

# 重启后验证
cat /proc/cmdline | grep isolcpus
```

### 1.5 tuna 动态调优（无需重启）

```bash
sudo apt install -y tuna

# 查看当前线程和 IRQ 分配
sudo tuna --show_threads
sudo tuna --show_irqs

# 动态隔离 CPU 2、3
sudo tuna --cpus=2,3 --isolate

# 将仿真器线程迁移到隔离核
sudo tuna --threads=verilator_sim --move --cpus=2,3

# 验证隔离状态
sudo tuna --show_threads --cpus=2,3
```

---

## 2. 多线程调试工具链

### 2.1 GDB 线程调试：三板斧

RTL 仿真器（如 Verilator）的 `--threads` 模式将 DFG 划分为 mtask 并分配到 worker 线程。GDB 提供线程级断点、冻结/解冻、反向步进等能力。

```bash
# 编译时保留调试信息（O0 优化级别）
g++ -g -O0 -pthread sim.cpp -o sim

# 启动 GDB
gdb ./sim

# 列出所有线程（含 LWP ID 和线程名）
(gdb) info threads
  Id   Target Id                                  Frame
* 1    Thread 0x7ffff7f96740 (LWP 2977) "main"     main () at sim.cpp:42
  2    Thread 0x7ffff7bff6c0 (LWP 2980) "worker0" worker_loop () at sim.cpp:88
  3    Thread 0x7ffff73fe6c0 (LWP 2981) "worker1" worker_loop () at sim.cpp:88

# 切换到线程 2
(gdb) thread 2

# 为特定线程设置断点（仅线程 2 在 foo 函数触发）
(gdb) break foo thread 2

# 对所有线程应用命令（如打印程序计数器）
(gdb) thread apply all print $pc
# 简写：taa print $pc

# 忽略错误地对所有线程执行命令
(gdb) thread apply all silent print errno
# 简写：taas print errno

# 查看线程栈回溯（诊断死锁的第一反应）
(gdb) thread apply all bt

# 设置调度器锁定：步进时只运行当前线程
(gdb) set scheduler-locking on
# 可选值：off（默认）、on（仅当前）、step（单步时锁定）
```

**线程命名技巧**：在代码中为 worker 线程设置名称，便于 GDB 中识别。

```cpp
#include <pthread.h>

void* worker_loop(void* arg) {
    int worker_id = *(int*)arg;
    char name[16];
    snprintf(name, sizeof(name), "mtask_w%02d", worker_id);
    pthread_setname_np(pthread_self(), name);
    // ... worker 主循环 ...
}
```

### 2.2 rr（Record & Replay）：消灭 Heisenbug

Mozilla `rr` 通过**序列化线程调度**和**仅记录非确定性输入源**（系统调用返回值、信号），实现确定性重放，典型开销 **1.2x–5x**。

```bash
# 安装 rr（Ubuntu/Debian）
sudo apt install rr

# 记录程序执行（自动处理多线程）
rr record ./verilator_sim
# 默认记录到 ~/.local/share/rr/ 目录

# 列出所有记录
rr ls

# 重放最近一次记录，自动启动 GDB
rr replay

# 在 GDB 中使用反向调试命令
(rr) reverse-next      # 反向单步，不进入函数
(rr) reverse-step      # 反向单步，进入函数
(rr) reverse-continue  # 反向运行到上一个断点/观察点
(rr) reverse-finish    # 反向执行到当前函数调用点

# 在重放中设置硬件观察点，回退到变量最后一次修改
(rr) watch -l shared_var
(rr) reverse-continue

# 性能提示：rr 需要 /proc/sys/kernel/perf_event_paranoid <= 1
echo 1 | sudo tee /proc/sys/kernel/perf_event_paranoid
```

**RTL 场景中的核心价值**：eval 阶段的不同线程调度顺序可能导致竞争条件，表现为时有时无的崩溃。使用 `rr` 可以在一次失败执行后**无限次精确重放**，从根本上消灭 Heisenbug。

### 2.3 QEMU icount 确定性重放

QEMU 的 `-icount` 模式将虚拟时间基准从真实时间切换到**指令计数**，所有非确定性事件按 `事件类型 + 距上次事件的指令数` 格式写入日志，重放时精确注入。

```bash
# 启动记录模式（icount 必须启用）
qemu-system-x86_64 \
  -icount shift=auto,rr=record,rrfile=replay.log \
  -drive file=disk.qcow2,if=none,snapshot,id=img-direct \
  -drive driver=blkreplay,if=none,image=img-direct,id=img-blkreplay \
  -device ide-hd,drive=img-blkreplay \
  -net nic -net user,filter=replay \
  -m 4G -smp 4

# 启动重放模式
qemu-system-x86_64 \
  -icount shift=auto,rr=replay,rrfile=replay.log \
  -drive file=disk.qcow2,if=none,snapshot,id=img-direct \
  -drive driver=blkreplay,if=none,image=img-direct,id=img-blkreplay \
  -device ide-hd,drive=img-blkreplay \
  -m 4G -smp 4
```

**RTL 协同验证**：当 RTL 仿真器与 QEMU 系统仿真进行协同验证时，QEMU 的 record/replay 确保外部 SoC 模型的事件注入完全确定性。RTL 侧观察到的非确定性可确信来源于 RTL 内部，而非 QEMU 的调度抖动。

### 2.4 死锁定位：GDB 实操

多线程死锁调试的标准流程：

```bash
# 1. 打印所有线程的栈回溯
(gdb) thread apply all bt

# 2. 查看所有线程的等待状态
(gdb) info threads

# 3. 查看 mutex 当前所有者（glibc pthread mutex）
(gdb) p mymutex.__owner

# 4. 定位循环等待链：对比各线程的栈帧和锁持有关系
(gdb) thread 2
(gdb) frame 3
(gdb) p lock_a
(gdb) thread 3
(gdb) frame 4
(gdb) p lock_b
```

**常见死锁模式**：
- **ABA 死锁**：线程 A 持有锁 L1 等待 L2，线程 B 持有 L2 等待 L1
- **优先级反转**：高优先级线程等待低优先级线程释放锁，但低优先级线程被中优先级线程抢占
- **信号丢失**：条件变量通知先于等待，导致永久等待

---

## 3. 时间基准：精度、开销与一致性

### 3.1 三种时间指令的对比

| 指令/API | 典型延迟 | 序列化 | 跨核一致性 | 适用场景 |
|----------|----------|--------|------------|----------|
| `rdtsc` | ~11.6 ns | 无 | 有风险（非 Invariant TSC） | 高频采样、绑定到固定 CPU |
| `rdtscp` | ~16.9 ns | 有（隐含 `cpuid`） | 可检测迁移 | 严格顺序性要求、检测线程迁移 |
| `clock_gettime(CLOCK_MONOTONIC)` | ~18.8 ns | 有（vDSO seqlock） | 内核同步 | 粗略计时、单调性保证 |

> 数据来源：Postgres 19 `pg_test_timing` 实测（pganalyze, 2026）。

### 3.2 Invariant TSC 与跨核一致性风险

- **Invariant TSC**：CPUID leaf 0x80000007, EDX[8] = 1 表示 TSC 在所有 P-State/C-State 下频率不变。
- **跨核一致性**：SMP 系统上不同物理核的 TSC 可能存在偏移（skew）。如果仿真器线程被调度器迁移到不同 CPU，两次 `rdtsc` 读数可能来自不同步的计数器。
- **解决方案**：将线程绑定到固定 CPU，或使用 `rdtscp`（通过 `aux` 寄存器返回 CPU ID，可检测迁移）。

```cpp
// 检测 Invariant TSC
static inline bool isInvariantTSC(void) {
    uint32_t a = 0x80000007, b, c, d;
    asm volatile("cpuid" : "=a"(a), "=b"(b), "=c"(c), "=d"(d)
                 : "0"(a), "1"(b), "2"(c), "3"(d));
    return (d & (1UL << 8)) != 0;  // EDX[8]
}

// 绑定线程到固定 CPU，避免跨核 TSC 不同步
static void bindToCpu(int cpu) {
    cpu_set_t set;
    CPU_ZERO(&set);
    CPU_SET(cpu, &set);
    if (sched_setaffinity(0, sizeof(set), &set) != 0) {
        perror("sched_setaffinity");
    }
}
```

### 3.3 `rdtscp` 检测线程迁移

```cpp
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

uint64_t measure_critical_section() {
    uint32_t aux_start, aux_end;
    uint64_t start = rdtscp(&aux_start);
    // ... 被测量的代码 ...
    uint64_t end = rdtscp(&aux_end);
    
    if (aux_start != aux_end) {
        fprintf(stderr, "警告：测量期间线程从 CPU %u 迁移到 CPU %u\n",
                aux_start, aux_end);
        // 该次测量数据应被丢弃
    }
    return end - start;
}
```

### 3.4 `clock_gettime` 的 vDSO 加速

Linux 内核的 vDSO 将 `clock_gettime(CLOCK_MONOTONIC)` 映射到用户空间，避免真实 `syscall` 陷入。vDSO 内部优先使用 TSC（如果内核判定为可靠），通过 seqlock 同步内核时间校准数据。

```bash
# 查看当前系统使用的时钟源
cat /sys/devices/system/clocksource/clocksource0/current_clocksource
# 输出: tsc  (理想) 或 hpet / acpi_pm / jiffies

# 查看 vDSO 是否可用
ldd /bin/date | grep linux-vdso
# 输出: linux-vdso.so.1 (0x00007fff...) 表示已加载

# 使用 perf 测试 gettime 开销
perf stat -e cycles,instructions ./test_gettime
```

---

## 4. 对 RTL 仿真器的启示

### 4.1 必须绑定线程到 CPU（避免调度器迁移）

OS 调度器是 RTL 仿真器性能抖动的最大外部变量。CFS 的负载均衡会将 worker 线程在不同 CPU 间迁移，导致：
- L1/L2 cache 失效
- 跨核 TSC 不同步（若使用 `rdtsc` 计时）
- 调度器抢占引入非确定性执行路径

**推荐做法**：在仿真器初始化时，通过 `pthread_setaffinity_np` 或 `taskset` 将每个 worker 线程绑定到专用 CPU，主线程和 I/O 线程绑定到非隔离核。

### 4.2 用 rr 调试多线程 race bug

RTL 仿真器引入多线程后，eval 阶段的竞争条件表现为「Heisenbug」——十次运行中可能只出现一次。`rr` 的确定性重放可以：
- 一次记录失败执行，无限次重放
- 使用 `reverse-continue` 从失败点回退到「信号最后一次有效」的时刻
- 在重放中设置硬件 watchpoint，精确定位数据竞争

**建议**：将 `rr record` 集成到 CI/CD 的回归测试流程中，自动捕获并归档失败执行的 trace。

### 4.3 用 `rdtscp` 做微基准测量（绑定到单一 CPU）

在 profiling 场景（非确定性可接受）：
- 使用 `rdtscp`（带序列化）+ `cpuid` 检测 Invariant TSC
- 将采样线程固定在单一 CPU
- 丢弃检测到线程迁移的样本

在确定性场景（如 record/replay 辅助调试）：
- 采用「逻辑 cycle 计数」作为时间基准，完全脱离主机时间
- 不应混用 `rdtsc`/`clock_gettime` 与逻辑计数，否则重放时 profiler 数据不可复现

### 4.4 用 cgroups 隔离仿真器线程

在共享服务器或多租户环境中，使用 cgroups v2 的 `cpuset` 为仿真器分配专用 CPU 分区，避免与其他进程争用。无需重启内核，动态生效。

### 4.5 时钟中断与 TSC 的联动

`nohz_full` 和 `isolcpus` 常与时钟源配置 `clocksource=tsc tsc=reliable` 一起使用。如果仿真器内部使用 `rdtsc` 做高精度计时，将线程绑定到固定 CPU 可以避免跨核 TSC 不同步问题。

---

## 5. 完整配置示例

### 5.1 内核启动参数（GRUB）

```bash
# /etc/default/grub
GRUB_CMDLINE_LINUX_DEFAULT="quiet splash isolcpus=2,3 nohz_full=2,3 rcu_nocbs=2,3 irqaffinity=0,1 intel_pstate=disable nosoftlockup nmi_watchdog=0 clocksource=tsc tsc=reliable"

sudo update-grub
sudo reboot

# 验证
cat /proc/cmdline | grep isolcpus
cat /proc/cpuinfo | grep -o 'constant_tsc\|nonstop_tsc\|tsc_adjust\|tsc_deadline_timer\|rdtscp' | sort -u
dmesg | grep -i "tsc\|clocksource"
```

### 5.2 systemd Service：自动绑定与隔离

```ini
# /etc/systemd/system/rt-simulator.service
[Unit]
Description=RTL Simulator with Real-Time CPU Isolation
After=network.target

[Service]
Type=simple
ExecStart=/opt/rtl-sim/bin/verilator_sim --threads 4
ExecStartPre=/bin/sh -c 'echo +cpuset > /sys/fs/cgroup/cgroup.subtree_control'
ExecStartPre=/bin/mkdir -p /sys/fs/cgroup/rt-sim
ExecStartPre=/bin/sh -c 'echo 2-3 > /sys/fs/cgroup/rt-sim/cpuset.cpus'
ExecStartPre=/bin/sh -c 'echo 0 > /sys/fs/cgroup/rt-sim/cpuset.mems'
ExecStartPre=/bin/sh -c 'echo isolated > /sys/fs/cgroup/rt-sim/cpuset.cpus.partition'
ExecStartPre=/bin/sh -c 'echo 0 > /sys/fs/cgroup/rt-sim/cpuset.sched_load_balance'

# 将服务进程放入 cgroup
Slice=rt-sim.slice

# 实时优先级（SCHED_FIFO，优先级 80）
CPUAffinity=2 3
CPUSchedulingPolicy=fifo
CPUSchedulingPriority=80

# 内存限制（防止 OOM 影响其他服务）
MemoryLimit=32G

# 日志
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

```bash
# 启动服务
sudo systemctl daemon-reload
sudo systemctl enable rt-simulator.service
sudo systemctl start rt-simulator.service

# 查看状态和 cgroup 分配
sudo systemctl status rt-simulator.service
ps -eo pid,psr,comm,args | grep verilator_sim
cat /sys/fs/cgroup/rt-sim/cpuset.cpus
```

### 5.3 cgroups 配置脚本（独立版本）

```bash
#!/bin/bash
# setup_rt_cgroup.sh — 为 RTL 仿真器配置实时 cgroup

set -e

RT_CPUS="2,3"
CGROUP_NAME="rt-sim"
SIM_PID=""

usage() {
    echo "Usage: $0 [-p PID] [-c CPU_LIST] [-n CGROUP_NAME]"
    echo "  -p PID          将已有进程移入 cgroup（默认：后续手动启动）"
    echo "  -c CPU_LIST     隔离 CPU 列表（默认：2,3）"
    echo "  -n CGROUP_NAME  cgroup 名称（默认：rt-sim）"
    exit 1
}

while getopts "p:c:n:h" opt; do
    case $opt in
        p) SIM_PID=$OPTARG ;;
        c) RT_CPUS=$OPTARG ;;
        n) CGROUP_NAME=$OPTARG ;;
        h) usage ;;
        *) usage ;;
    esac
done

CGROUP_PATH="/sys/fs/cgroup/${CGROUP_NAME}"

echo "[1/5] 启用 cpuset 控制器..."
if ! grep -q "cpuset" /sys/fs/cgroup/cgroup.subtree_control 2>/dev/null; then
    echo "+cpuset" | sudo tee /sys/fs/cgroup/cgroup.subtree_control
fi

echo "[2/5] 创建 cgroup ${CGROUP_NAME}..."
sudo mkdir -p "${CGROUP_PATH}"

echo "[3/5] 设置 CPU 掩码 ${RT_CPUS}..."
echo "${RT_CPUS}" | sudo tee "${CGROUP_PATH}/cpuset.cpus"

echo "[4/5] 设置内存节点..."
echo "0" | sudo tee "${CGROUP_PATH}/cpuset.mems"

echo "[5/5] 设置 isolated 分区..."
echo "isolated" | sudo tee "${CGROUP_PATH}/cpuset.cpus.partition"

if [ -n "$SIM_PID" ]; then
    echo "[*] 将 PID ${SIM_PID} 移入 cgroup..."
    echo "${SIM_PID}" | sudo tee "${CGROUP_PATH}/cgroup.procs"
    ps -To 'pid,lwp,psr,cmd' -p "${SIM_PID}"
else
    echo "[*] 请在 cgroup 内启动仿真器："
    echo "    cgexec -g cpuset:${CGROUP_NAME} ./verilator_sim"
fi

echo "[✓] 配置完成。验证命令："
echo "    cat ${CGROUP_PATH}/cpuset.cpus"
echo "    cat ${CGROUP_PATH}/cpuset.cpus.partition"
```

### 5.4 GDB 自动化脚本：多线程调试

```gdb
# .gdbinit-rtl — RTL 仿真器多线程调试专用脚本

# 打印线程事件（创建/退出）
set print thread-events on

# 打印所有线程的回溯（诊断死锁时直接使用）
define allbt
    thread apply all bt
end

document allbt
    Print backtrace for all threads.
end

# 切换到特定 worker 线程（假设已命名）
define worker
    if $argc != 1
        printf "Usage: worker <worker_id>\n"
    else
        thread find mtask_w$arg0
    end
end

document worker
    Switch to worker thread by ID (e.g., worker 0 -> mtask_w00).
end

# 在所有 worker 线程上设置断点
define breakall
    if $argc != 1
        printf "Usage: breakall <function_name>\n"
    else
        thread apply all break $arg0
    end
end

document breakall
    Set breakpoint on all threads.
end

# 冻结除当前线程外的所有线程（单线程步进）
define freeze_others
    set $current = $_thread
    thread apply all -s print ""
    thread $current
    set scheduler-locking on
    printf "Scheduler locked. Only thread %d will execute.\n", $current
end

document freeze_others
    Freeze all threads except current, enable scheduler-locking.
end

# 解锁所有线程
define thaw_all
    set scheduler-locking off
    printf "All threads unlocked.\n"
end

document thaw_all
    Resume normal multithreaded execution.
end

# 死锁诊断：打印所有 mutex 的 owner
define deadlock_check
    printf "=== Thread States ===\n"
    info threads
    printf "\n=== Backtraces ===\n"
    thread apply all bt
    printf "\n=== Mutex Owners ===\n"
    # 需根据实际 mutex 变量名修改
    # p &my_mutex
    # p my_mutex.__owner
end

document deadlock_check
    Diagnose potential deadlock: print all threads, backtraces, and mutex owners.
end
```

---

## 6. 部署前 OS 调优检查清单

### 6.1 硬件层检查

- [ ] 确认 CPU 支持 **Invariant TSC**（`cat /proc/cpuinfo | grep constant_tsc`）
- [ ] 确认支持 **rdtscp** 指令（`cat /proc/cpuinfo | grep rdtscp`）
- [ ] 确认 NUMA 拓扑与 CPU 核心映射（`numactl --hardware`）
- [ ] 确认内存通道配置对称（`dmidecode -t memory`）
- [ ] 禁用 CPU 频率缩放（BIOS 中关闭 SpeedStep/TurboBoost，或 `intel_pstate=disable`）

### 6.2 内核层检查

- [ ] 已配置 `isolcpus` 启动参数，隔离核已生效
- [ ] 已配置 `irqaffinity`，中断不落在隔离核上
- [ ] 已配置 `nohz_full`，隔离核无调度时钟中断
- [ ] 已配置 `rcu_nocbs`，RCU 回调不在隔离核执行
- [ ] 时钟源已设为 `tsc`（`cat /sys/devices/system/clocksource/clocksource0/current_clocksource`）
- [ ] 已禁用 NMI watchdog（`nmi_watchdog=0`）
- [ ] 已禁用软锁检测（`nosoftlockup`）
- [ ] 确认未使用 `isolcpus` 的「managed_irq」变体（该变体会让中断子系统重新向隔离核发送 IRQ）

### 6.3 调度器层检查

- [ ] 仿真器主线程已绑定到非隔离核（负责 I/O、调度）
- [ ] 仿真器 worker 线程已绑定到隔离核（`taskset -a -c` 或 `pthread_setaffinity_np`）
- [ ] 关键线程已设置 SCHED_FIFO 实时优先级（`chrt -f 80`）
- [ ] 已使用 cgroups v2 `cpuset` 创建 isolated 分区（或 `isolcpus` 已配置）
- [ ] 已验证线程亲和性（`ps -To 'pid,lwp,psr,cmd' -p <PID>`）
- [ ] 已禁用 CPU 负载均衡在隔离核之间（`cpuset.sched_load_balance = 0`）

### 6.4 调试基础设施检查

- [ ] GDB 已安装且支持多线程（`gdb --version`）
- [ ] `rr` 已安装且 `perf_event_paranoid <= 1`（`cat /proc/sys/kernel/perf_event_paranoid`）
- [ ] 仿真器编译带 `-g -O0`（调试版本）或 `-g -O2`（带调试信息的优化版本）
- [ ] worker 线程已设置 `pthread_setname_np`，便于 GDB 识别
- [ ] 若使用 QEMU 协同仿真，确认 `-icount` 模式已启用（确定性时间）

### 6.5 时间基准检查

- [ ] 仿真器内部时间基准已选择：
  - [ ] 确定性场景 → 逻辑 cycle 计数（脱离主机时间）
  - [ ] 性能剖析场景 → `rdtscp` + 线程绑定到单一 CPU
- [ ] 已检测 Invariant TSC 并绑定采样线程到固定 CPU
- [ ] 若使用 `clock_gettime(CLOCK_MONOTONIC)`，确认 vDSO 已启用（`ldd /bin/date | grep vdso`）
- [ ] 未混用 `CLOCK_REALTIME`（可能被 NTP 调整）与单调时间基准

### 6.6 验证命令速查

```bash
# 验证 isolcpus 和启动参数
cat /proc/cmdline

# 验证时钟源和 TSC 状态
cat /sys/devices/system/clocksource/clocksource0/current_clocksource
cat /sys/devices/system/clocksource/clocksource0/available_clocksource
dmesg | grep -i "tsc\|clocksource"

# 验证 CPU 隔离状态
cat /sys/devices/system/cpu/isolated
cat /sys/devices/system/cpu/present

# 验证线程亲和性（替换 <PID> 为实际进程 ID）
ps -To 'pid,lwp,psr,cmd' -p <PID>
taskset -a -p <PID>

# 验证 cgroup 配置
cat /sys/fs/cgroup/rt-sim/cpuset.cpus
cat /sys/fs/cgroup/rt-sim/cpuset.cpus.partition

# 验证 rr 可用性
rr --version
cat /proc/sys/kernel/perf_event_paranoid  # 应 <= 1

# 验证实时优先级
chrt -p <PID>  # 显示调度策略和优先级
```

---

## 7. 常见陷阱与排错

| 症状 | 可能原因 | 排查命令 |
|------|----------|----------|
| 仿真器性能抖动大，延迟不可预测 | 线程被调度器迁移，未绑定到固定 CPU | `ps -To 'pid,lwp,psr,cmd' -p <PID>` |
| 隔离核上仍有中断 | `irqaffinity` 未配置或 `managed_irq` 变体问题 | `cat /proc/interrupts`，检查隔离核的 IRQ 计数 |
| `rr record` 失败 | `perf_event_paranoid` 过高 | `cat /proc/sys/kernel/perf_event_paranoid` |
| `rdtsc` 测量值异常波动 | 线程迁移到不同 CPU，或非 Invariant TSC | 用 `rdtscp` 检测 `aux` 变化；检查 `constant_tsc` |
| cgroups v2 无法创建 isolated 分区 | 父 cgroup 未启用 cpuset 或已有其他子 cgroup | 检查 `/sys/fs/cgroup/cgroup.subtree_control` |
| 死锁无法定位 | 未打印所有线程回溯；mutex 未暴露 __owner | `thread apply all bt`；检查编译优化级别（`-O0`） |
| QEMU 重放不同步 | icount 未启用或 `rrfile` 路径错误 | 检查 `-icount shift=auto,rr=replay` 参数 |

---

## 8. 参考索引

- `source-os-scheduling` — Linux 调度器与 CPU 隔离对实时仿真器性能的影响
- `source-multithread-debugging` — 多线程仿真器调试技术综述（GDB、rr、QEMU icount）
- `source-timekeeping-simulation` — 仿真器中的高精度时间keeping（TSC、rdtsc、clock_gettime）
