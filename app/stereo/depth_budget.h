#pragma once
#include <algorithm>
namespace cinema_stereo {
enum class BudgetAction { Keep, Lower, Stop };
// Shader/pipeline creation and its immediate backlog are not steady-state
// capacity. This grace never bypasses fresh color/depth or presentation gates.
struct DepthBudget {
    double started=-1;
    int late_frames=0;
    void reset(){started=-1;late_frames=0;}
    BudgetAction update(bool late,bool paused,bool fixed,int width,double now){
        if(started<0||now<started)started=now;
        if(paused||now-started<2.){late_frames=0;return BudgetAction::Keep;}
        late_frames=late?late_frames+1:std::max(0,late_frames-1);
        if(!fixed&&width>256&&late_frames>=4)return BudgetAction::Lower;
        if(!fixed&&width==256&&late_frames>=12)return BudgetAction::Stop;
        return BudgetAction::Keep;
    }
};
}
