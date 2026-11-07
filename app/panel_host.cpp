// Presents one window from this app's private Gamescope display as a scene overlay.
// Gamescope forwards 2D. The optional stereo worker reads only a small depth-model input.
#include "stereo/stereo_bridge.h"
#include "openvr.h"
#include <X11/Xlib.h>
#include <X11/Xatom.h>
#include <X11/Xutil.h>
#include <X11/keysym.h>
#include <X11/XKBlib.h>
#include <X11/extensions/XTest.h>
#include <algorithm>
#include <chrono>
#include <cctype>
#include <cstring>
#include <cmath>
#include <csignal>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <memory>
#include <filesystem>
#include <vector>
#include <string>
#include <thread>
#include <sys/wait.h>
#include <unistd.h>
#include "editable_focus.h"
#include "pointer_geometry.h"
#include "cinema_keyboard.h"
#include "browser_pointer.h"
#include "pointer_sequence.h"
#include "pointer_frame.h"
#include "inspection_navigation.h"
#include "scene_placement.h"
#include "screen_layout.h"
#include "overlay_projection.h"
#include "pose_history.h"
#include "panel_visibility.h"
#include "forwarded_window.h"
#include "ambient_worker.h"
#include "panel_presentation.h"
#include "system_browser_input.h"
#include "scene_owner_adapter.h"
#include "browser_scroll.h"
#include "native_browser_scroll.h"
#include <sstream>
static bool unified_ui=false;
static bool stereo_active=false;
static unsigned transport_hide_errors=0;
static bool native_ui_handoff(const std::string& ipc,const std::string& session,uint32_t scene) {
    std::ifstream input(ipc+"/native-ui.txt");
    std::string magic,owner,extra;uint64_t pid=0;double stamp=0;int active=0;
    const double now=std::chrono::duration<double>(std::chrono::system_clock::now().time_since_epoch()).count();
    return (input>>magic>>owner>>pid>>stamp>>active)&&!(input>>extra)
        &&magic=="FCNUI1"&&owner==session&&pid==scene&&active==1
        &&std::isfinite(stamp)&&now>=stamp&&now-stamp<=.25;
}
static cinema_system_browser::State system_pointer;
static cinema_system_browser::HoverSources native_sources;
static uint64_t observed_browser_downs=0,observed_browser_ups=0,native_moves=0,native_downs=0,native_ups=0;
static uint64_t native_source_rejects=0,native_gate_rejects=0,native_hover_attributions=0;
static unsigned system_pointer_errors=0,system_pointer_entries=0,system_pointer_returns=0;
static PanelPresentation presentation;
static BrowserPointer browser_pointer;
static SmoothBrowserScroll smooth_scroll;
static NativeBrowserScroll native_scroll;
static PointerSequence pointer_sequence;
static bool keyboard_auto_suppressed=false;
// Aggregate timing only: no ray positions, page data or typed characters.
struct InputTiming {
    uint64_t count=0, total_us=0, maximum_us=0, over_50ms=0;
    void add(uint64_t microseconds) {
        ++count;total_us+=microseconds;maximum_us=std::max(maximum_us,microseconds);
        if (microseconds>50000) ++over_50ms;
    }
    void write(std::ostream& out) const {
        out << "{\"count\":" << count << ",\"mean_us\":" << (count?total_us/count:0)
            << ",\"max_us\":" << maximum_us << ",\"over_50ms\":" << over_50ms << '}';
    }
};
static InputTiming event_queue_timing, focus_poll_timing, input_work_timing;

static volatile std::sig_atomic_t running = 1;
static volatile std::sig_atomic_t stop_signal = 0;
static void stop(int value) { stop_signal = value; running = 0; }
static unsigned x_errors=0, key_send_failures=0;
static int ignore_x_error(Display*, XErrorEvent*) { ++x_errors;return 0; }
static bool window_fullscreen(Display* display,Window window) {
    Atom type=None;int format=0;unsigned long count=0,left=0;unsigned char* data=nullptr;
    const Atom full=XInternAtom(display,"_NET_WM_STATE_FULLSCREEN",False);
    XGetWindowProperty(display,window,XInternAtom(display,"_NET_WM_STATE",False),0,64,
                       False,XA_ATOM,&type,&format,&count,&left,&data);
    bool found=false;
    if (type==XA_ATOM && format==32 && data)
        for (unsigned long i=0;i<count;++i) if (reinterpret_cast<Atom*>(data)[i]==full) found=true;
    if(data) XFree(data);
    return found;
}
static void scene_poses(vr::TrackedDevicePose_t* poses) {
    vr::VRSystem()->GetDeviceToAbsoluteTrackingPose(vr::TrackingUniverseStanding,0,poses,vr::k_unMaxTrackedDeviceCount);
#ifdef FRAME_CINEMA_COMPOSITOR_TEST
    if (!poses[0].bPoseIsValid) {
        poses[0].bPoseIsValid=true;
        poses[0].bDeviceIsConnected=true;
        poses[0].eTrackingResult=vr::TrackingResult_Running_OK;
        poses[0].mDeviceToAbsoluteTracking={{{1,0,0,0},{0,1,0,1.65f},{0,0,1,0}}};
    }
#endif
}

static bool key_symbol(Display* display, KeySym symbol, Window target=0, unsigned modifiers=0) {
    auto code = XKeysymToKeycode(display, symbol);
    bool shift = false;
    if (code) {
        shift = XkbKeycodeToKeysym(display, code, 0, 0) != symbol && XkbKeycodeToKeysym(display, code, 0, 1) == symbol;
    } else {
        // Distinct spare codes preserve several Unicode characters queued in
        // one keyboard event; reusing one code would turn them into its last map.
        static std::vector<KeyCode> spare_codes;
        static size_t next_spare = 0;
        if (spare_codes.empty()) {
            int minimum, maximum;
            XDisplayKeycodes(display, &minimum, &maximum);
            for (int candidate=maximum; candidate>=minimum && spare_codes.size()<32; --candidate) {
                int count=0;
                auto* mapping=XGetKeyboardMapping(display,candidate,1,&count);
                bool unused=true;
                for (int i=0;i<count;++i) if (mapping[i]!=NoSymbol) unused=false;
                XFree(mapping);
                if (unused) spare_codes.push_back(candidate);
            }
        }
        if (spare_codes.empty()) return false;
        code = spare_codes[next_spare++ % spare_codes.size()];
        XChangeKeyboardMapping(display, code, 1, &symbol, 1);
        XSync(display, False);
    }
    if (target) {
        // XTEST follows Gamescope's Wayland seat, which can lack keyboard
        // focus despite our passive overlay's X/DOM focus. Address the
        // validated private browser window directly instead.
        XEvent event{};
        event.xkey.display=display;event.xkey.window=target;
        event.xkey.root=DefaultRootWindow(display);event.xkey.same_screen=True;
        event.xkey.keycode=code;event.xkey.state=modifiers|(shift?ShiftMask:0);
        event.xkey.type=KeyPress;
        const bool down=XSendEvent(display,target,False,NoEventMask,&event);
        event.xkey.type=KeyRelease;
        const bool up=XSendEvent(display,target,False,NoEventMask,&event);
        return down && up;
    }
    const auto modifier = XKeysymToKeycode(display, XK_Shift_L);
    if (shift) XTestFakeKeyEvent(display, modifier, True, CurrentTime);
    XTestFakeKeyEvent(display, code, True, CurrentTime);
    XTestFakeKeyEvent(display, code, False, CurrentTime);
    if (shift) XTestFakeKeyEvent(display, modifier, False, CurrentTime);
    return true;
}

static unsigned key_focus_restores = 0, key_focus_failures = 0;
static bool window_contains(Display* display, Window ancestor, Window window) {
    for (int depth=0;depth<16 && window>PointerRoot;++depth) {
        if (window==ancestor) return true;
        Window root=0,parent=0,*children=nullptr;unsigned count=0;
        const auto valid=XQueryTree(display,window,&root,&parent,&children,&count);
        if (children) XFree(children);
        if (!valid || !parent || parent==window) break;
        window=parent;
    }
    return false;
}
static bool focus_browser(Display* display, Window window) {
    Window focus=0;int revert=0;
    XGetInputFocus(display,&focus,&revert);
    if (window_contains(display,window,focus)) return true;
    XWindowAttributes attributes{};
    if (!window || !XGetWindowAttributes(display,window,&attributes) || attributes.map_state!=IsViewable) {
        ++key_focus_failures;return false;
    }
    XSetInputFocus(display,window,RevertToParent,CurrentTime);
    XSync(display,False);
    XGetInputFocus(display,&focus,&revert);
    if (!window_contains(display,window,focus)) { ++key_focus_failures;return false; }
    ++key_focus_restores;
    return true;
}
static bool keyboard_input(Display* display, Window window, const char* text, EditableFocus* editor = nullptr) {
    // Dedicated X server: a spare keycode can represent any Unicode codepoint.
    // Keep text only in the event being forwarded; never accumulate an input buffer.
    if (!focus_browser(display,window)) return false;
    const bool navigation=text[0]=='\t' || text[0]=='\n' || text[0]=='\r' || text[0]=='\x1b';
    if (editor && !editor->focus_editor(navigation)) return false;
    Window target=0;int revert=0;XGetInputFocus(display,&target,&revert);
    if (!window_contains(display,window,target)) return false;
    XSync(display,False);
    const auto errors_before=x_errors;
    bool sent=true;
    if (text[0] == '\x1b') {
        if (text[1]=='[') {
            const KeySym arrows[] = {XK_Up, XK_Down, XK_Right, XK_Left};
            if (text[2]>='A' && text[2]<='D') sent=key_symbol(display, arrows[text[2]-'A'],target);
        }
        XSync(display,False);
        if (!sent || x_errors!=errors_before) { ++key_send_failures;return false; }
        return sent;
    }
    const auto* cursor = reinterpret_cast<const unsigned char*>(text);
    const auto* end = cursor + strnlen(text, 8);
    while (cursor < end) {
        uint32_t codepoint = *cursor++;
        int more = 0;
        if ((codepoint & 0xe0) == 0xc0) { codepoint &= 0x1f; more = 1; }
        else if ((codepoint & 0xf0) == 0xe0) { codepoint &= 0x0f; more = 2; }
        else if ((codepoint & 0xf8) == 0xf0) { codepoint &= 0x07; more = 3; }
        if (cursor + more > end) break;
        while (more--) codepoint = (codepoint << 6) | (*cursor++ & 0x3f);
        KeySym symbol = codepoint <= 255 ? codepoint : (0x01000000 | codepoint);
        if (codepoint == 8) symbol = XK_BackSpace;
        if (codepoint == 10 || codepoint == 13) symbol = XK_Return;
        if (codepoint == 9) symbol = XK_Tab;
        sent=key_symbol(display, symbol,target) && sent;
    }
    XSync(display,False);
    if (!sent || x_errors!=errors_before) { ++key_send_failures;return false; }
    return sent;
}

