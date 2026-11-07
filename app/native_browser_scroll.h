#pragma once
#include <algorithm>
#include <cmath>
#include <cstdint>

// Native wheel delivery, with one pointer placement per continuous gesture.
// No easing, accumulated tail, retries, or invented wheel distance.
struct NativeBrowserScroll {
    uint64_t target=0, sent=0, rejected=0, placements=0;
    double last=0;
    static constexpr double idle_seconds=.120, max_event_age=.100;
    void cancel(){target=0;last=0;}

    template<class Position,class Post>
    bool send(uint64_t window,int x,int y,int width,int height,double dx,double dy,
              double age,double now,Position position,Post post){
        if(!window||width<1||height<1||x<0||y<0||x>=width||y>=height
           ||!std::isfinite(dx)||!std::isfinite(dy)||!std::isfinite(age)
           ||!std::isfinite(now)||age<0||age>max_event_age||(!dx&&!dy)){
            ++rejected;return false;
        }
        if(target!=window||now<last||now-last>idle_seconds){
            cancel();
            if(!position(x,y)){++rejected;return false;}
            target=window;++placements;
        }
        // Same bound as the committed producer, in Steam wheel units.
        post(std::clamp(dx,-3.,3.),std::clamp(dy,-3.,3.));
        last=now;++sent;return true;
    }
};
