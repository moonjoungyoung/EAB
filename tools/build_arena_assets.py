"""Extract language-independent UI symbols from local integration captures."""
from pathlib import Path
import json
import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'images/arena'
OUT.mkdir(parents=True, exist_ok=True)
# filename, reference capture, x/y/w/h. No words or counters in these crops.
MARKERS = {
    'empty_icon': (22, 935, 638, 42, 46),
    'empty_edge': (22, 675, 635, 15, 50),
    'warning_cancel_edge': (21, 325, 525, 34, 61),
    'warning_confirm_edge': (21, 540, 525, 34, 61),
    'warning_hide_edge': (21, 755, 525, 34, 61),
    'warning_arena_icon': (21, 936, 640, 34, 42),
    'screensaver_left': (1, 30, 134, 55, 76),
    'screensaver_right': (1, 1180, 163, 60, 85),
    'grid': (2, 1222, 14, 38, 38),
    'back': (3, 22, 13, 32, 39),
    'sanctuary': (2, 40, 144, 34, 36),
    'pass': (2, 37, 375, 43, 41),
    'gate_left': (3, 334, 557, 25, 85),
    'gate_right': (3, 918, 558, 26, 89),
    'gate_star': (3, 620, 641, 40, 61),
    'ranking': (14, 1030, 397, 31, 35),
    'record': (14, 1032, 298, 28, 33),
    'npc_active': (13, 1003, 174, 12, 80),
    'prepare': (8, 420, 532, 58, 48),
    'npc_reward': (8, 940, 547, 40, 40),
    'quick_icon': (8, 928, 634, 51, 57),
    'quick_edge': (8, 675, 635, 15, 50),
    'result_ornament': (10, 586, 240, 108, 45),
    'result_medal': (10, 578, 489, 42, 43),
    'result_gem': (10, 664, 489, 32, 46),
    'menu_close': (12, 1224, 16, 33, 33),
    'menu_book': (12, 1060, 117, 39, 44),
}
definition = {}
for name, (seq, x, y, w, h) in MARKERS.items():
    source = cv2.imdecode(np.fromfile(ROOT / 'arena_probe' / f'{seq}.png',np.uint8),cv2.IMREAD_COLOR)
    crop = source[y:y+h, x:x+w]
    ok, data = cv2.imencode('.png', crop)
    if not ok:
        raise RuntimeError(name)
    (OUT / f'{name}.png').write_bytes(data.tobytes())
    definition[name] = {'file': f'{name}.png', 'rect': [x,y,w,h]}
(OUT / 'layout.json').write_text(json.dumps(definition,indent=2)+'\n',encoding='utf-8')