static Window browser_window(Display* display, Window parent, int depth = 0) {
    if (depth > 3) return 0;
    Window root, owner, *children = nullptr;
    unsigned count = 0;
    if (!XQueryTree(display, parent, &root, &owner, &children, &count)) return 0;
    Window found = 0;
    for (unsigned i = 0; i < count && !found; ++i) {
        XWindowAttributes attributes{};
        XClassHint hint{};
        if (XGetWindowAttributes(display, children[i], &attributes) &&
            attributes.map_state == IsViewable && attributes.width >= 320 &&
            attributes.height >= 200 && XGetClassHint(display, children[i], &hint)) {
            std::string cls = hint.res_class ? hint.res_class : "";
            std::transform(cls.begin(), cls.end(), cls.begin(), [](unsigned char c){ return std::tolower(c); });
            // This X server belongs only to our panel process and its children.
            if (cls.find("chrome") != std::string::npos || cls.find("moonlight") != std::string::npos)
                found = children[i];
            if (hint.res_name) XFree(hint.res_name);
            if (hint.res_class) XFree(hint.res_class);
        }
        if (!found) found = browser_window(display, children[i], depth + 1);
    }
    if (children) XFree(children);
    return found;
}

static vr::HmdMatrix34_t screen_transform{};
static float screen_width = 4.2f;
static std::unique_ptr<cinema_placement::Bridge> placement;
static bool placement_ready = false;
static const char* placement_reason = "waiting for scene placement";
static unsigned placement_dropouts = 0;
static int placement_width_error = 0, placement_transform_error = 0, placement_visibility_error = 0;
static PanelVisibilityHistory visibility_history;
static unsigned visibility_write_failures=0, reference_reset_count=0;
static uint32_t reference_reset_event=0;
static bool observed_panel_visible=false;
static bool visibility_history_dirty=false;
static cinema_placement::PoseHistory pose_history;
static cinema_placement::Matrix raw_to_standing{};
static uint64_t tracking_universe=0;
static bool standing_known=false;
static unsigned reference_preserved=0, synchronized_samples=0, missing_timed_samples=0;
static int64_t monotonic_ns() {
    timespec value{};clock_gettime(CLOCK_MONOTONIC,&value);
    return int64_t(value.tv_sec)*1000000000+value.tv_nsec;
}
static void sample_pose_history() {
    vr::TrackedDevicePose_t pose{};
    const auto before=monotonic_ns();
    vr::VRSystem()->GetDeviceToAbsoluteTrackingPose(vr::TrackingUniverseStanding,0,&pose,1);
    const auto after=monotonic_ns();
    if(after-before>2000000) {pose_history.clear();return;}
    pose_history.add(before+(after-before)/2,pose);
}
static bool refresh_standing(bool universe_changed) {
    vr::ETrackedPropertyError error{};
    const auto universe=vr::VRSystem()->GetUint64TrackedDeviceProperty(0,vr::Prop_CurrentUniverseId_Uint64,&error);
    const auto next=vr::VRSystem()->GetRawZeroPoseToStandingAbsoluteTrackingPose();
    const bool valid=error==vr::TrackedProp_Success && universe!=0 && cinema_placement::rigid(next);
    const bool can_preserve=!universe_changed && standing_known && valid && universe==tracking_universe;
    bool preserved=false;
    if(can_preserve)preserved=placement->rebase(cinema_placement::multiply(next,cinema_placement::inverse(raw_to_standing)));
    raw_to_standing=next;tracking_universe=universe;standing_known=valid;
    pose_history.clear();return preserved;
}
static double placement_now() {
    return std::chrono::duration<double>(std::chrono::system_clock::now().time_since_epoch()).count();
}

static void place(vr::IVROverlay* overlays, vr::VROverlayHandle_t panel, const std::string& ipc) {
    cinema_placement::Packet packet;
    std::ifstream settings(ipc + "/placement.txt");
    const bool was_ready=placement_ready;
    placement_ready=false;
    placement_width_error=0;placement_transform_error=0;
    placement_reason="missing or invalid placement packet";
    if (cinema_placement::read(settings,packet)) {
        vr::TrackedDevicePose_t poses[vr::k_unMaxTrackedDeviceCount]{};
        scene_poses(poses);
        bool synchronized=false;
        if(packet.pose_time_ns>0) {
            const auto now=monotonic_ns();const double seconds=double(packet.pose_time_ns-now)*1e-9;
            if(seconds>=0 && seconds<=.08) {
                vr::VRSystem()->GetDeviceToAbsoluteTrackingPose(vr::TrackingUniverseStanding,float(seconds),poses,1);
                synchronized=true;
            } else synchronized=pose_history.at(packet.pose_time_ns,poses[0]);
            if(synchronized)++synchronized_samples;
            else {++missing_timed_samples;poses[0].bPoseIsValid=false;}
        }
        if (placement->update(packet,poses[0],placement_now(),synchronized)) {
            screen_transform=placement->screen;screen_width=placement->width;
            const auto rendered=cinema_projection::browser(screen_transform,screen_width);
            placement_width_error=overlays->SetOverlayWidthInMeters(panel,rendered.width);
            placement_transform_error=overlays->SetOverlayTransformAbsolute(panel,vr::TrackingUniverseStanding,&rendered.pose);
            placement_ready=!placement_width_error && !placement_transform_error;
        }
        placement_reason=placement->ready && !placement_ready ? "overlay placement API failed" : placement->reason;
    }
    if (was_ready && !placement_ready) ++placement_dropouts;
    placement_visibility_error=placement_ready && presentation.show && !stereo_active ? overlays->ShowOverlay(panel) : overlays->HideOverlay(panel);
}

