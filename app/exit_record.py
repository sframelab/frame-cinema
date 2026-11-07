"""Bounded content-free shutdown diagnostics, never playback/account data."""
import json
from pathlib import Path
import re
import time

_VERSION = re.search(r'"version": "([^"]+)"', (Path(__file__).with_name('cinema.gd')).read_text(encoding='utf-8', errors='replace'))
VERSION = _VERSION.group(1) if _VERSION else 'unknown'

def event(runtime, session, scene_code, supervisor_stopped, panel_code):
    now = time.time()
    reason = 'supervisor_stop' if supervisor_stopped else ('scene_failure' if scene_code else 'scene_exit')
    try:
        value = json.loads((runtime / 'exit-reason.json').read_text(encoding='utf-8'))
        if (not supervisor_stopped and scene_code == 0 and value.get('session') == session
                and 0 <= now - value.get('updated', 0) < 10
                and value.get('reason') in ('xr_runtime_exit', 'xr_session_loss', 'escape_key')):
            reason = value['reason']
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return {'version': VERSION, 'updated': now, 'reason': reason,
            'scene_exit_code': scene_code, 'last_panel_exit_code': panel_code}
