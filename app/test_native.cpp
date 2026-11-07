#define main cinema_panel_entry
#include "panel_host.cpp"
#undef main
#include <gtk/gtk.h>
#include <gdk/gdkx.h>

static int failures = 0;
static void check(bool good, const char* label) {
    std::printf("%s %s\n", good ? "PASS" : "FAIL", label);
    if (!good) ++failures;
}
static GtkWidget* fields[3]{};
static int phase = 0;
static gboolean next_field(void*) {
    if (phase == 3) { gtk_main_quit(); return false; }
    gtk_widget_grab_focus(fields[phase++]);
    return true;
}
static int fixture() {
    gtk_init(nullptr,nullptr);
    auto* window = gtk_window_new(GTK_WINDOW_TOPLEVEL);
    auto* box = gtk_box_new(GTK_ORIENTATION_VERTICAL,4);
    gtk_container_add(GTK_CONTAINER(window),box);
    fields[0] = gtk_entry_new(); fields[1] = gtk_entry_new(); fields[2] = gtk_button_new_with_label("Synthetic button");
    gtk_entry_set_visibility(GTK_ENTRY(fields[1]),false);
    for (auto* field:fields) gtk_box_pack_start(GTK_BOX(box),field,true,true,0);
    gtk_widget_show_all(window);
    gtk_widget_grab_focus(fields[2]);
    auto* display = gdk_x11_display_get_xdisplay(gtk_widget_get_display(window));
    XSetInputFocus(display,gdk_x11_window_get_xid(gtk_widget_get_window(window)),RevertToParent,CurrentTime);
    g_timeout_add(1000,next_field,nullptr);
    gtk_main();
    gtk_widget_destroy(window);
    return 0;
}
int main(int argc,char** argv) {
    // Chrome can destroy a window between discovery and attribute queries.
    // Use the production handler; individual send/state assertions still fail.
    XSetErrorHandler(ignore_x_error);
    if (argc > 1 && std::strcmp(argv[1],"--fixture")==0) return fixture();
    if (argc > 2 && std::strcmp(argv[1],"--keyboard-preview")==0) {
        CinemaKeyboard keyboard;
        auto pixels=keyboard.pixels(CinemaKeyboard::texture_scale);
        for (size_t i=0;i<pixels.size();i+=4) {
            std::swap(pixels[i],pixels[i+2]);
            for (int channel=0;channel<3;++channel) pixels[i+channel]=unsigned(pixels[i+channel])*pixels[i+3]/255;
        }
        auto* surface=cairo_image_surface_create_for_data(pixels.data(),CAIRO_FORMAT_ARGB32,keyboard.texture_width,keyboard.texture_height,keyboard.texture_width*4);
        const int status=cairo_surface_write_to_png(surface,argv[2]);
        cairo_surface_destroy(surface);
        return status;
    }
    CinemaKeyboard keyboard;
    check(inspection_navigation_allowed(100,101,false,false), "fresh off-head navigation inspection is allowed");
    check(!inspection_navigation_allowed(100,101,true,false) && !inspection_navigation_allowed(100,101,false,true),
          "inspection refuses tracked controllers and an in-use headset");
    check(!inspection_navigation_allowed(0,1,false,false) && !inspection_navigation_allowed(100,99,false,false)
          && !inspection_navigation_allowed(100,103,false,false), "inspection refuses missing, future and expired timestamps");
    PointerSequence order;
    check(order.accept(3,100) && !order.accept(1,99) && !order.accept(2,100),
          "tracking cancellation rejects an older queued press and release");
    check(order.accept(0,103) && order.accept(1,101) && order.accept(2,102),
          "ordinary movement does not invalidate queued button events");
    check(order.accept(7,110) && !order.accept(3,109) && !order.accept(1,109) && order.accept(1,111),
          "focus cancellation stays monotonic and allows subsequent input");
    auto hi_pixels=keyboard.pixels(CinemaKeyboard::texture_scale);
    check(hi_pixels.size()==size_t(CinemaKeyboard::texture_width)*CinemaKeyboard::texture_height*4 && hi_pixels[3]==0, "high-density keyboard preserves dimensions and transparent corners");
    bool layout_good=true;
    for (size_t i=0;i<keyboard.keys.size();++i) {
        const auto& k=keyboard.keys[i];
        layout_good=layout_good && k.x>=0 && k.y>=0 && k.x+k.w<=keyboard.width && k.y+k.h<=keyboard.height &&
            keyboard.hit((k.x+k.w/2)/keyboard.width,(k.y+k.h/2)/keyboard.height)==int(i);
    }
    check(layout_good,"keyboard keys fit and their centres select the intended key");
    auto find_key=[&](const char* name) { for (size_t i=0;i<keyboard.keys.size();++i) if (keyboard.keys[i].normal==name) return int(i); return -1; };
    bool hide=false;
    keyboard.pressed=find_key("a");
    check(keyboard.release(find_key("s"),hide).empty(),"dragging off a keyboard key cancels it");
    keyboard.pressed=find_key("Shift"); keyboard.release(keyboard.pressed,hide);
    keyboard.pressed=find_key("2");
    check(keyboard.release(keyboard.pressed,hide)=="@" && !hide,"shifted number produces punctuation without closing keyboard");
    keyboard.pressed=find_key("Hide"); keyboard.release(keyboard.pressed,hide);
    check(hide,"Hide explicitly dismisses the app keyboard");
    const PointerVector start{.2f,1.2f,-.1f}, direction{0,0,-1}, eye{0,1.65f,0};
    const auto ray = beam_transform(start,direction,4.f,eye);
    const PointerVector midpoint{ray.m[0][3],ray.m[1][3],ray.m[2][3]};
    const PointerVector axis{ray.m[0][0],ray.m[1][0],ray.m[2][0]};
    check((midpoint-axis*2.f-start).length()<.0001f &&
          (midpoint+axis*2.f-(start+direction*4.f)).length()<.0001f,
          "compositor beam starts at controller and stops at hit distance");
    const auto aligned = beam_transform({0,0,0},{0,0,-1},3.f,{0,0,0});
    bool finite=true;
    for (const auto& row:aligned.m) for (float n:row) finite=finite && std::isfinite(n);
    check(finite,"viewer-aligned beam has a finite fallback basis");
    auto* display = XOpenDisplay(nullptr);
    if (!display) return 2;
    const auto window = XCreateSimpleWindow(display,DefaultRootWindow(display),0,0,400,300,0,0,0);
    XSelectInput(display,window,KeyPressMask);
    XMapWindow(display,window);
    XSetInputFocus(display,window,RevertToParent,CurrentTime);
    XSync(display,false);
    keyboard_input(display,window,"Ab1@!z");
    XSync(display,false);
    std::string received;
    while (XPending(display)) {
        XEvent event{}; XNextEvent(display,&event);
        if (event.type==KeyPress) {
            char buffer[16]; KeySym symbol;
            int count=XLookupString(&event.xkey,buffer,sizeof(buffer),&symbol,nullptr);
            received.append(buffer,count);
        }
    }
    check(received=="Ab1@!z","literal mixed-case and punctuation reach X input unchanged");
    keyboard_input(display,window,"\x1b[D");
    XSync(display,false);
    bool left=false;
    while (XPending(display)) { XEvent event{}; XNextEvent(display,&event); if (event.type==KeyPress && XLookupKeysym(&event.xkey,0)==XK_Left) left=true; }
    check(left,"keyboard arrow sequence becomes one Left key");
    keyboard_input(display,window,"\xce\xbb\xd0\x96");
    XSync(display,false);
    std::vector<KeySym> unicode;
    while (XPending(display)) {
        XEvent event{}; XNextEvent(display,&event);
        if (event.type==MappingNotify) XRefreshKeyboardMapping(&event.xmapping);
        if (event.type==KeyPress) unicode.push_back(XLookupKeysym(&event.xkey,0));
    }
    check(unicode==std::vector<KeySym>{0x010003bb,0x01000416},"multiple Unicode characters retain separate key mappings");
    const auto decoy=XCreateSimpleWindow(display,DefaultRootWindow(display),0,0,80,80,0,0,0);
    XMapWindow(display,decoy);XSetInputFocus(display,decoy,RevertToParent,CurrentTime);XSync(display,False);
    const auto restores_before=key_focus_restores;
    keyboard_input(display,window,"x");XSync(display,False);
    bool recovered=false;
    while (XPending(display)) { XEvent event{};XNextEvent(display,&event);if (event.type==KeyPress && event.xkey.window==window && XLookupKeysym(&event.xkey,0)==XK_x) recovered=true; }
    check(recovered && key_focus_restores==restores_before+1,"key dispatch restores focus from another X window before typing");
    XDestroyWindow(display,decoy);
    BrowserPointer pointer;
    XSelectInput(display,window,PointerMotionMask|ButtonPressMask|ButtonReleaseMask);
    pointer.press(display,window,40,50,1);
    pointer.release(display,window,80,90);XSync(display,False);
    bool down_ok=false,up_ok=false,drag_ok=false;
    while (XPending(display)) {
        XEvent event{};XNextEvent(display,&event);
        if (event.type==ButtonPress) down_ok=event.xbutton.x==40 && event.xbutton.y==50 && event.xbutton.state==0;
        if (event.type==MotionNotify && event.xmotion.x==80) drag_ok=(event.xmotion.state&Button1Mask)!=0;
        if (event.type==ButtonRelease) up_ok=event.xbutton.x==80 && event.xbutton.y==90 && event.xbutton.state==Button1Mask;
    }
    check(down_ok && up_ok && drag_ok && !pointer.captured,"browser click carries press drag and release coordinates with correct button state");
    pointer.press(display,window,40,50,1);
    pointer.move(display,window,46,55);
    pointer.release(display,window,45,54);XSync(display,False);
    bool jitter_fixed=false,small_drag=false;
    while (XPending(display)) {
        XEvent event{};XNextEvent(display,&event);
        if (event.type==MotionNotify && (event.xmotion.state&Button1Mask)) small_drag=small_drag || event.xmotion.x!=40 || event.xmotion.y!=50;
        if (event.type==ButtonRelease) jitter_fixed=event.xbutton.x==40 && event.xbutton.y==50;
    }
    check(jitter_fixed && !small_drag,"trigger jitter retains a small link's original click without starting a text selection");
    pointer.press(display,window,40,50,1);
    for (int i=0;i<20;++i) pointer.move(display,window,40+i%3,50);
    pointer.release(display,window,40,50);XSync(display,False);
    int stationary_downs=0,stationary_ups=0,held_moves=0;
    while (XPending(display)) {
        XEvent event{};XNextEvent(display,&event);
        if (event.type==ButtonPress) ++stationary_downs;
        if (event.type==ButtonRelease) ++stationary_ups;
        if (event.type==MotionNotify && (event.xmotion.state&Button1Mask)) ++held_moves;
    }
    check(stationary_downs==1 && stationary_ups==1 && held_moves==0,
          "a steady or stabilized trigger tap emits no false drag motion");
    const bool activated=pointer.click(display,window,40,50);
    pointer.move(display,window,110,85);
    pointer.release(display,window,110,85);XSync(display,False);
    int activation_downs=0,activation_ups=0,activation_drags=0;bool same_point=true;
    while (XPending(display)) {
        XEvent event{};XNextEvent(display,&event);
        if (event.type==ButtonPress || event.type==ButtonRelease) {
            same_point=same_point && event.xbutton.x==40 && event.xbutton.y==50;
            if (event.type==ButtonPress) ++activation_downs;else ++activation_ups;
        }
        if (event.type==MotionNotify && (event.xmotion.state&Button1Mask)) ++activation_drags;
    }
    check(activated && activation_downs==1 && activation_ups==1 && same_point && activation_drags==0 && !pointer.button,
          "browser activation clicks its initial point once; later squeeze motion is hover only");
    XUnmapWindow(display,window);XSync(display,False);
    const auto failures_before=pointer.failures;
    pointer.move(display,window,41,51);
    XMapWindow(display,window);XSync(display,False);
    pointer.move(display,window,41,51);XSync(display,False);
    bool retried=false;
    while (XPending(display)) { XEvent event{};XNextEvent(display,&event);if (event.type==MotionNotify && event.xmotion.x==41 && event.xmotion.y==51) retried=true; }
    check(pointer.failures==failures_before+1 && retried,"failed motion retries the same coordinates after remapping");
    pointer.press(display,window,40,50,1);
    pointer.move(display,window,65,50);
    pointer.release(display,window,43,50);XSync(display,False);
    bool drag_return=false;
    while (XPending(display)) { XEvent event{};XNextEvent(display,&event);if (event.type==ButtonRelease) drag_return=event.xbutton.x==43; }
    check(drag_return,"an intentional drag stays free when it returns near the press point");
    const auto replacement=XCreateSimpleWindow(display,DefaultRootWindow(display),0,0,200,100,0,0,0);
    XMapWindow(display,replacement);XSync(display,False);
    pointer.press(display,window,40,50,1);pointer.release(display,replacement,40,50);XSync(display,False);
    bool cancelled=false,wrong_target=false;
    while (XPending(display)) {
        XEvent event{};XNextEvent(display,&event);
        if (event.type==ButtonRelease) {
            cancelled=event.xbutton.window==window && event.xbutton.x==-1 && event.xbutton.y==-1;
            wrong_target=event.xbutton.window==replacement;
        }
    }
    check(cancelled && !wrong_target && !pointer.button,"window replacement cancels on original window outside its content");
    pointer.press(display,window,40,50,1);pointer.cancel(display);XSync(display,False);
    cancelled=false;
    while (XPending(display)) { XEvent event{};XNextEvent(display,&event);if (event.type==ButtonRelease) cancelled=event.xbutton.x==-1 && event.xbutton.y==-1; }
    check(cancelled && !pointer.button && pointer.cancels==2,"tracking or dashboard cancellation releases outside the pressed page");
    XDestroyWindow(display,replacement);
    XDestroyWindow(display,window); XCloseDisplay(display);

    EditableFocus focus; focus.start();
    check(focus.available,"accessibility focus listener starts");
    bool plain=false,password=false,cleared=false;
    auto child=fork();
    if (!child) {
        if (argc > 2 && std::strcmp(argv[1],"--chrome")==0) {
            const std::string profile=std::string("--user-data-dir=")+argv[2];
            const char* page="--app=data:text/html,<title>Cinema input fixture</title><input id=e><input id=p type=password><button id=b autofocus>Fixture</button><script>setTimeout(()=>e.focus(),2500);setTimeout(()=>p.focus(),5000);setTimeout(()=>b.focus(),7500);setTimeout(()=>window.close(),9500)</script>";
            execlp("flatpak","flatpak","run","--user","--env=ACCESSIBILITY_ENABLED=1","--env=NO_AT_BRIDGE=0","com.google.Chrome",profile.c_str(),"--no-first-run","--no-default-browser-check","--disable-gpu","--force-renderer-accessibility","--ozone-platform=x11",page,nullptr);
        } else execl(argv[0],argv[0],"--fixture",nullptr);
        _exit(127);
    }
    int status=0;
    auto* fixture_display = argc > 2 ? XOpenDisplay(nullptr) : nullptr;
    Window fixture_window=0;
    while (waitpid(child,&status,WNOHANG)==0) {
        // Xvfb has no window manager to focus Chrome's newly mapped window.
        if (fixture_display && !fixture_window) {
            fixture_window=browser_window(fixture_display,DefaultRootWindow(fixture_display));
            if (fixture_window) { XSetInputFocus(fixture_display,fixture_window,RevertToParent,CurrentTime); XFlush(fixture_display); }
        }
        focus.poll();
        if (focus.editable && !focus.password) plain=true;
        if (focus.editable && focus.password) password=true;
        if (password && !focus.editable && !focus.request) cleared=true;
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }
    if (fixture_display) XCloseDisplay(fixture_display);
    check(plain,"owned editable field requests keyboard");
    check(password,"owned password field selects password mode");
    check(cleared,"moving to button cancels pending keyboard request");
    for (int i=0;i<20;++i) { focus.poll(); std::this_thread::sleep_for(std::chrono::milliseconds(10)); }
    const auto before=focus.events;
    child=fork();
    if (!child) { setsid(); execl(argv[0],argv[0],"--fixture",nullptr); _exit(127); }
    while (waitpid(child,&status,WNOHANG)==0) { focus.poll(); std::this_thread::sleep_for(std::chrono::milliseconds(10)); }
    check(before==focus.events,"unrelated process group cannot request our keyboard");
    std::printf("Native regression failures: %d\n",failures);
    return failures ? 1 : 0;
}