static unsigned pointer_packets = 0, pointer_clicks = 0, down_events = 0, ray_hits = 0;
static int cursor_error = 0, keyboard_error = 0;
static int beam_error = 0;
static vr::VROverlayHandle_t beam = 0;
static vr::VROverlayHandle_t keyboard_overlay = 0;
static vr::VROverlayHandle_t keyboard_upper = 0, keyboard_highlight = 0, keyboard_shown = 0;
static unsigned keyboard_ray_hits = 0;
static CinemaKeyboard keyboard_layout;
static vr::HmdMatrix34_t keyboard_transform{};
static bool keyboard_visible = false, keyboard_capture = false;
static bool keyboard_opened_for_editor = false;
static bool keyboard_dismissed = false;
static bool keyboard_ready = false;
static unsigned keyboard_uploads = 0, keyboard_presentations = 0;
static int highlight_error = 0;
static unsigned highlight_failures = 0;
static unsigned keyboard_shows = 0, keyboard_chars = 0, keyboard_app_hides = 0;
static EditableFocus* browser_focus = nullptr;
static unsigned keyboard_dispatches = 0, keyboard_blocked = 0;
static bool keyboard_target_ready = true;
static bool prepare_keyboard(vr::IVROverlay* overlays) {
    CinemaKeyboard layout;
    for (auto handle : {keyboard_overlay,keyboard_upper}) {
        auto pixels=layout.pixels(CinemaKeyboard::texture_scale);
        keyboard_error=overlays->SetOverlayRaw(handle,pixels.data(),CinemaKeyboard::texture_width,CinemaKeyboard::texture_height,4);
        ++keyboard_uploads;
        if (keyboard_error) return false;
        layout.shifted=true;
    }
    return true;
}
// The key shape whose highlight is in the overlay now: texture size in pixels and corner radius.
static int highlight_width=0, highlight_height=0;
static double highlight_radius=-1;
static bool upload_highlight(vr::IVROverlay* overlays, const CinemaKeyboard::Key& key) {
    const int scale=CinemaKeyboard::texture_scale;
    const int width=int(std::lround(key.w*scale)), height=int(std::lround(key.h*scale));
    const double radius=CinemaKeyboard::corner_radius(key);
    if (width==highlight_width && height==highlight_height && radius==highlight_radius) return true;
    auto pixels=CinemaKeyboard::highlight_pixels(key,scale);
    highlight_error=overlays->SetOverlayRaw(keyboard_highlight,pixels.data(),width,height,4);
    if (highlight_error) { highlight_width=highlight_height=0; highlight_radius=-1; return false; }
    highlight_width=width; highlight_height=height; highlight_radius=radius;
    return true;
}
static void present_keyboard(vr::IVROverlay* overlays, bool dashboard) {
    const auto target=keyboard_visible && !dashboard && keyboard_ready ? (keyboard_layout.shifted?keyboard_upper:keyboard_overlay) : 0;
    if (target!=keyboard_shown) {
        native_sources.leave(cinema_system_browser::Target::Keyboard);
        if (keyboard_shown) overlays->HideOverlay(keyboard_shown);
        keyboard_shown=0;
        if (target) {
            keyboard_error=overlays->ShowOverlay(target);
            if (!keyboard_error) { keyboard_shown=target; ++keyboard_presentations; }
            else { keyboard_visible=false; keyboard_ready=false; }
        }
    }
    if (!target || !keyboard_shown || keyboard_layout.hover<0) {
        overlays->HideOverlay(keyboard_highlight);
        return;
    }
    const auto& key=keyboard_layout.keys[keyboard_layout.hover];
    // The highlight carries the hovered key's own shape. Keys of one size share a texture, so moving
    // across the letters uploads nothing; a key of another size (Space, Return, Shift...) uploads its
    // small highlight once. The keyboard textures themselves are never re-uploaded on hover.
    if (!upload_highlight(overlays,key)) { ++highlight_failures; overlays->HideOverlay(keyboard_highlight); return; }
    auto pose=keyboard_transform;
    const float local[]={float((key.x+key.w/2)/CinemaKeyboard::width-.5)*CinemaKeyboard::metres,
                         float(.5-(key.y+key.h/2)/CinemaKeyboard::height)*CinemaKeyboard::metres*CinemaKeyboard::height/CinemaKeyboard::width,.004f};
    for (int i=0;i<3;++i) for (int j=0;j<3;++j) pose.m[i][3]+=keyboard_transform.m[i][j]*local[j];
    highlight_error=overlays->SetOverlayTransformAbsolute(keyboard_highlight,vr::TrackingUniverseStanding,&pose);
    if (!highlight_error) highlight_error=overlays->SetOverlayWidthInMeters(keyboard_highlight,CinemaKeyboard::metres*key.w/CinemaKeyboard::width);
    if (!highlight_error) highlight_error=overlays->SetOverlayAlpha(keyboard_highlight,keyboard_layout.pressed==keyboard_layout.hover?.4f:.2f);
    if (!highlight_error) highlight_error=overlays->ShowOverlay(keyboard_highlight);
    if (highlight_error) ++highlight_failures;
}
static uint64_t last_pointer_sequence = 0;
static auto pointer_seen = std::chrono::steady_clock::now();
static auto browser_released = std::chrono::steady_clock::time_point{};
static void cancel_pointer(Display* display, vr::IVROverlay* overlays, vr::VROverlayHandle_t cursor, unsigned& pressed, bool hide_beam = true) {
    overlays->HideOverlay(cursor);
    if (beam && hide_beam) overlays->HideOverlay(beam);
    if (hide_beam && (keyboard_capture || keyboard_layout.hover>=0)) {
        keyboard_capture=false; keyboard_layout.pressed=-1; keyboard_layout.hover=-1;
    }
    native_scroll.cancel();
    browser_pointer.cancel(display);pressed=0;XFlush(display);
}
static void show_beam(vr::IVROverlay* overlays, const float* start, const float* direction,
                      float length, const vr::HmdMatrix34_t& hmd) {
    if (!beam || length < .01f) return;
    auto pose = beam_transform({start[0],start[1],start[2]}, {direction[0],direction[1],direction[2]},
                               length, {hmd.m[0][3],hmd.m[1][3],hmd.m[2][3]});
    beam_error = overlays->SetOverlayTransformAbsolute(beam, vr::TrackingUniverseStanding, &pose);
    if (!beam_error) beam_error = overlays->SetOverlayWidthInMeters(beam, length);
    // Texture is 32x4; changing texel aspect keeps its thickness at 4 mm.
    if (!beam_error) beam_error = overlays->SetOverlayTexelAspect(beam, length / (8.f * .004f));
    if (!beam_error) beam_error = overlays->ShowOverlay(beam);
}
static bool keyboard_ray(Display* display, Window window, vr::IVROverlay* overlays,
                         vr::VROverlayHandle_t cursor, int kind, const float* origin,
                         const float* direction, float limit, const vr::HmdMatrix34_t& hmd) {
    if (!keyboard_visible) return false;
    float o[3]{}, d[3]{};
    for (int i=0;i<3;++i) for (int j=0;j<3;++j) {
        o[i]+=keyboard_transform.m[j][i]*(origin[j]-keyboard_transform.m[j][3]);
        d[i]+=keyboard_transform.m[j][i]*direction[j];
    }
    const float distance=std::abs(d[2])>.00001f ? -o[2]/d[2] : -1.f;
    const float u=.5f+(o[0]+d[0]*distance)/CinemaKeyboard::metres;
    const float v=.5f-(o[1]+d[1]*distance)/(CinemaKeyboard::metres*CinemaKeyboard::height/CinemaKeyboard::width);
    const bool hit=distance>0 && distance<=limit && u>=0 && u<=1 && v>=0 && v<=1;
    int key=hit?keyboard_layout.hit(u,v):-1;
    if (keyboard_capture) key=keyboard_layout.held(key,hit);
    if (key!=keyboard_layout.hover) { keyboard_layout.hover=key; }
    bool consumed=hit || keyboard_capture;
    if (kind==1 && hit) { keyboard_capture=true; keyboard_layout.pressed=key; }
    if (kind==2 && keyboard_capture) {
        consumed=true; keyboard_capture=false;
        bool hide=false;
        const bool was_shifted=keyboard_layout.shifted;
        const auto text=keyboard_layout.release(key,hide);
        bool explicit_hide=hide;
        if (!text.empty()) {
            ++keyboard_chars;
            keyboard_target_ready=window && keyboard_input(display,window,text.c_str(),browser_focus);
            if (keyboard_target_ready) {
                ++keyboard_dispatches;
                if (text=="\r") { hide=true; explicit_hide=true; }
            }
            else {
                ++keyboard_blocked;
                keyboard_layout.shifted=was_shifted;
                // Keep the editor available if focus/dispatch failed, including
                // Return. Only Done or an accepted Return dismisses it.
            }
        }
        if (hide) { keyboard_visible=false; keyboard_dismissed=explicit_hide; ++keyboard_app_hides; }
       
    }
    if (!consumed) return false;
    show_beam(overlays,origin,direction,hit?distance:limit,hmd);
    if (hit) {
        ++keyboard_ray_hits;
        auto pose=keyboard_transform;
        for (int i=0;i<3;++i) pose.m[i][3]=origin[i]+direction[i]*distance+keyboard_transform.m[i][2]*.01f;
        cursor_error=overlays->SetOverlayTransformAbsolute(cursor,vr::TrackingUniverseStanding,&pose);
        if (!cursor_error) cursor_error=overlays->ShowOverlay(cursor);
    } else overlays->HideOverlay(cursor);
    return true;
}
static void forward_ray(Display* display, Window window, vr::IVROverlay* overlays,
                        vr::VROverlayHandle_t cursor, std::istream& input, unsigned& pressed) {
    int kind = 0; uint64_t sequence = 0;
    float origin[3], direction[3];
    if (!(input >> kind >> sequence >> origin[0] >> origin[1] >> origin[2] >> direction[0] >> direction[1] >> direction[2])) return;
    for (int i=0; i<3; ++i) if (!std::isfinite(origin[i]) || !std::isfinite(direction[i])) return;
    float limit = 6.f;
    input >> limit;
    uint64_t sent_us=0;
    input >> sent_us; // Older fixtures omit this optional timing field.
    if (!std::isfinite(limit)) return;
    limit = cinema_layout::pointer_reach(limit);
    const float norm = std::sqrt(direction[0]*direction[0]+direction[1]*direction[1]+direction[2]*direction[2]);
    if (norm < .001f) return;
    for (float& v : direction) v /= norm;
    if (!pointer_sequence.accept(kind,sequence)) return;
    if ((kind==1 || kind==2) && sent_us) {
        const auto now_us=uint64_t(std::chrono::duration_cast<std::chrono::microseconds>(
            std::chrono::system_clock::now().time_since_epoch()).count());
        if (now_us>=sent_us && now_us-sent_us<10000000) event_queue_timing.add(now_us-sent_us);
    }
    if (kind == 0 || kind == 3 || kind == 6 || kind == 7) {
        if (sequence == last_pointer_sequence) return;
        last_pointer_sequence = sequence;
        pointer_seen = std::chrono::steady_clock::now();
    }
    // Consume sequence numbers while the other owner has input. Never replay
    // an old scene hover/down when focus returns.
    if(system_pointer.enabled && (system_pointer.active||system_pointer.require_up))return;
    if (kind == 3 || kind == 7) { cancel_pointer(display, overlays, cursor, pressed); return; }
    const char* session=std::getenv("FRAME_CINEMA_SESSION");
    const bool screen_relative=placement && pointer_frame_matches(input,session?session:"",
        placement->reference_generation(),placement->anchor_revision());
    if(!screen_relative) {cancel_pointer(display,overlays,cursor,pressed);return;}
    if (!presentation.interactive || !presentation.show) kind=6;
    if (kind == 6) cancel_pointer(display, overlays, cursor, pressed, false);
    ++pointer_packets;
    if (kind == 1) ++down_events;
    // Ownership survives a field click opening the keyboard mid-squeeze.
    // A repeated press packet must not become a fresh keyboard key press.
    if (kind==1 && (pressed || keyboard_capture)) return;
    vr::TrackedDevicePose_t poses[vr::k_unMaxTrackedDeviceCount]{};
    scene_poses(poses);
    if (!poses[0].bPoseIsValid) { cancel_pointer(display, overlays, cursor, pressed); return; }
    const auto& hmd = poses[0].mDeviceToAbsoluteTracking;
    float world_origin[3]{}, world_direction[3]{}, local_origin[3]{}, local_direction[3]{};
    pointer_to_world(screen_transform,origin,direction,world_origin,world_direction);
    for (int i=0; i<3; ++i) for (int j=0; j<3; ++j) {
        local_origin[i] += screen_transform.m[j][i]*(world_origin[j]-screen_transform.m[j][3]);
        local_direction[i] += screen_transform.m[j][i]*world_direction[j];
    }
    if (presentation.interactive && keyboard_ray(display,window,overlays,cursor,kind,world_origin,world_direction,limit,hmd)) {
        if (kind==2 && pressed) { browser_pointer.cancel(display);pressed=0;XFlush(display); }
        return;
    }
    XWindowAttributes a{};
    if (!window || !XGetWindowAttributes(display, window, &a) || a.width <= 0 || a.height <= 0) {
        browser_pointer.cancel(display);pressed=0;XFlush(display);
        overlays->HideOverlay(cursor);
        show_beam(overlays, world_origin, world_direction, limit, hmd);
        return;
    }
    const float distance = std::abs(local_direction[2]) > 0.00001f ? -local_origin[2]/local_direction[2] : -1;
    const float u = .5f + (local_origin[0]+local_direction[0]*distance)/screen_width;
    const float v = .5f - (local_origin[1]+local_direction[1]*distance)/(screen_width*a.height/a.width);
    const bool hit = presentation.show && distance > 0 && distance <= limit && u>=0 && u<=1 && v>=presentation.top && v<=1-presentation.top;
    show_beam(overlays, world_origin, world_direction, hit ? distance : limit, hmd);
    if (!hit || kind == 6) {
        browser_pointer.leave(display);
        if (kind==2 && pressed) { browser_pointer.cancel(display);pressed=0; }
        XFlush(display);overlays->HideOverlay(cursor);return;
    }
    if(system_pointer.enabled&&system_pointer.scene_latched&&kind==1){
        system_pointer.enter_requested=true;cancel_pointer(display,overlays,cursor,pressed);return;
    }
    ++ray_hits;
    Window unused; int x, y;
    XTranslateCoordinates(display, window, DefaultRootWindow(display), 0, 0, &x, &y, &unused);
    const int px=int(u*(a.width-1)),py=int(v*(a.height-1));
    browser_pointer.move(display,window,px,py);
    // A normal overlay avoids subview sizing against the forwarded 0x0 texture.
    auto cursor_pose = screen_transform;
    const float local[] = {(u-.5f)*screen_width, (.5f-v)*screen_width*a.height/a.width, .015f};
    for (int i=0; i<3; ++i) for (int j=0; j<3; ++j) cursor_pose.m[i][3] += screen_transform.m[i][j]*local[j];
    cursor_error = overlays->SetOverlayTransformAbsolute(cursor, vr::TrackingUniverseStanding, &cursor_pose);
    if (!cursor_error) cursor_error = overlays->ShowOverlay(cursor);
    if (kind == 1 && !pressed) {
        if (browser_focus) browser_focus->browser_click(x+int(u*(a.width-1)),y+int(v*(a.height-1)));
        keyboard_auto_suppressed=false;
        XSetInputFocus(display, window, RevertToParent, CurrentTime);
        // `pressed` retains physical-trigger ownership, not an X mouse hold.
        // Browsing uses activation; scrolling is a separate thumbstick action.
        if (browser_pointer.click(display,window,px,py)) {
            pressed=1;++pointer_clicks;
            browser_released=std::chrono::steady_clock::now();
        }
    }
    if (kind==2 && pressed) {
        pressed=0;
        browser_released=std::chrono::steady_clock::now();
    }
    if (kind==4 || kind==5) browser_pointer.scroll(display,window,px,py,kind);
    XFlush(display);
}

