#include <X11/Xlib.h>
#include <X11/Xutil.h>
#include <chrono>
#include <thread>
int main(){
 auto*d=XOpenDisplay(nullptr);if(!d)return 1;
 auto w=XCreateSimpleWindow(d,DefaultRootWindow(d),0,0,1920,1080,0,0,0);
 XClassHint hint{const_cast<char*>("chrome"),const_cast<char*>("Chrome")};XSetClassHint(d,w,&hint);
 XStoreName(d,w,"Cinema synthetic display test");XMapWindow(d,w);auto gc=XCreateGC(d,w,0,nullptr);
 for(int frame=0;frame<1800;++frame){
  for(int y=0;y<6;++y)for(int x=0;x<10;++x){
   XSetForeground(d,gc,((x+y+frame/30)%2)?0x20c8e0:0xd03080);XFillRectangle(d,w,gc,x*192,y*180,192,180);
  }XFlush(d);std::this_thread::sleep_for(std::chrono::milliseconds(33));
 }
 XFreeGC(d,gc);XDestroyWindow(d,w);XCloseDisplay(d);
}
