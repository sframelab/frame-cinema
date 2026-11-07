#pragma once
namespace cinema_stereo {
// Only depth estimation is reduced. The eye images retain the source size.
#ifndef FRAME_CINEMA_DEPTH_WIDTH
#define FRAME_CINEMA_DEPTH_WIDTH 384
#define FRAME_CINEMA_DEPTH_HEIGHT 224
#endif
constexpr int model_width=FRAME_CINEMA_DEPTH_WIDTH;
constexpr int model_height=FRAME_CINEMA_DEPTH_HEIGHT;
}
