---
title: 版本控制嵌入与构建可复现性
description: CMake 中嵌入 Git commit hash 的方法、构建可复现性（Reproducible Builds）原则与 C++ 编译器标志
source_url: "https://jonathanhamberg.com/posts/cmake-embedding-git-hash/"
source_type: "blog"
author: "Jonathan Hamberg"
date: "2020-11-27"
tags: ["git", "cmake", "version-embedding", "reproducible-build", "build-system", "version-string"]
keywords: ["git hash embedding build", "build reproducibility C++", "CMAKE git commit hash", "version string embedding", "reproducible build simulation"]
capture_date: "2026-07-03"
---

# 版本控制嵌入与构建可复现性

## 来源

- URL: https://jonathanhamberg.com/posts/cmake-embedding-git-hash/
- URL: https://github.com/andrew-hardin/cmake-git-version-tracking
- URL: https://reproducible-builds.org/
- 类型: blog / github / doc
- 作者: Jonathan Hamberg / Andrew Hardin / reproducible-builds.org 社区
- 日期: 2020–2025

## 摘要

将 Git commit hash 嵌入到编译产物中，是定位 bug 版本、支持可复现构建的关键实践。本文介绍了 CMake 中嵌入 Git hash 的三种方案：通过 `target_compile_definitions` 在每次构建时全量重编译、通过 `configure_file` 生成头文件触发局部重编译、以及最优方案——将 hash 写入单独的 `.cpp` 源文件并链接为静态库，仅在该文件变更时重编译。同时，本文涵盖了构建可复现性（Reproducible Builds）的通用原则：固定编译器版本、统一编译器标志、消除非确定性文件顺序与时间戳、使用 `SOURCE_DATE_EPOCH` 与 `pathmap` 等工具链支持。

## 关键要点

- **CMake 嵌入 Git Hash 的三种方案**：
  1. `target_compile_definitions`：将 hash 作为宏定义传递，但 commit 变化会导致整个项目重编译。
  2. `configure_file` 生成头文件：仅触发包含该头文件的源文件重编译，优于方案一。
  3. **推荐方案**：`git_version.h` 声明外部符号，`git_version.cpp.in` 通过 `configure_file` 生成实现文件。配合 `add_custom_target` 在每次构建时检查 hash 是否变化，仅重编译 `git_version.cpp`。
- **避免 CMake 重新配置**：`execute_process(COMMAND git log -1 --format=%h ...)` 仅在 CMake 配置阶段运行。若配置后新提交，hash 不会更新。应使用 `add_custom_target` 或 `add_custom_command` 在构建阶段动态检查。
- **缓存文件技巧**：在 CMake script 模式下，由于没有缓存访问权限，将上一次 hash 写入 `git-state.txt` 文件，通过 `file(WRITE)` 和 `file(STRINGS)` 做增量判断，避免无意义的重新生成。
- **GitHash 库方案**：`Svalorzen/GitHash` 提供了开箱即用的 CMake 模块，暴露 `GitHash::branch`、`GitHash::sha1`、`GitHash::shortSha1`、`GitHash::dirty` 等符号，自带缓存机制，避免重复编译。
- **构建可复现性原则**：
  - 同一源代码 + 同一构建环境 → 同一二进制产物。
  - 非确定性来源：编译器内建宏（如 `__DATE__` / `__TIME__`）、文件系统遍历顺序、链接器输入顺序、随机生成的 GUID、绝对路径嵌入。
  - 工具链支持：MSVC 2019+ `/experimental:deterministic` + `/pathmap`；GCC/Clang 通过 reproducible-builds.org 文档支持 `SOURCE_DATE_EPOCH`。
  - 现代构建系统（Bazel、Buck2）通过沙箱与封闭构建（hermetic build）大幅减少环境不确定性。
- **编译器标志追踪**：`arXiv:2312.13463` 指出，C++ 编译器可能以非确定性方式生成代码，且链接器输入顺序取决于构建 DAG 的完成顺序。应将完整编译器标志与构建元数据一同归档，便于事后审计与调试。

## 对 RTL 仿真器多线程化的启示

