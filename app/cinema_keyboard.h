#pragma once
#include <cairo/cairo.h>
#include <string>
#include <vector>
#include <cmath>
#include <algorithm>

// Only the key layout and one pending key are retained; never the field's text.
class CinemaKeyboard {
public:
    static constexpr int width=1400, height=540;
    static constexpr int texture_scale=2, texture_width=width*texture_scale, texture_height=height*texture_scale;
    static constexpr float metres=2.f;
    enum Action { Text, Shift, Hide };
    struct Key { double x,y,w,h; std::string normal, shifted; Action action=Text; };
    std::vector<Key> keys;
    bool shifted=false;
    int hover=-1, pressed=-1;
    CinemaKeyboard() {
        keys.push_back({1215,18,155,48,"Hide","Hide",Hide});
        row("`1234567890-=","~!@#$%^&*()_+",70,80);
        keys.push_back({1168,80,170,72,"Backspace","Backspace"});
        keys.push_back({28,160,110,72,"Tab","Tab"});
        row("qwertyuiop[]\\","QWERTYUIOP{}|",146,160);
        row("asdfghjkl;'","ASDFGHJKL:\"",130,240);
        keys.push_back({1060,240,210,72,"Enter","Enter"});
        keys.push_back({50,320,150,72,"Shift","Shift",Shift});
        row("zxcvbnm,./","ZXCVBNM<>?",208,320);
        keys.push_back({1050,320,120,72,"Left","Left"});
        keys.push_back({1178,320,120,72,"Right","Right"});
        keys.push_back({320,410,760,82,"Space","Space"});
    }
    // One corner rule for the keys and their hover highlight: Done is a pill, every other key 18 units.
    static double corner_radius(const Key& k) { return k.action==Hide ? k.h/2 : 18; }
    // The hover highlight for one key: white, its alpha the key's own rounded rectangle at the key's
    // own size, so it lies exactly on the key. A square highlight stretched to the space bar's
    // 760x82 turned its corners into long ovals. Drawn without Cairo so it can be checked anywhere.
    static std::vector<unsigned char> highlight_pixels(const Key& k,int scale) {
        const int w=int(std::lround(k.w*scale)), h=int(std::lround(k.h*scale));
        const double r=corner_radius(k), half_w=k.w/2, half_h=k.h/2;
        std::vector<unsigned char> pixels(size_t(w)*h*4,255);
        for (int y=0;y<h;++y) for (int x=0;x<w;++x) {
            const double qx=std::abs((x+.5)/scale-half_w)-(half_w-r), qy=std::abs((y+.5)/scale-half_h)-(half_h-r);
            const double outside=std::hypot(std::max(qx,0.),std::max(qy,0.)), inside=std::min(std::max(qx,qy),0.);
            const double coverage=std::clamp(.5-(outside+inside-r)*scale,0.,1.);
            pixels[(size_t(y)*w+x)*4+3]=static_cast<unsigned char>(std::lround(coverage*255));
        }
        return pixels;
    }
    // While the trigger is held, the ray keeps the key it pressed for as long as it stays on the keyboard.
    // Pulling a trigger moves a VR ray a little, and a release over the gap between keys or over the next key
    // dropped the press without a sign. Leaving the keyboard before letting go still cancels it.
    int held(int key,bool on_keyboard) const { return on_keyboard && pressed>=0 ? pressed : key; }
    int hit(float u,float v) const {
        const auto x=u*width,y=v*height;
        for (size_t i=0;i<keys.size();++i) {
            const auto& k=keys[i];
            if (x>=k.x && x<k.x+k.w && y>=k.y && y<k.y+k.h) return int(i);
        }
        return -1;
    }
    std::string release(int target,bool& hide) {
        const int original=pressed; pressed=-1;
        if (original<0 || original!=target || size_t(target)>=keys.size()) return "";
        const auto& k=keys[target];
        if (k.action==Hide) { hide=true; return ""; }
        if (k.action==Shift) { shifted=!shifted; return ""; }
        if (k.normal=="Backspace") return "\b";
        if (k.normal=="Tab") return "\t";
        if (k.normal=="Enter") return "\r"; // Receiver closes only after successful dispatch.
        if (k.normal=="Space") return " ";
        if (k.normal=="Left") return "\x1b[D";
        if (k.normal=="Right") return "\x1b[C";
        const auto text=shifted?k.shifted:k.normal;
        shifted=false; // One-shot Shift; never silently act as Caps Lock.
        return text;
    }
    std::vector<unsigned char> pixels(int scale=1) const {
        // 0.4.34 design pass: visionOS-style glass keyboard. Geometry, hit
        // testing and key semantics are unchanged; only the drawing differs.
        const int pixel_width=width*scale, pixel_height=height*scale;
        auto* surface=cairo_image_surface_create(CAIRO_FORMAT_ARGB32,pixel_width,pixel_height);
        auto* c=cairo_create(surface);
        cairo_scale(c,scale,scale);
        cairo_set_antialias(c,CAIRO_ANTIALIAS_BEST);
        cairo_set_source_rgba(c,0,0,0,0); cairo_set_operator(c,CAIRO_OPERATOR_SOURCE); cairo_paint(c);
        cairo_set_operator(c,CAIRO_OPERATOR_OVER);
        // Soft contact shadow so the slab reads as a floating object.
        for (int i=0;i<6;++i) {
            rounded(c,12-i*1.5,10-i*1.0,width-24+i*3.0,height-16+i*2.5,38+i*1.5);
            cairo_set_source_rgba(c,0,0,0,.035); cairo_fill(c);
        }
        // Glass body: neutral graphite, lighter at the top like overhead light.
        auto* glass=cairo_pattern_create_linear(0,0,0,height);
        cairo_pattern_add_color_stop_rgba(glass,0,.235,.245,.265,.90);
        cairo_pattern_add_color_stop_rgba(glass,.55,.165,.172,.188,.91);
        cairo_pattern_add_color_stop_rgba(glass,1,.125,.130,.145,.93);
        rounded(c,12,8,width-24,height-16,38);
        cairo_set_source(c,glass); cairo_fill(c);
        cairo_pattern_destroy(glass);
        // Diffuse sheen from the upper left.
        auto* sheen=cairo_pattern_create_radial(width*.22,-60,10,width*.22,-60,width*.75);
        cairo_pattern_add_color_stop_rgba(sheen,0,1,1,1,.10);
        cairo_pattern_add_color_stop_rgba(sheen,1,1,1,1,0);
        rounded(c,12,8,width-24,height-16,38);
        cairo_set_source(c,sheen); cairo_fill(c);
        cairo_pattern_destroy(sheen);
        // Specular rim: bright along the top edge, fading towards the bottom.
        auto* rim=cairo_pattern_create_linear(0,8,0,height-8);
        cairo_pattern_add_color_stop_rgba(rim,0,1,1,1,.55);
        cairo_pattern_add_color_stop_rgba(rim,.18,1,1,1,.16);
        cairo_pattern_add_color_stop_rgba(rim,1,1,1,1,.07);
        rounded(c,12.5,8.5,width-25,height-17,37.5);
        cairo_set_source(c,rim); cairo_set_line_width(c,1.2); cairo_stroke(c);
        cairo_pattern_destroy(rim);
        cairo_select_font_face(c,"sans-serif",CAIRO_FONT_SLANT_NORMAL,CAIRO_FONT_WEIGHT_NORMAL);
        cairo_font_extents_t font{};
        cairo_set_font_size(c,24); cairo_set_source_rgba(c,1,1,1,.55);
        cairo_move_to(c,40,50); cairo_show_text(c,"Keyboard");
        for (size_t i=0;i<keys.size();++i) {
            const auto& k=keys[i];
            const bool letter=k.action==Text && k.normal.size()==1;
            const bool selected=int(i)==pressed || (k.action==Shift && shifted);
            const bool done=k.action==Hide;
            const double radius=corner_radius(k);
            // Key platter: lighter glass for characters, recessed for functions.
            double top=letter?.20:.115, bottom=letter?.15:.085;
            if (done) { top=.24; bottom=.20; }
            if (int(i)==hover) { top+=.07; bottom+=.07; }
            auto* fill=cairo_pattern_create_linear(0,k.y,0,k.y+k.h);
            if (selected) {
                cairo_pattern_add_color_stop_rgba(fill,0,.97,.98,1,.96);
                cairo_pattern_add_color_stop_rgba(fill,1,.88,.90,.94,.96);
            } else {
                cairo_pattern_add_color_stop_rgba(fill,0,1,1,1,top);
                cairo_pattern_add_color_stop_rgba(fill,1,1,1,1,bottom);
            }
            rounded(c,k.x,k.y,k.w,k.h,radius);
            cairo_set_source(c,fill); cairo_fill(c);
            cairo_pattern_destroy(fill);
            // Hairline top highlight gives each key a physical edge.
            auto* edge=cairo_pattern_create_linear(0,k.y,0,k.y+k.h);
            cairo_pattern_add_color_stop_rgba(edge,0,1,1,1,selected?0:.30);
            cairo_pattern_add_color_stop_rgba(edge,.35,1,1,1,0);
            rounded(c,k.x+.5,k.y+.5,k.w-1,k.h-1,radius-.5);
            cairo_set_source(c,edge); cairo_set_line_width(c,1); cairo_stroke(c);
            cairo_pattern_destroy(edge);
            const double ink=selected?.08:.97;
            const double cx=k.x+k.w/2,cy=k.y+k.h/2;
            cairo_set_source_rgba(c,ink,ink+.01,ink+.03,selected?1:.96);
            cairo_set_line_width(c,2.6); cairo_set_line_cap(c,CAIRO_LINE_CAP_ROUND); cairo_set_line_join(c,CAIRO_LINE_JOIN_ROUND);
            if (k.normal=="Left" || k.normal=="Right") {
                // Drawn directly: the device's Cairo font lacks arrow glyphs.
                const double direction=k.normal=="Left"?-1:1;
                cairo_move_to(c,cx-direction*13,cy); cairo_line_to(c,cx+direction*13,cy);
                cairo_move_to(c,cx+direction*4,cy-9); cairo_line_to(c,cx+direction*13,cy); cairo_line_to(c,cx+direction*4,cy+9);
                cairo_stroke(c);
                continue;
            }
            if (k.normal=="Backspace") {
                // Delete-left key: a tag outline with an x.
                const double w=40,h=28,l=cx-w/2+4;
                cairo_move_to(c,l-10,cy); cairo_line_to(c,l,cy-h/2); cairo_line_to(c,l+w,cy-h/2);
                cairo_line_to(c,l+w,cy+h/2); cairo_line_to(c,l,cy+h/2); cairo_close_path(c);
                cairo_set_line_width(c,2.2); cairo_stroke(c);
                cairo_move_to(c,l+13,cy-6); cairo_line_to(c,l+25,cy+6);
                cairo_move_to(c,l+25,cy-6); cairo_line_to(c,l+13,cy+6); cairo_stroke(c);
                continue;
            }
            if (k.action==Shift) {
                // Shift arrow; filled while the one-shot Shift is armed.
                cairo_move_to(c,cx,cy-15); cairo_line_to(c,cx+15,cy+1); cairo_line_to(c,cx+7,cy+1);
                cairo_line_to(c,cx+7,cy+14); cairo_line_to(c,cx-7,cy+14); cairo_line_to(c,cx-7,cy+1);
                cairo_line_to(c,cx-15,cy+1); cairo_close_path(c);
                if (selected) cairo_fill(c); else { cairo_set_line_width(c,2.2); cairo_stroke(c); }
                continue;
            }
            std::string label=shifted?k.shifted:k.normal;
            if (done) label="Done";
            else if (k.normal=="Enter") label="return";
            else if (k.normal=="Tab") label="tab";
            else if (k.normal=="Space") label="space";
            cairo_set_font_size(c,label.size()>2 ? 24 : 33);
            cairo_font_extents(c,&font);
            cairo_text_extents_t extents{}; cairo_text_extents(c,label.c_str(),&extents);
            if (label.size()>2 && !done) cairo_set_source_rgba(c,ink,ink+.01,ink+.03,selected?1:.78);
            // Center on the font's cap band, not each glyph's ink box, so
            // letters with descenders share one baseline across a row.
            const double baseline=cy+(font.ascent-font.descent)/2-1;
            cairo_move_to(c,cx-extents.width/2-extents.x_bearing,baseline);
            cairo_show_text(c,label.c_str());
        }
        cairo_surface_flush(surface);
        const auto* data=cairo_image_surface_get_data(surface);
        const int stride=cairo_image_surface_get_stride(surface);
        std::vector<unsigned char> result(pixel_width*pixel_height*4);
        for (int y=0;y<pixel_height;++y) for (int x=0;x<pixel_width;++x) {
            const auto* p=data+y*stride+x*4;
            auto* out=result.data()+(y*pixel_width+x)*4;
			// Cairo stores premultiplied BGRA; the overlay consumes straight RGBA.
			const unsigned alpha=p[3];
			for (int channel=0;channel<3;++channel)
				out[channel]=alpha?static_cast<unsigned char>((unsigned(p[2-channel])*255+alpha/2)/alpha):0;
			out[3]=p[3];
        }
        cairo_destroy(c); cairo_surface_destroy(surface);
        return result;
    }
private:
	static void rounded(cairo_t* c,double x,double y,double w,double h,double radius) {
		constexpr double pi=3.14159265358979323846;
		cairo_new_sub_path(c);
		cairo_arc(c,x+w-radius,y+radius,radius,-pi/2,0);
		cairo_arc(c,x+w-radius,y+h-radius,radius,0,pi/2);
		cairo_arc(c,x+radius,y+h-radius,radius,pi/2,pi);
		cairo_arc(c,x+radius,y+radius,radius,pi,3*pi/2);
		cairo_close_path(c);
	}
    void row(const std::string& normal,const std::string& upper,double x,double y) {
        for (size_t i=0;i<normal.size();++i) keys.push_back({x+i*84,y,76,72,normal.substr(i,1),upper.substr(i,1)});
    }
};
