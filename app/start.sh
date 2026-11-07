#!/bin/sh
set -eu
cd "$(dirname "$0")"
export FRAME_CINEMA_NATIVE_PREVIEW=1 FRAME_CINEMA_NATIVE_SCROLL=1
export FRAME_CINEMA_SYSTEM_POINTER=1 FRAME_CINEMA_SCENE_OWNER=1 FRAME_CINEMA_UNIFIED_UI=1
export FRAME_CINEMA_STEREO=1 FRAME_CINEMA_STEREO_MODEL="$PWD/stereo/model"
# Let CPU helpers sleep during Vulkan inference instead of spinning beside XR.
export OMP_WAIT_POLICY=PASSIVE
export FRAME_CINEMA_IPC="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/frame-cinema"
export FRAME_CINEMA_PREVIEW_GODOT_DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
export LD_LIBRARY_PATH="/opt/steamvr/bin/linuxarm64${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export XR_RUNTIME_JSON=/opt/steamvr/steamxr_linuxarm64.json
# Foveation (More > Foveation, applied at launch; the scene writes the mode).
# Steam adds Valve's FDM injection layers to this process. Exactly one owner:
#   godot   - Godot's own density map, steered by XR_EXT_eye_gaze_interaction.
#             No XR_FB_foveation swapchain: with that flag SteamVR's compositor
#             treated our frames as foveated and the periphery warped (0.4.45,
#             0.4.47, 0.4.51). Valve's injection layers stay out of the process.
#   steamvr - Valve's injection layer foveates (eye-tracked); Godot stays off.
# The Godot settings are written here, before the engine reads them.
cinema_data="$FRAME_CINEMA_PREVIEW_GODOT_DATA/FrameCinema"
foveation="$(head -c 16 "$cinema_data/foveation-launch" 2>/dev/null | tr -cd 'a-z' || true)"
gaze=false
case "$foveation" in
godot)
  gaze=true
  export DISABLE_VULKAN_FDM_INJECTION_LAYER=1
  VK_INSTANCE_LAYERS="$(printf '%s' "${VK_INSTANCE_LAYERS:-}" | sed -e 's/VK_LAYER_VALVE_fdm_injection//g' -e 's/::*/:/g' -e 's/^://' -e 's/:$//')"
  export VK_INSTANCE_LAYERS
  ;;
steamvr)
  export FDM_DEBUG=enable,med
  ;;
esac
if [ -d "$cinema_data" ]; then
  printf '[xr]\n\nopenxr/foveation_level=0\nopenxr/foveation_eye_tracked=false\nopenxr/extensions/eye_gaze_interaction=%s\n' "$gaze" > "$cinema_data/xr-foveation.cfg" || true
fi
exec python3 supervisor.py "$@"