- RTL 仿真器通常需要向波形文件、日志文件、崩溃报告中写入**版本信息**（Git hash + dirty flag），以便 QA 或 CI 系统快速定位问题来源。采用「单独 `.cpp` 源文件 + 外部符号引用」方案，可避免每次提交都触发大规模重编译。
- 仿真器若采用分布式集群运行，应保证**构建可复现性**：不同节点上的编译产物必须 bit-exact 一致，否则多线程/多节点间行为差异可能被错误归咎于代码逻辑而非构建差异。
- 建议在构建产物中嵌入 `git describe --always --dirty` 格式的完整版本字符串，同时附带编译器版本、CMake 配置摘要和构建时间戳（由 `SOURCE_DATE_EPOCH` 控制而非 wall-clock）。
- 对于需要审计的场景（如安全相关 RTL 验证），构建可复现性可以确保任何开发者都能从相同源码复现出相同的二进制，从而验证供应链未被篡改。

## 原文摘录

> Often times it's very useful to include the version number into the software that you are building. Even better than a version number is the git hash of the commit that was used to build the software release.

> This command is only run during the CMake configuration stage. So if the user configure the CMake project, then commits some changes, and then builds again the GIT_HASH variable will not be updated because the CMake project was not re-configured.

> The third option would to be to have a header file that contains a external reference to the git commit hash. The git commit hash would then be written to a source .c or .cpp file. This has the advantage of only having to re-compile one file when the git commit hash has changed.

> Popular C++ compilers can generate code in a non-deterministic manner. Recompiling a translation unit using the same build configuration can result in a different binary. Similarly, modern build systems process the build graph efficiently by rendering directed acyclic graph-like build dependencies. As a result, the order of object files listed during the linking stage will depend on which translation unit the compiler built first. That, in turn, can cause non-deterministic behavior.

> Reproducible builds are a set of software development practices that create an independently-verifiable path from source to binary code.

## 代码示例

### 示例 1：CMake 最优方案 — 仅重编译单个 git_version.cpp

```cmake
# CMakeLists.txt 片段
# -------------------------------
# git_version.h  — 声明外部符号
# git_version.cpp.in — 模板文件，被 configure_file 替换
# -------------------------------

# 读取当前 git commit hash（配置阶段用）
execute_process(
    COMMAND git log -1 --format=%h
    WORKING_DIRECTORY ${CMAKE_CURRENT_LIST_DIR}
    OUTPUT_VARIABLE GIT_HASH
    OUTPUT_STRIP_TRAILING_WHITESPACE
)

# 配置模板文件生成 git_version.cpp
configure_file(
    ${CMAKE_CURRENT_SOURCE_DIR}/git_version.cpp.in
    ${CMAKE_CURRENT_BINARY_DIR}/git_version.cpp
    @ONLY
)

# 将生成的 .cpp 编译为静态库，只有 hash 变化时才会重编译
add_library(git_version STATIC
    ${CMAKE_CURRENT_BINARY_DIR}/git_version.cpp
)

# 主程序链接该库
target_link_libraries(my_simulator PRIVATE git_version)
```

```cpp
// git_version.h
#ifndef GIT_VERSION_H
#define GIT_VERSION_H
extern const char* kGitHash;
#endif
```

```cpp
// git_version.cpp.in
#include "git_version.h"
const char* kGitHash = "@GIT_HASH@";
```

```cpp
// main.cpp
#include <iostream>
#include "git_version.h"

int main() {
    std::cout << "RTL Simulator\n";
    std::cout << "Git Commit: " << kGitHash << "\n";
    return 0;
}
```

### 示例 2：每次构建都检查 hash 是否更新的 add_custom_target

