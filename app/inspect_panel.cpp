// Development-only, one-shot input on the cinema's private X display.
// The caller selects the window observed in a fresh screenshot.
#define main cinema_panel_main
#include "panel_host.cpp"
#undef main
#include <X11/Xutil.h>
#include <chrono>
#include <cstdlib>
#include <cstring>
#include <thread>
int main(int argc,char** argv) {
    if (argc!=5) return 2;
    auto* display=XOpenDisplay(nullptr);
    if (!display) return 3;
    const Window window=std::strtoul(argv[2],nullptr,0);
    const bool typing=std::strcmp(argv[1],"type")==0;
    const bool key=std::strcmp(argv[1],"key")==0;
    const std::string text=argv[3];
    if (typing && (text.empty() || text.size()>64 ||
        text.find_first_not_of("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 .,!?'-")!=std::string::npos)) {
        XCloseDisplay(display);return 2;
    }
    const int x=typing || key?0:std::atoi(argv[3]),y=typing || key?0:std::atoi(argv[4]);
    XClassHint hint{};
    XWindowAttributes size{};
    const bool known=XGetClassHint(display,window,&hint) && hint.res_class &&
        std::strcmp(hint.res_class,"Google-chrome")==0;
    if (hint.res_name) XFree(hint.res_name);
    if (hint.res_class) XFree(hint.res_class);
    if (!known || !XGetWindowAttributes(display,window,&size) ||
        x<0 || y<0 || x>=size.width || y>=size.height) { XCloseDisplay(display);return 4; }
    if (typing || key) {
        bool sent=true;
        if (typing) {
            for (const char character:text) {
                const char bytes[]={character,0};
                sent=keyboard_input(display,window,bytes) && sent;
            }
        } else if (text=="Backspace") sent=keyboard_input(display,window,"\b");
        else if (text=="Return") sent=keyboard_input(display,window,"\r");
        else if (text=="Left") sent=keyboard_input(display,window,"\x1b[D");
        else if (text=="Right") sent=keyboard_input(display,window,"\x1b[C");
        else { XCloseDisplay(display);return 2; }
        XSync(display,False);XCloseDisplay(display);
        return sent?0:5;
    }
    BrowserPointer pointer;
    pointer.move(display,window,x,y);
    if (std::strcmp(argv[1],"click")==0) {
        XSetInputFocus(display,window,RevertToParent,CurrentTime);
        pointer.click(display,window,x,y);
    } else if (std::strcmp(argv[1],"up")==0 || std::strcmp(argv[1],"down")==0)
        pointer.scroll(display,window,x,y,std::strcmp(argv[1],"up")==0?4:5);
    else if (std::strcmp(argv[1],"move")!=0) { XCloseDisplay(display);return 2; }
    XSync(display,False);XCloseDisplay(display);
    return pointer.failures?5:0;
}
