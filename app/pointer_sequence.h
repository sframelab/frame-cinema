#pragma once
#include <cstdint>

// The newest heartbeat is read before the queued button events. A cancellation
// therefore invalidates older queued events, even if they have not been read yet.
struct PointerSequence {
    uint64_t cancelled_through=0;
    bool accept(int kind,uint64_t sequence) {
        if (sequence<=cancelled_through) return false;
        if (kind==3 || kind==7) cancelled_through=sequence;
        return true;
    }
};
