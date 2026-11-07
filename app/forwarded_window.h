#pragma once
#include <X11/Xlib.h>
#include <X11/Xatom.h>
#include <cstdint>

// The caller owns a private X display. A window property assigns its surface
// to our OpenVR overlay; a surface transfer must have one owner at a time.
inline void forward_window(Display* display,Atom target,uint64_t overlay,Window previous,Window next) {
    if (previous==next) return;
    // Both requests use this connection, so the old assignment is removed
    // before the replacement can start forwarding. A destroyed old XID is
    // harmless to the panel's existing X error handler.
    if (previous) XDeleteProperty(display,previous,target);
    if (next) {
        // Forwarded windows leave Gamescope's normal maximization path.
        XMoveResizeWindow(display,next,0,0,DisplayWidth(display,DefaultScreen(display)),DisplayHeight(display,DefaultScreen(display)));
        XSync(display,False);
        unsigned long values[]={static_cast<unsigned long>(overlay&0xffffffff),static_cast<unsigned long>(overlay>>32)};
        XChangeProperty(display,next,target,XA_CARDINAL,32,PropModeReplace,
                        reinterpret_cast<unsigned char*>(values),2);
    }
    XFlush(display);
}
