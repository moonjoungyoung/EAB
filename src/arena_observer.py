"""NPC arena recognition using icons, button borders and layout, never text."""
from pathlib import Path
import json
import sys

import cv2
import numpy as np

from .image_matcher import read_image


class ArenaObserver:
    ACTIONS = {
        'lobby': (1200, 389), 'arena_gate': (470, 666),
        'arena_list': (1110, 215), 'npc_list': (640, 223),
        'npc_selected': (640, 662), 'prepare_quick': (824, 662),
        'result': (745, 639), 'menu': (1241, 33),
        'other_screen': (36, 32),
        'screensaver': (950, 580),
        'warning': (854, 556),
    }

    def __init__(self, resource_root=None):
        root = Path(resource_root) if resource_root else (
            Path(sys._MEIPASS) if getattr(sys, 'frozen', False)
            else Path(__file__).resolve().parents[1])
        self.root = root / 'images/arena'
        self.layout = json.loads((self.root / 'layout.json').read_text(encoding='utf-8'))
        self.templates = {name: read_image(self.root / definition['file'])
                          for name, definition in self.layout.items()}
        if any(image is None for image in self.templates.values()):
            raise RuntimeError('아레나 인식 이미지가 누락되었습니다.')

    def has(self, frame, name, threshold=.88):
        """Small bounded searches keep memory independent of full screen size."""
        x, y, w, h = self.layout[name]['rect']
        left, top = max(0, x-3), max(0, y-3)
        roi = frame[top:min(720,y+h+3), left:min(1280,x+w+3)]
        template = self.templates[name]
        scores = cv2.matchTemplate(roi, template, cv2.TM_CCOEFF_NORMED)
        _, score, _, (dx, dy) = cv2.minMaxLoc(scores)
        if not np.isfinite(score) or score < threshold:
            return False
        found = roi[dy:dy+h, dx:dx+w]
        # A dimmed screen under a modal is not an actionable screen.
        error = np.abs(found.astype(np.float32) - template.astype(np.float32)).mean()
        return error < 24

    @staticmethod
    def _green_button(frame, box):
        x, y, w, h = box
        crop = frame[y:y+h, x:x+w].astype(np.int16)
        b,g,r = cv2.split(crop)
        return float(np.mean((g > r+12) & (g > b+9) & (g > 40))) > .6

    def observe(self, frame):
        if frame is None or frame.shape != (720,1280,3):
            raise RuntimeError('아레나 화면은 1280×720 캡처가 필요합니다.')
        has = lambda name: self.has(frame,name)
        if (has('warning_cancel_edge') and has('warning_confirm_edge') and
                has('warning_hide_edge') and has('warning_arena_icon')):
            return 'warning'
        if has('menu_close') and has('menu_book'):
            return 'menu'
        if (has('result_ornament') and has('result_medal') and
                has('result_gem') and self._green_button(frame,(660,615,65,43))):
            return 'result'
        if not has('grid'):
            if has('screensaver_left') and has('screensaver_right'):
                return 'screensaver'
            return None
        if has('sanctuary') and has('pass'):
            return 'lobby'
        if has('gate_left') and has('gate_right') and has('gate_star'):
            return 'arena_gate'
        if has('ranking') and has('record'):
            if has('npc_active'):
                if self._green_button(frame,(525,642,65,40)):
                    return 'npc_selected'
                return 'npc_list'
            return 'arena_list'
        if has('prepare') and has('npc_reward'):
            if has('quick_icon') and has('quick_edge'):
                return 'prepare_quick'
            # Positive normal-start button evidence is required. A loading
            # frame or an obscured button is never sufficient for exhaustion.
            if has('empty_icon') and has('empty_edge'):
                return 'prepare_empty'
            return None
        if has('back'):
            return 'other_screen'
        return None

    def action(self, state):
        return self.ACTIONS[state]