```cmake
# CheckGit.cmake（脚本文件）
# -------------------------------
execute_process(
    COMMAND git log -1 --format=%h
    WORKING_DIRECTORY ${pre_configure_dir}
    OUTPUT_VARIABLE git_hash
    OUTPUT_STRIP_TRAILING_WHITESPACE
)

# 读取上一次缓存的 hash
if(EXISTS ${CMAKE_BINARY_DIR}/git-state.txt)
    file(STRINGS ${CMAKE_BINARY_DIR}/git-state.txt CONTENT)
    list(GET CONTENT 0 old_hash)
else()
    set(old_hash "")
endif()

# 如果不同，重新生成源文件
if(NOT "${git_hash}" STREQUAL "${old_hash}")
    file(WRITE ${CMAKE_BINARY_DIR}/git-state.txt ${git_hash})
    configure_file(
        ${pre_configure_dir}/git_version.cpp.in
        ${post_configure_file}
        @ONLY
    )
endif()
```

```cmake
# CMakeLists.txt 中注册 always-run target
add_custom_target(AlwaysCheckGit
    COMMAND ${CMAKE_COMMAND}
        -DRUN_CHECK_GIT_VERSION=1
        -Dpre_configure_dir=${CMAKE_CURRENT_SOURCE_DIR}
        -Dpost_configure_file=${CMAKE_CURRENT_BINARY_DIR}/git_version.cpp
        -P ${CMAKE_CURRENT_SOURCE_DIR}/CheckGit.cmake
    BYPRODUCTS ${CMAKE_CURRENT_BINARY_DIR}/git_version.cpp
)

add_library(git_version STATIC ${CMAKE_CURRENT_BINARY_DIR}/git_version.cpp)
add_dependencies(git_version AlwaysCheckGit)
```

### 示例 3：获取完整版本信息（含 dirty flag、分支、日期）

```cpp
// version_info.h
#pragma once
#include <string>

struct VersionInfo {
    std::string hash;       // 短 hash, e.g. "a1b2c3d"
    std::string branch;     // 当前分支, e.g. "main"
    bool dirty;             // 工作区是否有未提交修改
    std::string build_date; // 构建日期（由 SOURCE_DATE_EPOCH 控制）
};

VersionInfo get_version_info();
```

```cpp
// version_info.cpp.in（CMake configure_file 模板）
#include "version_info.h"

VersionInfo get_version_info() {
    return VersionInfo{
        "@GIT_HASH@",
        "@GIT_BRANCH@",
        @GIT_DIRTY@,  // true 或 false
        "@BUILD_DATE@"
    };
}
```

```cmake
# CMake 中收集更全面的 git 信息
execute_process(COMMAND git rev-parse --short HEAD  OUTPUT_VARIABLE GIT_HASH  ...)
execute_process(COMMAND git rev-parse --abbrev-ref HEAD OUTPUT_VARIABLE GIT_BRANCH ...)
execute_process(COMMAND git diff --quiet OUTPUT_QUIET ERROR_QUIET RESULT_VARIABLE GIT_DIRTY_RES)
if(GIT_DIRTY_RES)
    set(GIT_DIRTY "true")
else()
    set(GIT_DIRTY "false")
endif()

# 使用 SOURCE_DATE_EPOCH 保证可复现时间戳
if(DEFINED ENV{SOURCE_DATE_EPOCH})
    set(BUILD_DATE "$ENV{SOURCE_DATE_EPOCH}")
else()
    string(TIMESTAMP BUILD_DATE "%Y-%m-%dT%H:%M:%S" UTC)
endif()
```

## 相关链接

- [Jonathan Hamberg — Embedding Git Hash with CMake](https://jonathanhamberg.com/posts/cmake-embedding-git-hash/)
- [cmake-git-version-tracking (GitHub)](https://github.com/andrew-hardin/cmake-git-version-tracking)
- [Svalorzen/GitHash (GitHub)](https://github.com/Svalorzen/GitHash)
- [Stack Overflow — How to make Git commit hash available in C++ without needless recompiling?](https://stackoverflow.com/questions/51727566/)
- [Reproducible Builds 官网](https://reproducible-builds.org/)
- [NIST — Source and Executable Core Deterministic Build](https://csrc.nist.gov/CSRC/media/Projects/cyber-supply-chain-risk-management/documents/SSCA/Fall_2019/WedAM1.1_Source_and_Executable_Core.pdf)
- [arXiv:2312.13463 — Compiler Flags and Build Reproducibility](https://arxiv.org/abs/2312.13463)
