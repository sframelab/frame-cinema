#include "native_click_gate.h"
#include <cstdlib>
#include <iostream>
#include <limits>

int main() {
    using Gate = frame_native_ui::NativeClickGate;
    constexpr auto invalid = Gate::invalid_source;
    Gate gate;
    int checks = 0;
    const auto check = [&](bool ok, const char* name) {
        ++checks;
        if (!ok) { std::cerr << "FAIL: " << name << '\n'; std::exit(1); }
    };

    // No raw-controller API exists here: an initial native edge must work.
    check(gate.down(1, 1.0).accepted, "first Down without legacy state");
    check(!gate.down(1, 1.01).accepted, "duplicate Down suppressed");
    check(!gate.down(2, 1.02).accepted, "foreign Down cannot steal latch");
    check(!gate.up(2, 1.03), "foreign Up cannot clear latch");
    gate.focus_leave(2);
    check(gate.held_source() == 1, "foreign FocusLeave preserves latch");
    check(gate.up(1, 1.04), "matching Up releases");
    check(gate.up(1, 1.05), "Up without hold accepted");
    check(gate.down(1, 1.06).accepted, "fresh press after release");
    gate.focus_leave(1);
    check(gate.down(2, 1.07).accepted, "own FocusLeave releases");
    gate.reset();

    check(!gate.down(invalid, 2.0).accepted, "unknown source rejected");
    gate.move(1, 2.0);
    const auto fallback = gate.down(invalid, 2.20);
    check(fallback.accepted && fallback.used_hover && fallback.source == 1,
          "fresh valid hover attributes invalid button source");
    check(gate.up(invalid, 2.21), "fresh matching fallback releases");
    check(!gate.down(invalid, 2.251).accepted, "stale hover rejected");
    check(!gate.down(invalid, 1.99).accepted, "future hover rejected");
    gate.move(invalid, 2.26);
    check(!gate.down(invalid, 2.27).accepted, "invalid Move cannot refresh hover");
    gate.move(2, 2.3);
    gate.focus_leave(2);
    check(!gate.down(invalid, 2.31).accepted, "FocusLeave invalidates same-source hover");
    gate.move(1, 3.0);
    gate.reset();
    check(!gate.down(invalid, 3.01).accepted, "page/hide reset clears hover epoch");
    gate.move(1, 4.0);
    check(gate.down(invalid, 4.1).accepted, "second hover epoch works");
    gate.move(2, 4.11);
    check(!gate.up(invalid, 4.12) && gate.held_source() == 1,
          "other hand hover cannot release first hand latch");
    check(gate.up(1, 4.13), "explicit owner Up recovers despite other hover");
    check(!gate.down(1, std::numeric_limits<double>::quiet_NaN()).accepted,
          "nonfinite time rejected");
    std::cout << "PASS: " << checks << " native click gate checks\n";
}
