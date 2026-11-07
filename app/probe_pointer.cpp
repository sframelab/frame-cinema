// Read-only, bounded mouse diagnostics for one owned private browser window.
// Never subscribes to keyboard events or reads page/field contents.
#include <X11/Xlib.h>
#include <X11/Xproto.h>
#include <X11/extensions/record.h>
#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <thread>
#include <unistd.h>

static Window target=0;
static auto started=std::chrono::steady_clock::now();
static void recorded(XPointer, XRecordInterceptData* data) {
    if (data->category==XRecordFromServer && !data->client_swapped) {
        for (unsigned long offset=0; offset+sizeof(xEvent)<=data->data_len*4; offset+=sizeof(xEvent)) {
            const auto& e=*reinterpret_cast<const xEvent*>(data->data+offset);
            const unsigned type=e.u.u.type&0x7f;
            const auto& p=e.u.keyButtonPointer;
            if (p.event!=target || type<ButtonPress || type>MotionNotify) continue;
            // Hover is high volume; only retain held motion and button edges.
            if (type==MotionNotify && !(p.state&Button1Mask)) continue;
            const auto ms=std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now()-started).count();
            std::printf("{\"ms\":%ld,\"type\":%u,\"button\":%u,\"x\":%d,\"y\":%d,\"state\":%u,\"synthetic\":%s}\n",
                ms,type,type==MotionNotify?0:e.u.u.detail,p.eventX,p.eventY,p.state,(e.u.u.type&0x80)?"true":"false");
            std::fflush(stdout);
        }
    }
    XRecordFreeData(data);
}
int main(int argc,char** argv) {
    if (argc!=3 || !(target=std::strtoul(argv[1],nullptr,0))) return 2;
    const int seconds=std::clamp(std::atoi(argv[2]),1,1800);
    XInitThreads();
    auto* control=XOpenDisplay(nullptr);auto* stream=XOpenDisplay(nullptr);
    if (!control || !stream) return 3;
    XWindowAttributes attributes{};
    if (!XGetWindowAttributes(control,target,&attributes)) return 4;
    XRecordClientSpec clients=XRecordAllClients;
    auto* range=XRecordAllocRange();
    range->delivered_events.first=ButtonPress;range->delivered_events.last=MotionNotify;
    auto context=XRecordCreateContext(control,0,&clients,1,&range,1);XFree(range);XSync(control,False);
    if (!context || !XRecordEnableContextAsync(stream,context,recorded,nullptr)) return 5;
    std::puts("{\"ready\":true}");std::fflush(stdout);
    std::thread([stream] { for (;;) XRecordProcessReplies(stream); }).detach();
    std::this_thread::sleep_for(std::chrono::seconds(seconds));
    std::puts("{\"complete\":true}");std::fflush(stdout);
    _exit(0);
}
