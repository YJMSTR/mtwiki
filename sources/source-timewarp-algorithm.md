---
title: "Time Warp: Virtual Time and Optimistic Synchronization"
source_url: "https://worrydream.com/refs/Jefferson_1987_-_Distributed_Simulation_and_the_Time_Warp_Operating_System.pdf"
source_type: "paper"
author: "David R. Jefferson"
date: "1985"
tags: ["pdes", "time-warp", "optimistic", "rollback", "antimessage", "virtual-time", "synchronization"]
keywords: ["time-warp", "virtual-time", "optimistic-synchronization", "rollback", "antimessage", "gvt", "distributed-simulation"]
capture_date: "2026-07-01"
---

# Time Warp: Virtual Time and Optimistic Synchronization

## 来源

- 主要URL: https://worrydream.com/refs/Jefferson_1987_-_Distributed_Simulation_and_the_Time_Warp_Operating_System.pdf
- 原始论文: https://ftp.cs.ucla.edu/tech-report/198_-reports/870042.pdf
- 原始发表: Jefferson, D. R. "Virtual Time." ACM Transactions on Programming Languages and Systems (TOPLAS) 7.3 (1985): 404-425.
- 类型: paper
- 作者: David R. Jefferson (Lawrence Livermore National Laboratory / Rand Corporation / UCLA)
- 日期: 1985
- 合著者/合作者: Henry Sowizral (Time Warp机制共同发明人), 后续实现包括Time Warp Operating System (TWOS) 等

## 摘要

Time Warp是由David Jefferson和Henry Sowizral在1980年代初期（Rand Corporation）发明的乐观同步机制，用于分布式离散事件仿真。其核心思想是：允许系统中的逻辑进程（LP）不受限制地向前执行事件，无需等待其他进程的同步信号。当某个LP收到一个时间戳小于其当前本地虚拟时间（LVT）的事件（称为straggler）时，该LP必须回滚（rollback）到一个安全状态，并使用anti-message（反消息）来取消已经发送给下游LP的错误事件。anti-message与其对应的正消息相遇时会发生"湮灭"（annihilation），类似粒子物理学中的粒子-反粒子对。为了 reclaim 内存，系统需要定期计算Global Virtual Time (GVT)——系统中所有未处理事件的最小时间戳，任何小于GVT的状态都可以被安全释放。Jefferson将Time Warp重新诠释为"虚拟时间"（Virtual Time）范式的实现，与虚拟内存（Virtual Memory）之间存在深刻的时空对称性。

## 关键要点

- **基本机制**: LP自由执行事件，通过rollback纠正因果错误。rollback时恢复LP状态，并发送anti-message取消已发送的错误事件。
- **Anti-message**: 与原始消息内容相同但标记为"反消息"的消息。当anti-message到达时，如果原始消息已被处理，则接收方LP也需要rollback；如果原始消息还在队列中，两者直接湮灭。
- **Global Virtual Time (GVT)**: 系统中所有未处理事件的最小时间戳。GVT是单调递增的，表示整个仿真已确定的最早时间点。任何状态或事件的时间戳小于GVT时可以被安全回收（fossil collection）。
- **虚拟时间理论**: Jefferson在1985年的论文"Virtual Time"中将Time Warp从单纯的仿真机制提升为更广泛的分布式系统同步范式，建立了与虚拟内存之间的形式对称性。
- **Time Warp Operating System (TWOS)**: 1987年在JPL/Caltech的Mark III Hypercube上实现，是第一个完整的Time Warp操作系统。后续有Georgia Tech Time Warp (GTW), ROSS, Warped2等实现。
- **反向计算 (Reverse Computation)**: 作为状态保存的替代方案，通过逆向计算事件效果来实现rollback，可以显著减少内存使用。Carothers和Perumalla在1999年推动了这一方向。

## 对 RTL 仿真器多线程化的启示

