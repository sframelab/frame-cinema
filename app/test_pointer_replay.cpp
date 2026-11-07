// Disposable-browser test driver: replay only mouse coordinates and timings.
#include "browser_pointer.h"
#include <X11/Xutil.h>
#include <chrono>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <thread>
int main(int argc,char** argv) {
    if (argc!=3 || (std::strcmp(argv[1],"atomic") && std::strcmp(argv[1],"legacy"))) return 2;
    auto* display=XOpenDisplay(nullptr);if (!display) return 3;
    const auto window=std::strtoul(argv[2],nullptr,0);XClassHint hint{};
    const bool known=XGetClassHint(display,window,&hint) && hint.res_class && !std::strcmp(hint.res_class,"Google-chrome");
    if(hint.res_name)XFree(hint.res_name);
    if(hint.res_class)XFree(hint.res_class);
    if (!known) { XCloseDisplay(display);return 4; }
    XSetInputFocus(display,window,RevertToParent,CurrentTime);
    BrowserPointer pointer;bool held=false;int ms=0,type=0,x=0,y=0,previous=0,count=0;
    const auto start=std::chrono::steady_clock::now();
    while (std::cin>>ms>>type>>x>>y) {
        if (++count>1000 || ms<previous || ms>10000 || (type!=4 && type!=5 && type!=6)) return 5;
        previous=ms;std::this_thread::sleep_until(start+std::chrono::milliseconds(ms));
        if (type==4 && !held) {
            held=true;
            if (!std::strcmp(argv[1],"atomic")) pointer.click(display,window,x,y);
            else pointer.press(display,window,x,y,1);
        } else if (type==5 && held) {
            held=false;pointer.release(display,window,x,y);
        } else if (type==6) pointer.move(display,window,x,y);
        XFlush(display);
    }
    pointer.cancel(display);XSync(display,False);XCloseDisplay(display);
    return pointer.failures?6:0;
}
