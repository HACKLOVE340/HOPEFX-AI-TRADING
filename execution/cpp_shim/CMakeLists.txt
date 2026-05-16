cmake_minimum_required(VERSION 3.16)
project(hopefx_shim CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Release build: maximum optimisation.
# -march=native is only applied when no explicit march flag is passed in via
# CMAKE_CXX_FLAGS (e.g. CI passes -march=x86-64 for portability).
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()

if(CMAKE_CXX_FLAGS MATCHES "-march=")
  # Caller supplied an explicit -march — use it; don't override with native.
  set(CMAKE_CXX_FLAGS_RELEASE "-O3 -DNDEBUG")
else()
  set(CMAKE_CXX_FLAGS_RELEASE "-O3 -march=native -mtune=native -DNDEBUG")
endif()

# Link-time optimisation
set(CMAKE_INTERPROCEDURAL_OPTIMIZATION TRUE)

# ── ZeroMQ ────────────────────────────────────────────────────────────────────
find_package(PkgConfig REQUIRED)
pkg_check_modules(ZMQ REQUIRED libzmq)

# cppzmq header-only binding (fetched via FetchContent if not installed)
include(FetchContent)
FetchContent_Declare(
    cppzmq
    GIT_REPOSITORY https://github.com/zeromq/cppzmq.git
    GIT_TAG        v4.10.0
)
set(CPPZMQ_BUILD_TESTS OFF CACHE BOOL "" FORCE)
FetchContent_MakeAvailable(cppzmq)

# ── Executable ────────────────────────────────────────────────────────────────
add_executable(hopefx_shim hopefx_shim.cpp)

target_include_directories(hopefx_shim PRIVATE
    ${ZMQ_INCLUDE_DIRS}
    ${cppzmq_SOURCE_DIR}
)

target_link_libraries(hopefx_shim PRIVATE
    ${ZMQ_LIBRARIES}
    pthread
)

target_compile_options(hopefx_shim PRIVATE
    ${ZMQ_CFLAGS_OTHER}
    -Wall -Wextra -Wpedantic
    # Reduce latency jitter: disable frame pointer for tighter stack frames
    -fomit-frame-pointer
    # Inline aggressively
    -finline-functions
)

# ── Install ───────────────────────────────────────────────────────────────────
install(TARGETS hopefx_shim DESTINATION bin)