// Included after the frozen keyboard/pointer helpers; not standalone.
static std::vector<unsigned char> system_return_pixels(){
    constexpr int width=1024,height=192;
    auto* surface=cairo_image_surface_create(CAIRO_FORMAT_ARGB32,width,height);auto* c=cairo_create(surface);
    cairo_set_operator(c,CAIRO_OPERATOR_SOURCE);cairo_set_source_rgba(c,0,0,0,0);cairo_paint(c);cairo_set_operator(c,CAIRO_OPERATOR_OVER);
    constexpr double pi=3.141592653589793;
    cairo_new_sub_path(c);cairo_arc(c,width-76,76,64,-pi/2,0);cairo_arc(c,width-76,height-76,64,0,pi/2);
    cairo_arc(c,76,height-76,64,pi/2,pi);cairo_arc(c,76,76,64,pi,3*pi/2);cairo_close_path(c);
    cairo_set_source_rgba(c,.13,.15,.19,.98);cairo_fill_preserve(c);cairo_set_source_rgba(c,.76,.80,.88,.65);cairo_set_line_width(c,2);cairo_stroke(c);
    cairo_select_font_face(c,"sans-serif",CAIRO_FONT_SLANT_NORMAL,CAIRO_FONT_WEIGHT_NORMAL);cairo_set_font_size(c,52);cairo_set_source_rgb(c,.97,.98,1);
    cairo_text_extents_t extent{};cairo_text_extents(c,"Cinema controls",&extent);
    cairo_move_to(c,(width-extent.width)/2-extent.x_bearing,(height-extent.height)/2-extent.y_bearing);cairo_show_text(c,"Cinema controls");
    cairo_surface_flush(surface);const auto* bytes=cairo_image_surface_get_data(surface);const int stride=cairo_image_surface_get_stride(surface);
    std::vector<unsigned char> rgba(width*height*4);
    for(int y=0;y<height;++y)for(int x=0;x<width;++x){const auto* in=bytes+y*stride+x*4;auto* out=rgba.data()+(y*width+x)*4;const unsigned alpha=in[3];
        for(int ch=0;ch<3;++ch){out[ch]=alpha?static_cast<unsigned char>((unsigned(in[2-ch])*255+alpha/2)/alpha):0;}
        out[3]=alpha;}
    cairo_destroy(c);cairo_surface_destroy(surface);return rgba;
}
static bool system_triggers_released(){
    bool found=false;
    for(auto role:{vr::TrackedControllerRole_LeftHand,vr::TrackedControllerRole_RightHand}){
        const auto device=vr::VRSystem()->GetTrackedDeviceIndexForControllerRole(role);
        if(device>=vr::k_unMaxTrackedDeviceCount||!vr::VRSystem()->IsTrackedDeviceConnected(device))continue;
        found=true;vr::VRControllerState_t state{};
        if(!vr::VRSystem()->GetControllerState(device,&state,sizeof(state))
           ||(state.ulButtonPressed&vr::ButtonMaskFromId(vr::k_EButton_SteamVR_Trigger)))return false;
    }
    return found; // Unknown button state must not arm either ownership path.
}
static void system_drain(vr::IVROverlay* overlays,vr::VROverlayHandle_t handle){
    vr::VREvent_t event{};for(unsigned count=0;handle&&count<1024&&overlays->PollNextOverlayEvent(handle,&event,sizeof(event));++count){}
}
static void system_keyboard_release(Display* display,Window window,int key){
    keyboard_capture=false;bool hide=false;const bool was_shifted=keyboard_layout.shifted;
    const auto text=keyboard_layout.release(key,hide);bool explicit_hide=hide;
    if(!text.empty()){
        ++keyboard_chars;keyboard_target_ready=window&&keyboard_input(display,window,text.c_str(),browser_focus);
        if(keyboard_target_ready){++keyboard_dispatches;if(text=="\r"){hide=true;explicit_hide=true;}}
        else {++keyboard_blocked;keyboard_layout.shifted=was_shifted;}
    }
    if(hide){keyboard_visible=false;keyboard_dismissed=explicit_hide;++keyboard_app_hides;}
}

static void record_visibility(vr::IVROverlay* overlays,vr::VROverlayHandle_t panel,
                              Window window,bool dashboard,bool query) {
    PanelVisibilityState visibility;
    visibility.time=placement_now();visibility.ready=placement_ready;
    visibility.visible=observed_panel_visible;visibility.attached=window!=0;visibility.window=window;
    visibility.dashboard=dashboard;visibility.keyboard=keyboard_visible;
    visibility.generation=placement->reference_generation();visibility.revision=placement->anchor_revision();
    visibility.width=screen_width;visibility.clicks=pointer_clicks;
    visibility.reset_count=reference_reset_count;visibility.reset_event=reference_reset_event;
    visibility.width_error=placement_width_error;visibility.transform_error=placement_transform_error;
    visibility.visibility_error=placement_visibility_error;visibility.reason=placement_reason;
    // Query runtime visibility on transitions and at the existing status cadence.
    if (query || !visibility_history.same(visibility))
        observed_panel_visible=visibility.visible=overlays->IsOverlayVisible(panel);
    visibility_history_dirty=visibility_history.record(visibility) || visibility_history_dirty;
}

