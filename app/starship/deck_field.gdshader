shader_type spatial;

// Observation Deck floor while Cinema's ambient glow is on: the base mirror lookup plus
// the movie's cached ambient field reflected at the screen plane and the movie light.
#define FIELD
#include "deck_common.gdshaderinc"
