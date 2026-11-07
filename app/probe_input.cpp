// Read-only diagnostics on the cinema's private X display and owned browser.
// Count events only: never read keycodes, accessible names, values, or text.
#include <X11/Xlib.h>
#include <X11/extensions/record.h>
#include <X11/extensions/XTest.h>
#include <X11/keysym.h>
#include <atspi/atspi.h>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <thread>
#include <atomic>
#include "editable_focus.h"

static pid_t browser_group=0;
static std::atomic<unsigned> text_events{0}, focus_events{0}, delivered{0}, device{0};
static void accessibility(AtspiEvent* event,void*) {
    if (event->source) {
        const auto pid=EditableFocus::sender_pid(ATSPI_OBJECT(event->source));
        if (pid && getpgid(pid)==browser_group) {
            if (std::string(event->type).find("text-changed")!=std::string::npos) ++text_events;
            else ++focus_events;
        }
    }
    g_boxed_free(ATSPI_TYPE_EVENT,event);
}
static void recorded(XPointer kind,XRecordInterceptData* data) {
    if (data->category==XRecordFromServer && data->data_len) {
        // The range has only keyboard press/release events; count packets,
        // without examining key codes or their translated characters.
        if (kind) ++delivered;else ++device;
    }
    XRecordFreeData(data);
}
int main(int argc,char** argv) {
    if (argc<3 || (browser_group=std::atoi(argv[1]))<=1) return 2;
    XInitThreads();
    const int seconds=std::min(90,std::max(1,std::atoi(argv[2])));
    atspi_init();atspi_set_timeout(150,150);
    auto* listener=atspi_event_listener_new(accessibility,nullptr,nullptr);
    atspi_event_listener_register(listener,"object:text-changed",nullptr);
    atspi_event_listener_register(listener,"object:state-changed:focused",nullptr);
    auto* control=XOpenDisplay(nullptr);auto* stream=XOpenDisplay(nullptr);
    if (!control || !stream) return 3;
    XRecordClientSpec clients=XRecordAllClients;
    XRecordContext contexts[2]{};
    for (int i=1;i<2;++i) {
        auto* range=XRecordAllocRange();
        if (i) { range->delivered_events.first=KeyPress;range->delivered_events.last=KeyRelease; }
        else { range->device_events.first=KeyPress;range->device_events.last=KeyRelease; }
        contexts[i]=XRecordCreateContext(control,0,&clients,1,&range,1);XFree(range);XSync(control,False);
        XRecordEnableContextAsync(stream,contexts[i],recorded,reinterpret_cast<XPointer>(i));
    }
    std::puts("READY counting only owned text-change events and private-display keyboard packets");std::fflush(stdout);
    // XRecordProcessReplies can block while there are no keyboard events.
    std::thread([stream] { for (;;) XRecordProcessReplies(stream); }).detach();
    if (argc==4 && std::string(argv[3])=="--pulse-shift") {
        auto key=XKeysymToKeycode(control,XK_Shift_L);
        int down=XTestFakeKeyEvent(control,key,True,CurrentTime);
        int up=XTestFakeKeyEvent(control,key,False,CurrentTime);XSync(control,False);
        std::printf("PULSE modifier only, XTest return values %d %d\n",down,up);std::fflush(stdout);
    }
    if (argc==4 && std::string(argv[3])=="--send-shift") {
        Window focused=0;int revert=0;XGetInputFocus(control,&focused,&revert);
        XEvent event{};event.xkey.display=control;event.xkey.window=focused;
        event.xkey.root=DefaultRootWindow(control);event.xkey.same_screen=True;
        event.xkey.keycode=XKeysymToKeycode(control,XK_Shift_L);
        event.xkey.type=KeyPress;int down=XSendEvent(control,focused,True,KeyPressMask,&event);
        event.xkey.type=KeyRelease;int up=XSendEvent(control,focused,True,KeyReleaseMask,&event);
        XSync(control,False);
        std::printf("PULSE modifier only, direct X return values %d %d\n",down,up);std::fflush(stdout);
    }
    auto until=std::chrono::steady_clock::now()+std::chrono::seconds(seconds);
    while (std::chrono::steady_clock::now()<until) {
        for (int i=0;i<8 && g_main_context_pending(nullptr);++i) g_main_context_iteration(nullptr,false);
        std::this_thread::sleep_for(std::chrono::milliseconds(20));
    }
    std::printf("COUNTS text_changes=%u focus_events=%u delivered_key_packets=%u\n",text_events.load(),focus_events.load(),delivered.load());std::fflush(stdout);
    // Closing the process also closes both X clients and their record context.
    _exit(0);
}
