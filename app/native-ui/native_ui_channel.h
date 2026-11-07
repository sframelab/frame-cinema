#pragma once
#include <atomic>
#include <cstdint>
#include <cstddef>
struct NativeUIChannel {
    static constexpr size_t capacity=16*1024*1024;
    std::atomic<uint64_t> request{0},complete{0};
    std::atomic<int> ready{0},stop{0};
    std::atomic<uint64_t> shortcuts[8]{};
    std::atomic<int> shortcut_error{0};
    std::atomic<unsigned> shortcut_active{0};
    std::atomic<unsigned> shortcut_components{0};
    uint64_t handle=0,parent_start=0;
    uint32_t parent=0,width=0,height=0;
    int error=0;
    uint64_t submissions=0,allocations=0;
    alignas(64) unsigned char pixels[capacity];
};
static_assert(std::atomic<uint64_t>::is_always_lock_free);
