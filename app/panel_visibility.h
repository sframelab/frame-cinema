#pragma once
#include <cstdint>
#include <cstdio>
#include <deque>
#include <fstream>
#include <iomanip>
#include <string>

// A bounded history of our own screen state. No URLs, field values, images,
// input coordinates or room poses. The runtime visibility bit is only a hint:
// it cannot establish that the compositor actually displayed video pixels.
struct PanelVisibilityState {
    double time=0;
    bool ready=false, visible=false, attached=false, dashboard=false, keyboard=false;
    uint64_t generation=0, revision=0, clicks=0, reset_count=0, window=0;
    uint32_t reset_event=0;
    int width_error=0, transform_error=0, visibility_error=0;
    float width=0;
    std::string reason;
};

class PanelVisibilityHistory {
    std::deque<PanelVisibilityState> events;
    uint64_t transitions=0;
    static void text(std::ostream& out,const std::string& value) {
        out << '"';
        for (unsigned char c:value) {
            if (c=='"' || c=='\\') out << '\\' << c;
            else if (c>=32) out << c;
        }
        out << '"';
    }
public:
    static constexpr size_t capacity=32;
    bool same(const PanelVisibilityState& s) const {
        if (events.empty()) return false;
        const auto& p=events.back();
        return p.ready==s.ready && p.visible==s.visible && p.attached==s.attached
            && p.dashboard==s.dashboard && p.keyboard==s.keyboard
            && p.generation==s.generation && p.revision==s.revision && p.width==s.width && p.window==s.window
            && p.reason==s.reason && p.reset_count==s.reset_count && p.reset_event==s.reset_event
            && p.width_error==s.width_error && p.transform_error==s.transform_error
            && p.visibility_error==s.visibility_error;
    }
    bool record(const PanelVisibilityState& s) {
        if (same(s)) return false;
        if (events.size()==capacity) events.pop_front();
        events.push_back(s);++transitions;return true;
    }
    size_t size() const { return events.size(); }
    void write(std::ostream& out) const {
        out << std::setprecision(16) << "{\"transitions\":" << transitions << ",\"events\":[";
        bool first=true;
        for (const auto& s:events) {
            if (!first) out << ',';
            first=false;
            out << "{\"time\":" << s.time << ",\"ready\":" << (s.ready?"true":"false")
                << ",\"visible\":" << (s.visible?"true":"false")
                << ",\"attached\":" << (s.attached?"true":"false")
                << ",\"dashboard\":" << (s.dashboard?"true":"false")
                << ",\"keyboard\":" << (s.keyboard?"true":"false")
                << ",\"generation\":" << s.generation << ",\"revision\":" << s.revision
                << ",\"width\":" << s.width << ",\"clicks\":" << s.clicks
                << ",\"window\":" << s.window
                << ",\"reset_count\":" << s.reset_count << ",\"reset_event\":" << s.reset_event
                << ",\"width_error\":" << s.width_error << ",\"transform_error\":" << s.transform_error
                << ",\"visibility_error\":" << s.visibility_error << ",\"reason\":";
            text(out,s.reason);out << '}';
        }
        out << "]}";
    }
    bool save(const std::string& path) const {
        std::ofstream out(path+".tmp");write(out);out.close();
        return out && std::rename((path+".tmp").c_str(),path.c_str())==0;
    }
};
