#pragma once
#include <cmath>
#include <istream>
#include <string>

namespace cinema_controller {
inline bool focused(std::istream& input, const std::string& session, unsigned long scene_pid, double now) {
    std::string magic, owner, extra; unsigned long pid=0; double stamp=0; int flag=0;
    if (!(input>>magic>>owner>>pid>>stamp>>flag) || input>>extra) return false;
    return magic=="FCCF1" && owner==session && scene_pid && pid==scene_pid && flag==1 &&
        std::isfinite(stamp) && std::isfinite(now) && now>=stamp && now-stamp<.15;
}
}