1. **乐观同步对零延迟电路天然友好**: RTL门级仿真中，组合逻辑的传播延迟通常建模为零（或delta cycle）。在保守同步中，零延迟意味着零lookahead，导致无法并行化。Time Warp的乐观同步不依赖lookahead，允许组合逻辑LP自由执行，这使其特别适合RTL门级仿真的并行化。

2. **Anti-message在共享内存中可优化**: Jefferson和Fujimoto都指出，在共享内存多处理器上，anti-message可以通过简单的指针操作（direct cancellation）实现，无需实际发送消息。在稀疏计算RTL仿真器中，当一个门LP rollback时，需要取消它发送给下游门LP的事件。在共享内存架构下，可以直接在目标LP的事件队列中标记删除，大幅降低开销。

3. **状态保存策略的选择**: 对于RTL门级LP，单个门的状态通常只有1-2 bit（输出值）。完整状态保存（copy state saving）每事件保存一个bit，开销极小。增量状态保存（incremental state saving）可能反而因跟踪开销而不划算。对于包含寄存器文件或存储器的LP，可以采用混合策略：对bit级状态完整保存，对大数组增量保存。

4. **GVT计算是共享内存RTL仿真的瓶颈**: 在共享内存多线程环境中，GVT计算需要扫描所有线程的事件队列。Fujimoto和Hybinette (1997) 提出了针对共享内存的GVT优化算法。对于RTL仿真器，由于事件频率高、LP数量多，需要特别高效的GVT算法，或者考虑近似GVT/分批GVT计算。

5. **Bounded Time Warp降低投机风险**: 纯Time Warp在RTL仿真中可能因过度乐观执行导致大量无用计算。可以为乐观执行设置一个时间窗口边界（如GVT + Δ），限制LP超前执行的最大距离。这类似于"乐观窗口"技术，在通用PDES和RTL仿真中都能有效减少rollback。

6. **RTL电路的层次结构可用于减少rollback**: 在RTL设计中，时钟域是天然的时间边界。同一时钟域内的寄存器LP可以形成保守同步簇，而跨时钟域的异步路径才需要乐观同步。这种层次化同步可以大幅降低rollback频率。

## 原文摘录

> "The basic Time Warp mechanism, which is at the heart of TWOS, was invented by Henry Sowizral and David Jefferson (then at the Rand Corporation and the University of Southern California respectively) as a method for speeding up discrete event simulations. The major contribution of that work was the idea that process rollback should be considered a fundamental synchronization tool for distributed simulation. Before Time Warp was described most researchers probably believed that general rollback in an asynchronous environment was either fundamentally impossible to implement, or prohibitively expensive. Time Warp offered a simple and elegant implementation based on the notions of antimessages and annihilation."

> "Later the theory of virtual time was introduced as a paradigm for organizing and synchronizing certain kinds of distributed systems. Virtual time is a global temporal coordinate axis defined by the application as a measure of its progress and as a scale against which to specify synchronization."

> "There is a strong space-time symmetry between the theories of virtual memory and virtual time, and between their respective implementations, demand paging and the Time Warp mechanism."

> "Time Warp seems to have the widest applicability with the fewest restrictions, and seems to be the only choice for applications that contain instances of the following virtual time synchronization problem."

> "The success of the symmetry between message and antimessages led me to make symmetry a key design principle in Time Warp and its extensions over the years."

## 相关链接

- [Virtual Time (1985) PDF](https://ftp.cs.ucla.edu/tech-report/198_-reports/870042.pdf)
- [Distributed Simulation and the Time Warp Operating System (1987)](https://worrydream.com/refs/Jefferson_1987_-_Distributed_Simulation_and_the_Time_Warp_Operating_System.pdf)
- [Time Warp Operating System (ResearchGate)](https://www.researchgate.net/publication/234812891_Time_warp_operating_system)
- [Jefferson在Making of a Field中的个人回忆](https://www.researchgate.net/publication/322325092_Parallel_discrete_event_simulation_The_making_of_a_field)
- [ROSS: Rensselaer's Optimistic Simulation System](https://github.com/gonsie/ROSS)
