// The hover highlight lies exactly on its key: own size, own corners (0.5.16). A press survives aim drift (0.5.17).
// Build: g++ -std=c++17 -I. test_keyboard_highlight.cpp $(pkg-config --cflags cairo) -o test_keyboard_highlight
#include "cinema_keyboard.h"
#include <cstdio>
#include <cstdlib>

static int failures = 0;
static void check(bool ok, const char* what) {
    std::printf("%s %s\n", ok ? "PASS" : "FAIL", what);
    if (!ok) ++failures;
}

static int alpha(const std::vector<unsigned char>& pixels, int width, int x, int y) {
    return pixels[(size_t(y) * width + x) * 4 + 3];
}

int main() {
    CinemaKeyboard keyboard;
    const int scale = CinemaKeyboard::texture_scale;
    const CinemaKeyboard::Key* letter = nullptr; const CinemaKeyboard::Key* space = nullptr;
    const CinemaKeyboard::Key* enter = nullptr; const CinemaKeyboard::Key* done = nullptr;
    for (const auto& k : keyboard.keys) {
        if (k.normal == "q") letter = &k;
        if (k.normal == "Space") space = &k;
        if (k.normal == "Enter") enter = &k;
        if (k.action == CinemaKeyboard::Hide) done = &k;
    }
    if (!letter || !space || !enter || !done) { std::puts("FAIL keys missing"); return 1; }

    bool sizes = true, centres = true, corners = true, colour = true;
    for (const auto& k : keyboard.keys) {
        const auto pixels = CinemaKeyboard::highlight_pixels(k, scale);
        const int w = int(k.w * scale), h = int(k.h * scale);
        sizes = sizes && pixels.size() == size_t(w) * h * 4;
        centres = centres && alpha(pixels, w, w / 2, h / 2) == 255;
        corners = corners && alpha(pixels, w, 0, 0) == 0 && alpha(pixels, w, w - 1, h - 1) == 0;
        for (size_t i = 0; i < pixels.size(); i += 4) colour = colour && pixels[i] == 255 && pixels[i + 1] == 255 && pixels[i + 2] == 255;
    }
    check(sizes, "every highlight is its key's own size at the keyboard's texture scale");
    check(centres, "every highlight is solid in the middle");
    check(corners, "every highlight is clear at its outer corners");
    check(colour, "the highlight is white; only alpha carries the shape");

    // The bug: a square texture stretched to 760x82 made the space bar's corners ovals.
    // Now the corner region of the space bar, Return and a letter key is the same picture.
    const auto a = CinemaKeyboard::highlight_pixels(*letter, scale);
    const auto b = CinemaKeyboard::highlight_pixels(*space, scale);
    const auto c = CinemaKeyboard::highlight_pixels(*enter, scale);
    const int aw = int(letter->w * scale), bw = int(space->w * scale), cw = int(enter->w * scale);
    bool same = true;
    for (int y = 0; y < 30 * scale; ++y) for (int x = 0; x < 30 * scale; ++x)
        same = same && alpha(a, aw, x, y) == alpha(b, bw, x, y) && alpha(a, aw, x, y) == alpha(c, cw, x, y);
    check(same, "Space, Return and the letter keys share one corner shape");

    // The edge of the highlight is the key's 18-unit arc: half covered where the arc meets the diagonal.
    const double r = CinemaKeyboard::corner_radius(*space), d = r * (1 - 1 / std::sqrt(2.0));
    const int px = int(std::lround(d * scale - .5));
    const int edge = alpha(b, bw, px, px);
    check(edge > 64 && edge < 192, "the corner's edge sits on the key's own 18-unit arc");
    // Straight along the top edge of the long key: clear above the key, solid just inside it.
    check(alpha(b, bw, bw / 2, 0) >= 128 && alpha(b, bw, bw / 2, 2) == 255, "the space bar's long top edge is straight and sharp");

    // Done is a pill: its corner radius is half its height.
    check(CinemaKeyboard::corner_radius(*done) == done->h / 2 && CinemaKeyboard::corner_radius(*space) == 18, "Done keeps its pill shape, the other keys 18 units");
    const auto p = CinemaKeyboard::highlight_pixels(*done, scale);
    const int pw = int(done->w * scale), ph = int(done->h * scale);
    check(alpha(p, pw, 0, ph / 2) >= 64 && alpha(p, pw, int(done->h * scale * .05), int(done->h * scale * .05)) == 0, "Done's highlight is rounded end to end");

    // A press survives the ray drifting while the trigger is pulled (0.5.17). Before, a release anywhere but on
    // the pressed key typed nothing: over the gap next to a letter, or over its neighbour.
    {
        CinemaKeyboard k;
        int g = -1, h = -1;
        for (size_t i = 0; i < k.keys.size(); ++i) { if (k.keys[i].normal == "g") g = int(i); if (k.keys[i].normal == "h") h = int(i); }
        const auto& kg = k.keys[g];
        const float gu = float((kg.x + kg.w / 2) / CinemaKeyboard::width), gv = float((kg.y + kg.h / 2) / CinemaKeyboard::height);
        const float gap_u = float((kg.x + kg.w + 4) / CinemaKeyboard::width);  // between g and h
        const auto& kh = k.keys[h];
        const float hu = float((kh.x + kh.w / 2) / CinemaKeyboard::width);
        bool hide = false;
        check(k.hit(gap_u, gv) == -1 && k.hit(hu, gv) == h && k.hit(gu, gv) == g, "the test points sit on g, on the gap after it and on h");
        k.pressed = k.hit(gu, gv);
        check(k.release(k.held(k.hit(gap_u, gv), true), hide) == "g", "a press on g released over the gap types g");
        k.pressed = k.hit(gu, gv);
        check(k.release(k.held(k.hit(hu, gv), true), hide) == "g", "a press on g released over h types g, not h and not nothing");
        k.pressed = k.hit(gu, gv);
        check(k.release(k.held(-1, false), hide).empty(), "a press dragged off the keyboard before release types nothing");
        k.pressed = -1;
        check(k.held(h, true) == h && k.held(-1, true) == -1, "with nothing pressed, the hover follows the ray");
    }

    std::printf("%s\n", failures ? "KEYBOARD_HIGHLIGHT_FAIL" : "KEYBOARD_HIGHLIGHT_OK");
    return failures ? 1 : 0;
}
