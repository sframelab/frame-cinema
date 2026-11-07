#pragma once
#include <X11/Xlib.h>

// Mouse capture belongs to one private browser window. Events never propagate
// to a compositor ancestor, and a cancelled press releases outside the page.
struct BrowserPointer {
    Window captured=0, hovered=0;
    unsigned button=0, moves=0, downs=0, ups=0, cancels=0, failures=0;
    int x=0,y=0;
    int press_x=0,press_y=0;
    bool dragging=false;
    // A trigger squeeze can move a VR ray a few pixels. Retain a small press
    // dead zone; intentional drags and explicit cancellation still leave it.
    void stabilize(int& px,int& py) {
        if (!captured || !button || dragging) return;
        const int dx=px-press_x,dy=py-press_y;
        if (px<0 || py<0 || dx*dx+dy*dy>144) { dragging=true;return; }
        px=press_x;py=press_y;
    }
    static unsigned mask(unsigned b) { return b>=1 && b<=5 ? 1u<<(7+b) : 0; }
    bool send(Display* d,Window window,int type,int px,int py,unsigned b,unsigned state) {
        XWindowAttributes a{};Window child=0;int rx=0,ry=0;
        if (!window || !XGetWindowAttributes(d,window,&a) || a.map_state!=IsViewable ||
            !XTranslateCoordinates(d,window,DefaultRootWindow(d),px,py,&rx,&ry,&child)) {
            ++failures;return false;
        }
        XEvent event{};
        if (type==MotionNotify) {
            event.xmotion={type,0,True,d,window,DefaultRootWindow(d),None,CurrentTime,
                px,py,rx,ry,state,NotifyNormal,True};
        } else {
            event.xbutton={type,0,True,d,window,DefaultRootWindow(d),None,CurrentTime,
                px,py,rx,ry,state,b,True};
        }
        if (!XSendEvent(d,window,False,NoEventMask,&event)) { ++failures;return false; }
        return true;
    }
    void move(Display* d,Window window,int px,int py) {
        if (captured && captured!=window) { cancel(d);return; }
        stabilize(px,py);
        // Repeating a held move at identical coordinates looks like a drag to
        // carousel/tap handlers, including the release-time move.
        if (hovered==window && x==px && y==py) return;
        if (send(d,window,MotionNotify,px,py,0,mask(button))) {
            hovered=window;x=px;y=py;++moves;
        } else hovered=0;
    }
    bool press(Display* d,Window window,int px,int py,unsigned b) {
        if (button || b<1 || b>3) return false;
        move(d,window,px,py);
        if (!send(d,window,ButtonPress,px,py,b,0)) return false;
        captured=window;button=b;press_x=px;press_y=py;dragging=false;++downs;return true;
    }
    void release(Display* d,Window window,int px,int py) {
        if (!captured || !button) return;
        // A replaced window cannot receive the old window's release.
        if (window!=captured) { cancel(d);return; }
        stabilize(px,py);
        move(d,captured,px,py);
        if (send(d,captured,ButtonRelease,px,py,button,mask(button))) ++ups;
        captured=0;button=0;
    }
    bool click(Display* d,Window window,int px,int py,unsigned b=1) {
        // Browser triggers select at press time. Finish the X click before
        // subsequent hand motion so a squeeze cannot become a page drag.
        if (!press(d,window,px,py,b)) return false;
        const auto before=ups;
        release(d,window,px,py);
        return ups==before+1;
    }
    void cancel(Display* d) {
        dragging=true;
        if (captured && button) {
            move(d,captured,-1,-1);
            if (send(d,captured,ButtonRelease,-1,-1,button,mask(button))) ++ups;
            ++cancels;
        } else if (hovered) move(d,hovered,-1,-1);
        captured=0;button=0;hovered=0;
    }
    void leave(Display* d) {
        if (hovered) move(d,hovered,-1,-1);
        if (!captured) hovered=0;
    }
    void scroll(Display* d,Window window,int px,int py,unsigned b) {
        if (b!=4 && b!=5) return;
        move(d,window,px,py);
        send(d,window,ButtonPress,px,py,b,mask(button));
        send(d,window,ButtonRelease,px,py,b,mask(button)|mask(b));
    }
};
