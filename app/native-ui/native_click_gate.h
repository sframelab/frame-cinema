#pragma once
#include <cmath>
#include <cstdint>
#include <limits>

namespace frame_native_ui {

// Caller supplies monotonic seconds and only connected, tracked controller IDs.
// Sanitize every other event source to invalid_source. Reset on hide, layout/
// page change or ownership change; drain old overlay events before first Show.
// This gate deliberately has no dependency on legacy/raw controller state.
class NativeClickGate {
public:
    using Source = std::uint32_t;
    static constexpr Source invalid_source = std::numeric_limits<Source>::max();
    static constexpr double hover_fresh_seconds = 0.250;
    enum class Rejection { none, unknown_source, duplicate_down, foreign_hold };
    struct Press {
        bool accepted = false;
        Source source = invalid_source;
        bool used_hover = false;
        Rejection rejection = Rejection::unknown_source;
    };

    void move(Source source, double now) {
        if (source == invalid_source || !valid_time(now)) return;
        // A backwards clock/event must not make an old hover newly fresh.
        if (hover_source_ != invalid_source && now < hover_time_) return;
        hover_source_ = source;
        hover_time_ = now;
    }

    Press down(Source source, double now) {
        const bool fallback = source == invalid_source;
        source = resolve(source, now);
        if (source == invalid_source) return {};
        if (held_source_ != invalid_source) {
            return {false, source, fallback, held_source_ == source
                ? Rejection::duplicate_down : Rejection::foreign_hold};
        }
        held_source_ = source;
        // Emit one complete same-position UI click only for accepted Down.
        return {true, source, fallback, Rejection::none};
    }

    // Up never emits a click. A recognized Up succeeds even if there is no
    // current hold; an Up from another source cannot release the current one.
    bool up(Source source, double now) {
        source = resolve(source, now);
        if (source == invalid_source) return false;
        if (held_source_ != invalid_source && held_source_ != source) return false;
        held_source_ = invalid_source;
        return true;
    }

    // FocusLeave is source-specific, without hover attribution. A global
    // hide/ownership loss calls reset() instead.
    void focus_leave(Source source) {
        if (source == invalid_source) return;
        if (held_source_ == source) held_source_ = invalid_source;
        if (hover_source_ == source) {
            hover_source_ = invalid_source;
            hover_time_ = -1.0;
        }
    }

    void reset() {
        held_source_ = hover_source_ = invalid_source;
        hover_time_ = -1.0;
    }
    Source held_source() const { return held_source_; }

private:
    static bool valid_time(double now) { return std::isfinite(now) && now >= 0.0; }
    Source resolve(Source source, double now) const {
        if (!valid_time(now)) return invalid_source;
        if (source != invalid_source) return source;
        const double age = now - hover_time_;
        return hover_source_ != invalid_source && age >= 0.0 && age <= hover_fresh_seconds
            ? hover_source_ : invalid_source;
    }
    Source held_source_ = invalid_source;
    Source hover_source_ = invalid_source;
    double hover_time_ = -1.0;
};

} // namespace frame_native_ui