int main(int argc, char** argv) {
    XInitThreads();
    if (argc < 2) return 2;
    std::signal(SIGTERM, stop);
    std::signal(SIGINT, stop);
    XSetErrorHandler(ignore_x_error);
    auto display = XOpenDisplay(nullptr);
    if (!display) return 3;
    vr::EVRInitError init = vr::VRInitError_None;
    vr::VR_Init(&init, vr::VRApplication_Overlay);
    if (init != vr::VRInitError_None) return 4;
    auto overlays = vr::VROverlay();
    const char* system_setting=std::getenv("FRAME_CINEMA_SYSTEM_POINTER");
    system_pointer.enabled=system_setting&&std::strcmp(system_setting,"1")==0;
    const char* unified_setting=std::getenv("FRAME_CINEMA_UNIFIED_UI");
    unified_ui=unified_setting&&std::strcmp(unified_setting,"1")==0;
    vr::VROverlayHandle_t panel = 0, transport = 0;
    const char* location = std::getenv("FRAME_CINEMA_IPC");
    std::string ipc = location ? location : "/run/user/1000/frame-cinema";
    const char* scene_session=std::getenv("FRAME_CINEMA_SESSION");
    cinema_scene_owner::BorrowedHandles scene_handles;
    const char* scene_setting=std::getenv("FRAME_CINEMA_SCENE_OWNER");
    scene_handles.enabled=scene_setting&&std::strcmp(scene_setting,"1")==0;
    if(scene_handles.enabled&&!system_pointer.enabled)return 21;
    if (overlays->FindOverlay("frame-lab.cinema.video", &transport) != vr::VROverlayError_None) return 6;
    const auto renderer = overlays->GetOverlayRenderingPid(transport);
    const char* native_scroll_setting=std::getenv("FRAME_CINEMA_NATIVE_SCROLL");
    const bool native_scroll_enabled=native_scroll_setting&&std::strcmp(native_scroll_setting,"1")==0;
    auto* native_scroll_view=native_scroll_enabled?vr::VROverlayView():nullptr;
    if(native_scroll_enabled&&!native_scroll_view)return 30;
    if(!scene_handles.begin(overlays,vr::VRApplications(),ipc,scene_session?scene_session:"",renderer))return 22;
    if(scene_handles.create(overlays,cinema_scene_owner::Role::Screen,"frame-lab.cinema.screen","Frame Cinema screen",&panel))return 5;
    if(scene_handles.screen_renderer(overlays,panel,renderer))return 7;
    // The OpenXR scene owns controller input. An interactive overlay can take
    // focus from it while the scene still receives tracked poses.
    overlays->SetOverlayInputMethod(panel, vr::VROverlayInputMethod_None);
    overlays->SetOverlayFlag(panel, vr::VROverlayFlags_MakeOverlaysInteractiveIfVisible, false);
    overlays->SetOverlayFlag(panel, vr::VROverlayFlags_VisibleInDashboard, true);
    overlays->SetOverlayFlag(panel, vr::VROverlayFlags_SendVRSmoothScrollEvents, true);
    overlays->SetOverlayFlag(panel, vr::VROverlayFlags_EnableControlBarKeyboard, false);
    overlays->SetOverlayFlag(panel, vr::VROverlayFlags_IgnoreTextureAlpha, true);
    placement=std::make_unique<cinema_placement::Bridge>(scene_session?scene_session:"",ipc+"/placement-map.txt");
    refresh_standing(false);
    place(overlays, panel, ipc);
    vr::VROverlayHandle_t cursor = 0;
    cursor_error = overlays->CreateOverlay("frame-lab.cinema.pointer", "Cinema pointer", &cursor);
    if (cursor_error) return 9;
    overlays->SetOverlayInputMethod(cursor, vr::VROverlayInputMethod_None);
    overlays->SetOverlayWidthInMeters(cursor, .035f);
    overlays->SetOverlaySortOrder(panel, 10);
    overlays->SetOverlaySortOrder(cursor, 20);
    unsigned char pixels[32*32*4]{};
    for (int y=0; y<32; ++y) for (int x=0; x<32; ++x) {
        const int i=(y*32+x)*4, r=(x-16)*(x-16)+(y-16)*(y-16);
        pixels[i]=pixels[i+1]=pixels[i+2]=r<64 ? 255 : 20;
        pixels[i+3]=r<144 ? 255 : 0;
    }
    cursor_error = overlays->SetOverlayRaw(cursor, pixels, 32, 32, 4);
    beam_error = overlays->CreateOverlay("frame-lab.cinema.ray", "Cinema ray", &beam);
    if (beam_error) return 10;
    overlays->SetOverlayInputMethod(beam, vr::VROverlayInputMethod_None);
    overlays->SetOverlaySortOrder(beam, 20);
    overlays->SetOverlaySortOrder(cursor, 30);
    unsigned char beam_pixels[32*4*4]{};
    for (int y=0; y<4; ++y) for (int x=0; x<32; ++x) {
        const int i=(y*32+x)*4;
        beam_pixels[i]=195; beam_pixels[i+1]=220; beam_pixels[i+2]=255;
        beam_pixels[i+3]=(y==1 || y==2) ? 255 : 90;
    }
    beam_error = overlays->SetOverlayRaw(beam, beam_pixels, 32, 4, 4);
    keyboard_error=scene_handles.create(overlays,cinema_scene_owner::Role::Keyboard,"frame-lab.cinema.keyboard","Cinema keyboard",&keyboard_overlay);
    if (keyboard_error) return 11;
    keyboard_error=scene_handles.create(overlays,cinema_scene_owner::Role::KeyboardUpper,"frame-lab.cinema.keyboard.upper","Cinema keyboard upper case",&keyboard_upper);
    if (keyboard_error) return 11;
    for (auto handle : {keyboard_overlay,keyboard_upper}) {
        overlays->SetOverlayInputMethod(handle,vr::VROverlayInputMethod_None);
        overlays->SetOverlaySortOrder(handle,15);
        overlays->SetOverlayWidthInMeters(handle,CinemaKeyboard::metres);
    }
    keyboard_error=scene_handles.create(overlays,cinema_scene_owner::Role::KeyboardHighlight,"frame-lab.cinema.keyboard.highlight","Cinema key highlight",&keyboard_highlight);
    if (keyboard_error) return 11;
    overlays->SetOverlayInputMethod(keyboard_highlight,vr::VROverlayInputMethod_None);
    overlays->SetOverlaySortOrder(keyboard_highlight,16);
    // Preload the letter keys' highlight, the shape hovered most. Its texture has the key's own
    // proportions, so texels stay square; hover moves this overlay and never uploads a keyboard texture.
    if (upload_highlight(overlays,keyboard_layout.keys[1]))
        highlight_error=overlays->SetOverlayTexelAspect(keyboard_highlight,1.f);
    if (!highlight_error) highlight_error=overlays->SetOverlayColor(keyboard_highlight,1.f,1.f,1.f);
    if (highlight_error) ++highlight_failures;
    keyboard_ready=prepare_keyboard(overlays);
    vr::VROverlayHandle_t system_return=0;
    if(system_pointer.enabled){
        bool ok=!scene_handles.create(overlays,cinema_scene_owner::Role::Return,"frame-lab.cinema.system.return","Cinema controls",&system_return);
        if(ok){auto pixels=system_return_pixels();ok=!overlays->SetOverlayRaw(system_return,pixels.data(),1024,192,4);}
        if(ok)ok=!overlays->SetOverlayWidthInMeters(system_return,.82f);
        if(ok)ok=!overlays->SetOverlaySortOrder(system_return,30);
        const vr::HmdVector2_t return_scale={{1024,192}},key_scale={{CinemaKeyboard::width,CinemaKeyboard::height}};
        if(ok)ok=!overlays->SetOverlayMouseScale(system_return,&return_scale);
        for(auto handle:{keyboard_overlay,keyboard_upper})if(ok)ok=!overlays->SetOverlayMouseScale(handle,&key_scale);
        if(!ok){
            ++system_pointer_errors;system_pointer.enabled=false;
            if(system_return){scene_handles.destroy(overlays,system_return);}
            system_return=0;
            // Scene-owned mode requires a reachable native return path. Its
            // failed setup must not silently enter the old controller route.
            if(scene_handles.enabled){scene_handles.release(overlays);return 23;}
        }
    }
#if defined(FRAME_CINEMA_COMPOSITOR_TEST) && !defined(FRAME_CINEMA_REAL_DASHBOARD)
    // Only the separately compiled synthetic fixture may receive test rays
    // while Steam's dashboard is open. Production retains its ownership gate.
    for (auto handle : {keyboard_overlay,keyboard_upper,keyboard_highlight,beam,cursor})
        overlays->SetOverlayFlag(handle,vr::VROverlayFlags_VisibleInDashboard,true);
#endif
    const pid_t child = fork();
    if (child == 0) { execvp(argv[1], argv+1); _exit(127); }
    std::unique_ptr<cinema_stereo::Bridge> stereo;
    vr::VROverlayHandle_t stereo_handle=0;
    const char* stereo_setting=std::getenv("FRAME_CINEMA_STEREO");
    const char* source_session=std::getenv("FRAME_CINEMA_SOURCE_SESSION");
    const char* stereo_model=std::getenv("FRAME_CINEMA_STEREO_MODEL");
    if(stereo_setting&&std::strcmp(stereo_setting,"1")==0&&scene_handles.enabled&&source_session&&stereo_model){
        try{
            if(scene_handles.create(overlays,cinema_scene_owner::Role::Stereo,"frame-lab.cinema.stereo","Cinema 3D",&stereo_handle))throw std::runtime_error("stereo_lease");
            stereo=std::make_unique<cinema_stereo::Bridge>(stereo_handle,panel,ipc,scene_session,source_session,stereo_model);
        }catch(const std::exception& e){std::fprintf(stderr,"cinema stereo setup: %s\n",e.what());}
    }
    if (child < 0) return 8;
    Window window = 0;
    AmbientWorker ambient_worker;
    const Atom target = XInternAtom(display, "STEAM_GAMESCOPE_VROVERLAY_TARGET", False);
    int ticks = 0, child_status = 0;
    // Keep one prior source session, including when Services closes its IPC
    // status file. Both snapshots are bounded and contain no browser content.
    std::rename((ipc+"/panel-visibility.json").c_str(),(ipc+"/panel-visibility.previous.json").c_str());
    uint64_t keyboard_request = 0;
    unsigned int mouse_button = 0;
    bool dashboard_was_visible = false;
    bool manual_keyboard = false;
    auto editor_checked=std::chrono::steady_clock::now();
    auto target_missing_since=std::chrono::steady_clock::time_point{};
    EditableFocus editable_focus;
    editable_focus.start();
    browser_focus=&editable_focus;
    uint64_t browser_command = 0;
    const char* pipe_setting=std::getenv("FRAME_CINEMA_BROWSER_PIPE");
    const bool browser_pipe=pipe_setting && std::strcmp(pipe_setting,"1")==0;
    auto navigate = [&](int command, uint64_t id) {
        if (command<1 || command>5 || !window) return;
        const bool keyboard_was_open=keyboard_visible || manual_keyboard;
        cancel_pointer(display,overlays,cursor,mouse_button);
        editable_focus.request=false; manual_keyboard=false; browser_released={};
        if (command==4 && !keyboard_was_open) {
            manual_keyboard=true;
            return;
        }
        if (keyboard_visible) ++keyboard_app_hides;
        keyboard_visible=false; keyboard_auto_suppressed=true;
        // B closes our keyboard without changing browser focus or sending Escape.
        if (command==5) return;
        if (command==1 || command==2) editable_focus.clear_editor();
        XSetInputFocus(display,window,RevertToParent,CurrentTime);
        if (browser_pipe && (command==1 || command==2)) {
            // Keep pointer/editor cancellation ahead of navigation. Browser
            // accelerators may be unavailable in the kiosk player window.
            char filename[64];std::snprintf(filename,sizeof(filename),"/media/%020llu",static_cast<unsigned long long>(id));
            const std::string path=ipc+filename;
            const auto now=std::chrono::duration<double>(std::chrono::system_clock::now().time_since_epoch()).count();
            std::ofstream request(path+".tmp");
            request.precision(17);
            request << "{\"id\":" << id << ",\"op\":\"" << (command==1?"browser_back":"browser_reload")
                    << "\",\"created\":" << now << '}';
            request.close();
            std::error_code error;
            if (request) std::filesystem::rename(path+".tmp",path+".json",error);
        }
        else if (command==1) key_symbol(display,XK_Left,window,Mod1Mask);
        else if (command==2) key_symbol(display,XK_F5,window);
        else if (command==3) key_symbol(display,XK_Escape,window);
        XFlush(display);
    };
    Window system_window=0;
    auto system_released_since=std::chrono::steady_clock::time_point{};
    auto system_mode=[&](bool wanted,bool user_return){
        smooth_scroll.cancel();native_scroll.cancel();
        cancel_pointer(display,overlays,cursor,mouse_button);
        keyboard_capture=false;keyboard_layout.pressed=-1;keyboard_layout.hover=-1;
        system_pointer.cancel();native_sources.clear();
        for(auto handle:{panel,keyboard_overlay,keyboard_upper,system_return})system_drain(overlays,handle);
        // Queued scene events are consumed below even while native input owns
        // focus. pointer.txt is sequence-deduplicated and never injected here.
        bool ok=true;
        for(auto handle:{panel,keyboard_overlay,keyboard_upper}){
            const auto method=wanted?vr::VROverlayInputMethod_Mouse:
                (handle==panel&&overlays->IsDashboardVisible()?vr::VROverlayInputMethod_Mouse:vr::VROverlayInputMethod_None);
            if(overlays->SetOverlayInputMethod(handle,method))ok=false;
            if(overlays->SetOverlayFlag(handle,vr::VROverlayFlags_MakeOverlaysInteractiveIfVisible,wanted))ok=false;
        }
        if(system_return){
            const bool show_return=wanted&&!unified_ui;
            if(overlays->SetOverlayInputMethod(system_return,show_return?vr::VROverlayInputMethod_Mouse:vr::VROverlayInputMethod_None))ok=false;
            if(overlays->SetOverlayFlag(system_return,vr::VROverlayFlags_MakeOverlaysInteractiveIfVisible,show_return))ok=false;
            if(show_return?overlays->ShowOverlay(system_return):overlays->HideOverlay(system_return))ok=false;
        }
        if(!wanted||!ok){
            system_pointer.leave(user_return||!ok);system_window=0;
            if(!ok){
                ++system_pointer_errors;
                // Every cleanup call is attempted. If focus cannot be released,
                // terminate the owned panel rather than trap the user's input.
                bool cleanup=true;
                for(auto handle:{panel,keyboard_overlay,keyboard_upper,system_return})if(handle){
                    if(overlays->SetOverlayFlag(handle,vr::VROverlayFlags_MakeOverlaysInteractiveIfVisible,false))cleanup=false;
                    if(overlays->SetOverlayInputMethod(handle,vr::VROverlayInputMethod_None))cleanup=false;
                }
                if(system_return&&overlays->HideOverlay(system_return))cleanup=false;
                if(!cleanup)running=0;
            }
        }
        return ok;
    };
    while (running && waitpid(child, &child_status, WNOHANG) == 0) {
        if(!scene_handles.tick(vr::VRApplications())){++system_pointer_errors;running=0;break;}
        const auto iteration_start=std::chrono::steady_clock::now();
        editable_focus.poll();
        if (keyboard_visible && !keyboard_capture) {
            const bool begin=iteration_start-editor_checked>std::chrono::milliseconds(500);
            if (begin) editor_checked=iteration_start;
            editable_focus.refresh_editor(begin);
        } else {
            editable_focus.state_probe.cancel();
        }
        if (keyboard_visible && keyboard_opened_for_editor && !keyboard_capture &&
                !editable_focus.editor && !editable_focus.control && !g_main_context_pending(nullptr)) {
            if (target_missing_since==std::chrono::steady_clock::time_point{}) target_missing_since=iteration_start;
            if (iteration_start-target_missing_since>std::chrono::milliseconds(200)) {
                keyboard_visible=false;
                keyboard_layout.pressed=-1;keyboard_layout.hover=-1;++keyboard_app_hides;
            }
        } else {
            target_missing_since={};
        }
        focus_poll_timing.add(std::chrono::duration_cast<std::chrono::microseconds>(
            std::chrono::steady_clock::now()-iteration_start).count());
        bool dashboard_visible = overlays->IsDashboardVisible();
#if defined(FRAME_CINEMA_COMPOSITOR_TEST) && !defined(FRAME_CINEMA_REAL_DASHBOARD)
        dashboard_visible=false;
#endif
        if (dashboard_visible != dashboard_was_visible) {
            smooth_scroll.cancel();native_scroll.cancel();
            if(system_pointer.active)system_mode(false,false);
            overlays->SetOverlayInputMethod(panel, dashboard_visible ? vr::VROverlayInputMethod_Mouse : vr::VROverlayInputMethod_None);
            cancel_pointer(display, overlays, cursor, mouse_button);
            dashboard_was_visible = dashboard_visible;
        }
        vr::VREvent_t system_event{};
        bool reference_changed=false;
        while (vr::VRSystem()->PollNextEvent(&system_event, sizeof(system_event))) {
            if (system_event.eventType == vr::VREvent_SeatedZeroPoseReset ||
                system_event.eventType == vr::VREvent_StandingZeroPoseReset ||
                system_event.eventType == vr::VREvent_ChaperoneUniverseHasChanged) {
                ++reference_reset_count;reference_reset_event=system_event.eventType;
                reference_changed=true;
                // A seated origin does not change this standing-space overlay.
                // For standing resets, convert the accepted anchor through the
                // unchanged raw universe instead of calibrating from scratch.
                const bool preserved=system_event.eventType==vr::VREvent_SeatedZeroPoseReset ||
                    refresh_standing(system_event.eventType==vr::VREvent_ChaperoneUniverseHasChanged);
                if(preserved) {++reference_preserved;}
                else {
                    placement->invalidate(placement_now());
                    if (placement_ready) ++placement_dropouts;
                    placement_ready=false;
                    placement_reason=placement->reason;
                    placement_visibility_error=overlays->HideOverlay(panel);
                    cancel_pointer(display,overlays,cursor,mouse_button);
                }
                // Preserve each event, including several resets in one poll.
                record_visibility(overlays,panel,window,dashboard_visible,true);
            }
        }
        sample_pose_history();
        if (ticks % 2 == 0 || reference_changed) {
            presentation.read(ipc,scene_session?scene_session:"",placement_now());
            presentation.apply(overlays,panel);
            if(!presentation.show) {
                keyboard_visible=false;keyboard_capture=false;keyboard_layout.pressed=-1;
                editable_focus.request=false;manual_keyboard=false;keyboard_auto_suppressed=true;
            }
            place(overlays,panel,ipc);
            if (!placement_ready) cancel_pointer(display,overlays,cursor,mouse_button);
            else {
                keyboard_transform=cinema_layout::keyboard_pose(screen_transform,screen_width);
                overlays->SetOverlayTransformAbsolute(keyboard_overlay,vr::TrackingUniverseStanding,&keyboard_transform);
                overlays->SetOverlayTransformAbsolute(keyboard_upper,vr::TrackingUniverseStanding,&keyboard_transform);
            }
        }
        if(system_pointer.enabled){
            std::ifstream focus_file(ipc+"/controller-focus.txt");
            auto lease=cinema_system_browser::read_lease(focus_file,scene_session?scene_session:"",placement_now());
            if(unified_ui&&lease.valid&&native_ui_handoff(ipc,scene_session?scene_session:"",lease.scene))lease.focused=true;
            const auto scene=vr::VRApplications()->GetCurrentSceneProcessId();
            cinema_system_browser::Guard guard{browser_pipe,bool(window),placement_ready,presentation.show,presentation.interactive,
                dashboard_visible,lease.valid&&scene==lease.scene,lease.valid,presentation.top};
            if(system_pointer.active&&(!system_pointer.continues(guard,placement->reference_generation(),placement->anchor_revision(),lease.scene)||window!=system_window))
                system_mode(false,false);
            // The return target is tied to the screen's accepted world frame,
            // closer to the viewer, above the keyboard and away from the floor.
            if(system_return&&placement_ready){
                auto pose=cinema_layout::keyboard_pose(screen_transform,screen_width);
                for(int r=0;r<3;++r)pose.m[r][3]+=screen_transform.m[r][1]*1.7f;
                if(overlays->SetOverlayTransformAbsolute(system_return,vr::TrackingUniverseStanding,&pose)){
                    ++system_pointer_errors;if(system_pointer.active)system_mode(false,true);guard.placement=false;
                }
            }
            if(system_pointer.can_enter(guard,lease)){
                system_pointer.enter(placement->reference_generation(),placement->anchor_revision(),lease.scene);system_window=window;
                if(system_mode(true,false))++system_pointer_entries;
            }
        }
        if (!dashboard_visible && placement_ready) {
            std::ifstream pointer(ipc+"/pointer.txt");
            if (pointer) forward_ray(display, window, overlays, cursor, pointer, mouse_button);
        }
        std::vector<std::filesystem::path> events;
        std::error_code fs_error;
        for (const auto& entry : std::filesystem::directory_iterator(ipc+"/input", fs_error))
            if (entry.path().extension()==".evt" || entry.path().extension()==".nav") events.push_back(entry.path());
        std::sort(events.begin(), events.end());
        for (const auto& file : events) {
            std::ifstream event_file(file);
            if (file.extension()==".nav") {
                uint64_t id=0;int command=0;double inspected_at=0;
                if (event_file>>id>>command) {
                    event_file>>inspected_at;
                    bool inspection_allowed=false;
                    if (inspected_at>0 && (command==1 || command==2)) {
                        vr::TrackedDevicePose_t poses[vr::k_unMaxTrackedDeviceCount]{};
                        vr::VRSystem()->GetDeviceToAbsoluteTrackingPose(vr::TrackingUniverseStanding,0,poses,vr::k_unMaxTrackedDeviceCount);
                        bool tracked=false;
                        for (uint32_t i=0;i<vr::k_unMaxTrackedDeviceCount;++i)
                            if (poses[i].bPoseIsValid && vr::VRSystem()->GetTrackedDeviceClass(i)==vr::TrackedDeviceClass_Controller) tracked=true;
                        const auto activity=vr::VRSystem()->GetTrackedDeviceActivityLevel(vr::k_unTrackedDeviceIndex_Hmd);
                        const auto now=std::chrono::duration<double>(std::chrono::system_clock::now().time_since_epoch()).count();
                        inspection_allowed=inspection_navigation_allowed(inspected_at,now,tracked,
                            activity==vr::k_EDeviceActivityLevel_UserInteraction || activity==vr::k_EDeviceActivityLevel_UserInteraction_Timeout);
                    }
                    if ((!system_pointer.active||unified_ui)&&(inspected_at>0 ? inspection_allowed : !dashboard_visible)) navigate(command,id);
                }
            } else if (!dashboard_visible && placement_ready) forward_ray(display,window,overlays,cursor,event_file,mouse_button);
            std::filesystem::remove(file, fs_error);
        }
        if (keyboard_dismissed) {
            editable_focus.request=false; manual_keyboard=false; browser_released={}; keyboard_dismissed=false; keyboard_auto_suppressed=true;
        }
        if (dashboard_visible) {
            overlays->HideOverlay(cursor);overlays->HideOverlay(beam);
        } else if (!system_pointer.active&&std::chrono::steady_clock::now()-pointer_seen > std::chrono::milliseconds(250))
            cancel_pointer(display, overlays, cursor, mouse_button);
        if (browser_released != std::chrono::steady_clock::time_point{} && std::chrono::steady_clock::now()-browser_released > std::chrono::milliseconds(200)) {
            if (editable_focus.editable) editable_focus.request = true;
            else if (!editable_focus.editor && keyboard_visible) {
                keyboard_visible=false; keyboard_capture=false; keyboard_auto_suppressed=true;
                editable_focus.request=false; keyboard_layout.pressed=-1; ++keyboard_app_hides;
            }
            browser_released = {};
        }
        int command=0;uint64_t command_id=0;
        std::ifstream commands(ipc+"/browser-command.txt");
        if ((commands>>command_id>>command) && command_id!=browser_command && window) {
            browser_command=command_id;navigate(command,command_id);
        }
        if (keyboard_auto_suppressed) editable_focus.request=false;
        keyboard_target_ready=editable_focus.editor!=nullptr || editable_focus.control!=nullptr;
        ++ticks;
        {
            uint64_t request = 0;
            std::ifstream keyboard_file(ipc + "/keyboard.request");
            if ((keyboard_file >> request) && request != keyboard_request) {
                keyboard_request = request;
                manual_keyboard = true;
            }
            if ((manual_keyboard || editable_focus.request) && window && !dashboard_visible && presentation.show) {
                const bool automatic=!manual_keyboard;
                manual_keyboard = false;
                editable_focus.request = false;
                if (!keyboard_visible) {
                    keyboard_opened_for_editor=automatic;
                    XSetInputFocus(display, window, RevertToParent, CurrentTime);
                    XFlush(display);
                    keyboard_layout.pressed=-1; keyboard_layout.hover=-1;
                    keyboard_capture=false; keyboard_layout.shifted=false;
                    if (!keyboard_ready) keyboard_ready=prepare_keyboard(overlays);
                    keyboard_visible=keyboard_ready;
                    if (keyboard_visible) ++keyboard_shows;
                }
            }
        }
        if (ticks % 60 == 1) {
            Window next = browser_window(display, DefaultRootWindow(display));
            ambient_worker.target(next);
            if (next != window) {
                if(system_pointer.active)system_mode(false,false);
                if (window) { cancel_pointer(display,overlays,cursor,mouse_button);editable_focus.clear_editor(); }
                forward_window(display,target,panel,window,next);
                window = next;
                if (!window) keyboard_visible=false;
            }
            if (window) {
                XWindowAttributes attributes{};
                if (XGetWindowAttributes(display, window, &attributes)) {
                    vr::HmdVector2_t scale = {{float(attributes.width), float(attributes.height)}};
                    overlays->SetOverlayMouseScale(panel, &scale);
                }
            }
        }
        // Gamescope's primary surface is only a transport. Once forwarding is
        // attached, leaving it visible adds a foreign opaque layer over hands.
        if(unified_ui&&window&&ticks%12==1){
            vr::VROverlayHandle_t current_transport=0;
            if(!overlays->FindOverlay("frame-lab.cinema.video",&current_transport)
                &&current_transport==transport&&overlays->GetOverlayRenderingPid(transport)==renderer){
                if(overlays->IsOverlayVisible(transport)&&overlays->HideOverlay(transport))++transport_hide_errors;
            }
        }
        if (ticks % 12 == 1) {
            uint32_t width = 0, height = 0;
            overlays->GetOverlayTextureSize(panel, &width, &height);
            std::ofstream status(ipc + "/panel-status.tmp");
            status << "{\"window_attached\":" << (window ? "true" : "false")
                   << ",\"placement_ready\":" << (placement_ready?"true":"false")
                   << ",\"placement_reason\":\"" << placement_reason << '"'
                   << ",\"placement_dropouts\":" << placement_dropouts
                   << ",\"rendered_screen_width\":" << cinema_projection::browser(screen_transform,screen_width).width
                   << ",\"distant_projection\":" << (screen_width>6.f?"true":"false")
                   << ",\"placement_width_error\":" << placement_width_error
                   << ",\"placement_transform_error\":" << placement_transform_error
                   << ",\"placement_visibility_error\":" << placement_visibility_error
                   << ",\"placement_revision\":" << placement->anchor_revision()
                   << ",\"placement_generation\":" << placement->reference_generation()
                   << ",\"reference_preserved\":" << reference_preserved
                   << ",\"synchronized_samples\":" << synchronized_samples
                   << ",\"missing_timed_samples\":" << missing_timed_samples
                   << ",\"standing_reference_known\":" << (standing_known?"true":"false")
                   << ",\"visibility_write_failures\":" << visibility_write_failures
                   << ",\"visible\":" << (overlays->IsOverlayVisible(panel) ? "true" : "false")
                   << ",\"picture_top\":" << presentation.top << ",\"presentation_error\":" << presentation.error << ",\"presentation_show\":" << (presentation.show?"true":"false")
                   << ",\"width\":" << width << ",\"height\":" << height
                   << ",\"pointer_packets\":" << pointer_packets << ",\"pointer_clicks\":" << pointer_clicks
                   << ",\"transport_hidden\":" << (!overlays->IsOverlayVisible(transport)?"true":"false")
                   << ",\"transport_hide_errors\":" << transport_hide_errors
                   << ",\"native_scroll_enabled\":" << (native_scroll_enabled?"true":"false")
                   << ",\"native_scroll_sent\":" << native_scroll.sent
                   << ",\"native_scroll_rejected\":" << native_scroll.rejected
                   << ",\"native_scroll_placements\":" << native_scroll.placements
                   << ",\"observed_browser_downs\":" << observed_browser_downs << ",\"observed_browser_ups\":" << observed_browser_ups
                   << ",\"native_moves\":" << native_moves << ",\"native_downs\":" << native_downs << ",\"native_ups\":" << native_ups
                   << ",\"native_source_rejects\":" << native_source_rejects << ",\"native_gate_rejects\":" << native_gate_rejects << ",\"native_hover_attributions\":" << native_hover_attributions
                   << ",\"system_pointer_enabled\":" << (system_pointer.enabled?"true":"false")
                   << ",\"system_pointer_active\":" << (system_pointer.active?"true":"false")
                   << ",\"system_pointer_require_up\":" << (system_pointer.require_up?"true":"false")
                   << ",\"system_pointer_entries\":" << system_pointer_entries << ",\"system_pointer_returns\":" << system_pointer_returns
                   << ",\"system_pointer_errors\":" << system_pointer_errors
                   << ",\"mouse_backend\":\"direct-x-window\",\"mouse_moves\":" << browser_pointer.moves
                   << ",\"mouse_downs\":" << browser_pointer.downs << ",\"mouse_ups\":" << browser_pointer.ups
                   << ",\"mouse_cancels\":" << browser_pointer.cancels << ",\"mouse_send_failures\":" << browser_pointer.failures
                   << ",\"down_events\":" << down_events << ",\"ray_hits\":" << ray_hits
                   << ",\"cursor_error\":" << cursor_error << ",\"cursor_visible\":" << (overlays->IsOverlayVisible(cursor)?"true":"false")
                   << ",\"beam_ready\":" << (beam && !beam_error?"true":"false") << ",\"beam_error\":" << beam_error
                   << ",\"beam_visible\":" << (overlays->IsOverlayVisible(beam)?"true":"false")
                   << ",\"keyboard_ray_hits\":" << keyboard_ray_hits
                   << ",\"keyboard_error\":" << keyboard_error << ",\"keyboard_visible\":" << (keyboard_visible?"true":"false")
                   << ",\"keyboard_shows\":" << keyboard_shows << ",\"keyboard_char_events\":" << keyboard_chars
                   << ",\"key_focus_restores\":" << key_focus_restores << ",\"key_focus_failures\":" << key_focus_failures
                   << ",\"keyboard_backend\":\"direct-x-window\",\"key_send_failures\":" << key_send_failures
                   << ",\"keyboard_dispatches\":" << keyboard_dispatches << ",\"keyboard_blocked\":" << keyboard_blocked
                   << ",\"keyboard_target_ready\":" << (keyboard_target_ready?"true":"false")
                   << ",\"editor_focus_restores\":" << editable_focus.restores << ",\"editor_focus_failures\":" << editable_focus.failures
                   << ",\"editor_expirations\":" << editable_focus.expirations
                   << ",\"editor_refresh_failures\":" << editable_focus.refresh_failures
                   << ",\"has_editor\":" << (editable_focus.editor?"true":"false")
                   << ",\"has_control\":" << (editable_focus.control?"true":"false")
                   << ",\"control_role\":" << int(editable_focus.control_role)
                   << ",\"keyboard_automatic\":" << (keyboard_opened_for_editor?"true":"false")
                   << ",\"editable_focused\":" << (editable_focus.editable?"true":"false")
                   << ",\"keyboard_owner\":\"cinema\",\"keyboard_app_hides\":" << keyboard_app_hides
                   << ",\"keyboard_ready\":" << (keyboard_ready?"true":"false") << ",\"keyboard_texture_uploads\":" << keyboard_uploads
                   << ",\"keyboard_presentations\":" << keyboard_presentations
                   << ",\"highlight_error\":" << highlight_error << ",\"highlight_failures\":" << highlight_failures
                   << ",\"focus_watcher\":" << (editable_focus.available?"true":"false") << ",\"focus_events\":" << editable_focus.events
                   << ",\"heartbeat\":" << ticks
                   << ",\"dashboard_visible\":" << (dashboard_visible ? "true" : "false")
                   << ",\"event_queue_timing\":";
            event_queue_timing.write(status);
            status << ",\"focus_poll_timing\":";focus_poll_timing.write(status);
            status << ",\"input_work_timing\":";input_work_timing.write(status);
            status << '}';
            status.close();
            std::rename((ipc + "/panel-status.tmp").c_str(), (ipc + "/panel-status.json").c_str());
        }
        vr::TrackedDevicePose_t system_input_poses[vr::k_unMaxTrackedDeviceCount]{};
        if(system_pointer.active)vr::VRSystem()->GetDeviceToAbsoluteTrackingPose(vr::TrackingUniverseStanding,0,system_input_poses,vr::k_unMaxTrackedDeviceCount);
        auto system_device_tracked=[&](uint32_t device){
            return device<vr::k_unMaxTrackedDeviceCount&&vr::VRSystem()->GetTrackedDeviceClass(device)==vr::TrackedDeviceClass_Controller
                &&system_input_poses[device].bDeviceIsConnected&&system_input_poses[device].bPoseIsValid
                &&system_input_poses[device].eTrackingResult==vr::TrackingResult_Running_OK;
        };
        // Validate the actual holder before any queued Up can commit its key.
        // Pose data is local to this iteration and is never recorded.
        if(system_pointer.active&&system_pointer.held_tracking(system_device_tracked(system_pointer.held_device)))
            cancel_pointer(display,overlays,cursor,mouse_button);
        auto system_event_input=[&](cinema_system_browser::Target target,const vr::VREvent_t& event){
            if(!system_pointer.active||dashboard_visible)return;
            if(event.eventType==vr::VREvent_FocusLeave){
                auto source=event.trackedDeviceIndex;
                if(source>=vr::k_unMaxTrackedDeviceCount||vr::VRSystem()->GetTrackedDeviceClass(source)!=vr::TrackedDeviceClass_Controller)source=UINT32_MAX;
                native_sources.leave(target,source);
                if(system_pointer.focus_leave(target,source))cancel_pointer(display,overlays,cursor,mouse_button);
                if(target==cinema_system_browser::Target::Keyboard)keyboard_layout.hover=-1;
                else if(target==cinema_system_browser::Target::Browser){browser_pointer.leave(display);smooth_scroll.cancel();native_scroll.cancel();}
                return;
            }
            const bool move=event.eventType==vr::VREvent_MouseMove,down=event.eventType==vr::VREvent_MouseButtonDown,up=event.eventType==vr::VREvent_MouseButtonUp;
            native_moves+=move;native_downs+=down;native_ups+=up;
            const double native_now=double(monotonic_ns())*1e-9;
            uint32_t device=event.trackedDeviceIndex;
            const bool explicit_controller=device<vr::k_unMaxTrackedDeviceCount
                &&vr::VRSystem()->GetTrackedDeviceClass(device)==vr::TrackedDeviceClass_Controller;
            if(explicit_controller&&!system_device_tracked(device)){++native_source_rejects;return;}
            if(!explicit_controller){
                if(move){++native_source_rejects;return;}
                device=native_sources.resolve(target,UINT32_MAX,native_now);
                if(device!=UINT32_MAX)++native_hover_attributions;
            }
            if(!system_device_tracked(device)){++native_source_rejects;return;}
            if(move)native_sources.move(target,device,native_now,event.eventAgeSeconds);
            auto native_press=[&](){const bool accepted=system_pointer.native_down(target,device);if(!accepted)++native_gate_rejects;return accepted;};
            if(target==cinema_system_browser::Target::Browser&&(event.eventType==vr::VREvent_ScrollSmooth||event.eventType==vr::VREvent_ScrollDiscrete)){
                XWindowAttributes size{};
                if(window&&XGetWindowAttributes(display,window,&size)){
                    bool accepted=true;
                    if(native_scroll_enabled){
                        accepted=native_scroll.send(window,browser_pointer.x,browser_pointer.y,size.width,size.height,
                            event.data.scroll.xdelta,event.data.scroll.ydelta,event.eventAgeSeconds,native_now,
                            [&](int x,int y){
                                const auto errors=x_errors;
                                XSetInputFocus(display,window,RevertToParent,CurrentTime);
                                XWarpPointer(display,None,window,0,0,0,0,x,y);
                                XSync(display,False);return errors==x_errors;
                            },[&](double dx,double dy){
                                vr::VREvent_t wheel{};wheel.eventType=vr::VREvent_ScrollSmooth;
                                wheel.trackedDeviceIndex=vr::k_unTrackedDeviceIndexInvalid;
                                wheel.data.scroll.xdelta=float(dx);wheel.data.scroll.ydelta=float(dy);
                                native_scroll_view->PostOverlayEvent(transport,&wheel);
                            });
                    }
                    // In native mode this snapshot only defers media/observer work.
                    // The bridge must not turn it into a second CDP wheel stream.
                    if(accepted)smooth_scroll.add(event.data.scroll.xdelta,event.data.scroll.ydelta,browser_pointer.x,browser_pointer.y,size.width,size.height);
                }
                XFlush(display);return;
            }
            if(!move&&!down&&!up)return;
            if((down||up)&&event.data.mouse.button!=vr::VRMouseButton_Left)return;
            if(target==cinema_system_browser::Target::Return){
                const auto pixel=cinema_system_browser::pixels(event.data.mouse.x,event.data.mouse.y,1024,192);
                if(down&&pixel.valid&&native_press()){
                    ++system_pointer_returns;keyboard_visible=false;keyboard_auto_suppressed=true;editable_focus.request=false;manual_keyboard=false;
                    system_mode(false,true);
                }else if(up)system_pointer.native_up(target,device);
                return;
            }
            if(target==cinema_system_browser::Target::Keyboard){
                if(!keyboard_visible)return;
                const auto pixel=cinema_system_browser::pixels(event.data.mouse.x,event.data.mouse.y,CinemaKeyboard::width,CinemaKeyboard::height);
                int key=pixel.valid?keyboard_layout.hit((pixel.x+.5f)/CinemaKeyboard::width,(pixel.y+.5f)/CinemaKeyboard::height):-1;
                if(keyboard_capture)key=keyboard_layout.held(key,pixel.valid);
                keyboard_layout.hover=key;
                if(down&&key>=0&&native_press()){keyboard_capture=true;keyboard_layout.pressed=key;}
                if(up){
                    if(system_pointer.owns(target,device)){
                        if(system_pointer.native_up(target,device)&&keyboard_capture)system_keyboard_release(display,window,key);
                        else {keyboard_capture=false;keyboard_layout.pressed=-1;}
                    }else system_pointer.native_up(target,device);
                }
                return;
            }
            XWindowAttributes attributes{};
            if(!window||!XGetWindowAttributes(display,window,&attributes))return;
            const auto pixel=cinema_system_browser::pixels(event.data.mouse.x,event.data.mouse.y,attributes.width,attributes.height,presentation.top);
            // A native release outside the image still unlocks this hand.
            if(up&&!pixel.valid){system_pointer.native_up(target,device);mouse_button=0;return;}
            if(!pixel.valid){if(up&&system_pointer.owns(target,device)){system_pointer.native_up(target,device);mouse_button=0;}return;}
            browser_pointer.move(display,window,pixel.x,pixel.y);
            if(down&&native_press()){
                smooth_scroll.cancel();native_scroll.cancel();
                Window unused=0;int x=0,y=0;XTranslateCoordinates(display,window,DefaultRootWindow(display),0,0,&x,&y,&unused);
                editable_focus.browser_click(x+pixel.x,y+pixel.y);keyboard_auto_suppressed=false;XSetInputFocus(display,window,RevertToParent,CurrentTime);
                // Complete the X click at press coordinates before any hand
                // motion: the native trigger never becomes a browser drag.
                if(browser_pointer.click(display,window,pixel.x,pixel.y)){mouse_button=1;++pointer_clicks;browser_released=std::chrono::steady_clock::now();}
            }
            if(up&&system_pointer.owns(target,device)){system_pointer.native_up(target,device);mouse_button=0;browser_released=std::chrono::steady_clock::now();}
            XFlush(display);
        };
        vr::VREvent_t event{};
        for(auto handle:{system_return,keyboard_overlay,keyboard_upper}){
            unsigned count=0;
            while(handle&&count++<256&&overlays->PollNextOverlayEvent(handle,&event,sizeof(event))){
                if(handle!=system_return&&handle!=keyboard_shown)continue;
                system_event_input(handle==system_return?cinema_system_browser::Target::Return:cinema_system_browser::Target::Keyboard,event);
            }
        }
        while (overlays->PollNextOverlayEvent(panel, &event, sizeof(event))) {
            observed_browser_downs+=event.eventType==vr::VREvent_MouseButtonDown;
            observed_browser_ups+=event.eventType==vr::VREvent_MouseButtonUp;
            if(system_pointer.active&&!dashboard_visible){system_event_input(cinema_system_browser::Target::Browser,event);continue;}
            if (!window || !placement_ready || !presentation.show || !presentation.interactive) continue;
            if (event.eventType==vr::VREvent_FocusLeave) {
                if (dashboard_visible) cancel_pointer(display,overlays,cursor,mouse_button);
                continue;
            }
            if (event.eventType == vr::VREvent_MouseMove || event.eventType == vr::VREvent_MouseButtonDown || event.eventType == vr::VREvent_MouseButtonUp) {
                if (!overlays->IsDashboardVisible()) continue;
                XWindowAttributes attributes{};
                if (!XGetWindowAttributes(display, window, &attributes)) continue;
                Window unused;
                int x, y;
                XTranslateCoordinates(display, window, DefaultRootWindow(display), 0, 0, &x, &y, &unused);
                const int px=std::clamp(int(event.data.mouse.x),0,attributes.width-1);
                const int py=std::clamp(attributes.height-1-int(event.data.mouse.y),0,attributes.height-1);
                browser_pointer.move(display,window,px,py);
                if (event.eventType == vr::VREvent_MouseButtonDown) {
                    editable_focus.browser_click(x+px,y+py);
                    keyboard_auto_suppressed=false;
                    XSetInputFocus(display,window,RevertToParent,CurrentTime);
                    const unsigned button=event.data.mouse.button==vr::VRMouseButton_Right?3:1;
                    if (browser_pointer.press(display,window,px,py,button)) mouse_button=button;
                } else if (event.eventType==vr::VREvent_MouseButtonUp && mouse_button) {
                    browser_pointer.release(display,window,px,py);mouse_button=0;
                    browser_released=std::chrono::steady_clock::now();
                }
            } else if (event.eventType==vr::VREvent_ScrollSmooth || event.eventType==vr::VREvent_ScrollDiscrete) {
                if (!overlays->IsDashboardVisible()) continue;
                if (event.data.scroll.ydelta!=0)
                    browser_pointer.scroll(display,window,browser_pointer.x,browser_pointer.y,event.data.scroll.ydelta>0?4:5);
            }
            // Input is forwarded live; no text, screenshots or browser data are logged.
            XFlush(display);
        }
        smooth_scroll.flush(ipc);
        present_keyboard(overlays,dashboard_visible || !placement_ready || !presentation.show);
        if(system_pointer.enabled){
            const bool released=system_triggers_released();const auto now=std::chrono::steady_clock::now();
            if(released&&system_pointer.held!=cinema_system_browser::Target::Empty){
                if(system_released_since==std::chrono::steady_clock::time_point{})system_released_since=now;
                else if(now-system_released_since>std::chrono::milliseconds(80)){
                    // A lost native MouseUp cancels; it never synthesizes a key.
                    system_pointer.cancel();cancel_pointer(display,overlays,cursor,mouse_button);system_released_since={};
                }
            }else system_released_since={};
            system_pointer.released(released);
        }
        if(stereo){stereo->tick(window,placement_ready,presentation.show,presentation.interactive,dashboard_visible,screen_transform,screen_width,presentation.top);stereo_active=stereo->active;}
        record_visibility(overlays,panel,window,dashboard_visible,ticks%12==1);
        if (visibility_history_dirty && ticks%12==1) {
            visibility_history_dirty=!visibility_history.save(ipc+"/panel-visibility.json");
            if (visibility_history_dirty) ++visibility_write_failures;
        }
        input_work_timing.add(std::chrono::duration_cast<std::chrono::microseconds>(
            std::chrono::steady_clock::now()-iteration_start).count());
        std::this_thread::sleep_until(iteration_start+std::chrono::milliseconds(8));
    }
    if(std::getenv("FRAME_CINEMA_LEASE_DIAGNOSTICS"))std::fprintf(stderr,"panel_exit running=%d signal=%d child_status=%d system_errors=%llu\n",int(running),int(stop_signal),child_status,(unsigned long long)system_pointer_errors);
    stereo.reset();stereo_active=false;
    // A lost owner epoch invalidates cached borrowed handles. Do not run the
    // normal overlay cleanup against them; creator timeout/release owns it.
    if(scene_handles.cleanup_safe(overlays)){
        if(system_pointer.enabled)system_mode(false,false);
        if(system_return){overlays->HideOverlay(system_return);overlays->ClearOverlayTexture(system_return);scene_handles.destroy(overlays,system_return);}
    }
    browser_pointer.cancel(display);
    if (visibility_history_dirty) visibility_history.save(ipc+"/panel-visibility.json");
    ambient_worker.stop();
    forward_window(display,target,panel,window,0);
    XFlush(display);
    overlays->DestroyOverlay(cursor);
    overlays->DestroyOverlay(beam);
    scene_handles.destroy(overlays,keyboard_overlay);
    scene_handles.destroy(overlays,keyboard_upper);
    scene_handles.destroy(overlays,keyboard_highlight);
    scene_handles.destroy(overlays,panel);
    // Final borrowed-handle operation: detach window/clear own textures before
    // telling the creator that it may destroy this epoch's overlays.
    if(!scene_handles.release(overlays))++system_pointer_errors;
    kill(child, SIGTERM);
    vr::VR_Shutdown();
    XCloseDisplay(display);
    return 0;
}
