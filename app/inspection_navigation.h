#pragma once
#include <cmath>

// Only a fresh off-head inspection action can cross dashboard ownership.
// Ordinary controller/pointer events never carry this timestamp.
inline bool inspection_navigation_allowed(double created, double now, bool controller_tracked, bool headset_in_use) {
    return std::isfinite(created) && created > 0 && now >= created && now-created < 2.0
        && !controller_tracked && !headset_in_use;
}
