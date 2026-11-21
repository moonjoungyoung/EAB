"""Guarded NPC arena flow. Screen recognition belongs to ArenaObserver."""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger(__name__)


class _Stopped(Exception):
    pass


class ArenaBot:
    STATE_TIMEOUT = 30.0
    EMPTY_STABLE_SECONDS = 5.0
    POLL_INTERVAL = 0.25
    MAX_RUNS = 30
    REASONS = {
        'quota_exhausted': '오늘 사용할 수 있는 NPC 빠른 대전을 모두 완료했습니다.',
        'user_stopped': '사용자 요청으로 중지했습니다.',
        'result_timeout': '빠른 대전 결과를 확인하지 못해 중지했습니다. 화면을 확인해 주세요.',
        'state_timeout': '다음 화면을 확인하지 못해 중지했습니다. 화면을 확인해 주세요.',
        'run_limit_reached': '안전을 위한 최대 30회 실행 한도에 도달했습니다.',
        'home_navigation_limit': '메인 로비로 돌아오지 못해 중지했습니다.',
        'unsupported_state': '지원하지 않는 화면이어서 중지했습니다.',
        'invalid_capture_size': '1280×720 게임 화면을 캡처하지 못했습니다.',
        'missing_action': '현재 화면에서 실행할 버튼을 확인하지 못했습니다.',
        'invalid_action_position': '버튼 위치가 화면 범위를 벗어나 중지했습니다.',
        'input_failed': '게임에 클릭을 전달하지 못했습니다.',
    }
    NEXT_STATES = {
        'screensaver': {'lobby'},
        'lobby': {'arena_gate'},
        'arena_gate': {'arena_list', 'npc_list'},
        'arena_list': {'npc_list'},
        'npc_list': {'npc_selected'},
        'npc_selected': {'prepare_quick', 'prepare_empty'},
        'prepare_quick': {'warning', 'result'},
        'warning': {'result'},
        'result': {'npc_list'},
        'menu': {'other_screen', 'lobby', 'arena_gate', 'arena_list', 'npc_list',
                 'npc_selected', 'prepare_quick', 'prepare_empty'},
        'other_screen': {'other_screen', 'menu', 'lobby', 'arena_gate', 'arena_list',
                         'npc_list', 'npc_selected', 'prepare_quick', 'prepare_empty'},
    }

    def __init__(self, adb_controller, debug_mode=False, runtime_dir=None, observer=None):
        if observer is None:
            from .arena_observer import ArenaObserver
            observer = ArenaObserver()
        self.adb = adb_controller
        self.observer = observer
        self.debug_mode = debug_mode
        self.runtime_dir = Path(runtime_dir) if runtime_dir else Path.cwd() / 'logs' / 'arena'
        self.last_screen = None
        self.is_running = False
        self.is_paused = False
        self.stats = {'completed_runs': 0, 'start_time': None, 'end_time': None}
        self._stop = threading.Event()
        self._pause = threading.Event()
        self._pause_seconds = 0.0
        self._generation = 0
        self._phase = 'starting'

    def stop(self):
        self._stop.set()

    def pause(self):
        self._pause.set()

    def resume(self):
        self._pause.clear()

    def set_user_action(self, action):
        """Keep shared session shutdown compatible after its mode is cleared."""
        handlers = {'stop': self.stop, 'pause': self.pause, 'resume': self.resume}
        handler = handlers.get(action)
        if handler is not None:
            handler()

    def get_stats(self):
        return dict(self.stats)

    def _now(self):
        return time.monotonic() - self._pause_seconds

    def _checkpoint(self):
        if self._stop.is_set():
            raise _Stopped()
        if self._pause.is_set():
            started = time.monotonic()
            self.is_paused = True
            self._generation += 1
            try:
                while self._pause.is_set():
                    if self._stop.is_set():
                        raise _Stopped()
                    time.sleep(0.05)
            finally:
                self._pause_seconds += time.monotonic() - started
                self.is_paused = False
        if self._stop.is_set():
            raise _Stopped()

    def _sleep(self, seconds):
        deadline = self._now() + seconds
        while self._now() < deadline:
            self._checkpoint()
            time.sleep(min(0.05, max(0.0, deadline - self._now())))
        self._checkpoint()

    def _capture(self):
        self._checkpoint()
        frame = self.adb.capture_frame()
        self._checkpoint()
        if not isinstance(frame, np.ndarray) or frame.shape != (720, 1280, 3):
            raise RuntimeError('invalid_capture_size')
        self.last_screen = frame
        return frame

    def _guarded_tap(self, state, position=None):
        if state is None:
            return False
        generation = self._generation
        frame = self._capture()
        if self._generation != generation or self.observer.observe(frame) != state:
            return False
        position = position if position is not None else self.observer.action(state)
        if not position or len(position) != 2:
            raise RuntimeError('missing_action')
        x, y = map(int, position)
        if not (0 <= x < 1280 and 0 <= y < 720):
            raise RuntimeError('invalid_action_position')
        self._checkpoint()
        if self._generation != generation:
            return False
        if self.adb.tap(x, y, delay=0) is False:
            raise RuntimeError('input_failed')
        logger.info('NPC 아레나 입력: %s (%s, %s)', state, x, y)
        return True

    def run(self):
        if self.is_running:
            raise RuntimeError('arena_already_running')
        self.is_running = True
        self.stats['start_time'] = time.time()
        try:
            result = self._run()
        except _Stopped:
            result = self._result('stopped', 'user_stopped')
        except Exception as exc:
            logger.exception('NPC 아레나 실행 실패')
            result = self._result('failed', str(exc))
        finally:
            self.is_running = False
            self.is_paused = False
            self.stats['end_time'] = time.time()
        if result['status'] == 'failed':
            self._save_diagnostics(result)
        return result

    def _run(self):
        deadline = self._now() + self.STATE_TIMEOUT
        last_observed = None
        stable_count = 0
        generation = self._generation
        empty_since = None
        last_action = None
        quick_pending = False
        result_seen = False
        back_count = 0
        home_navigation = True

        while True:
            self._checkpoint()
            frame = self._capture()
            state = self.observer.observe(frame)
            if state is not None and state not in {'menu', 'other_screen', 'screensaver'}:
                home_navigation = False
            if self._generation != generation:
                generation = self._generation
                stable_count = 0
                empty_since = None
            stable_count = stable_count + 1 if state == last_observed else 1
            last_observed = state
            if state != 'prepare_empty':
                empty_since = None
            if self._now() >= deadline:
                return self._result('failed', 'result_timeout' if quick_pending else 'state_timeout')

            if state is None:
                self._sleep(self.POLL_INTERVAL)
                continue
            if stable_count < 2:
                self._sleep(self.POLL_INTERVAL)
                continue

            if self._phase != state:
                logger.info('NPC 아레나 화면: %s', state)
            self._phase = state
            if result_seen and state == 'npc_list':
                self.stats['completed_runs'] += 1
                logger.info('NPC 아레나 완료: %s회', self.stats['completed_runs'])
                if self.stats['completed_runs'] >= self.MAX_RUNS:
                    return self._result('failed', 'run_limit_reached')
                quick_pending = False
                result_seen = False
                last_action = None
                deadline = self._now() + self.STATE_TIMEOUT
                stable_count = 0
                self._sleep(1.0)
                continue

            # A quick battle is never submitted again after its first tap.
            if quick_pending and state not in {'warning', 'result'}:
                self._sleep(self.POLL_INTERVAL)
                continue
            if state in {'other_screen', 'menu'} and not home_navigation:
                self._sleep(self.POLL_INTERVAL)
                continue
            if last_action is not None:
                if ((state == last_action and state != 'other_screen') or
                        state not in self.NEXT_STATES[last_action]):
                    self._sleep(self.POLL_INTERVAL)
                    continue

            if state == 'prepare_empty':
                if empty_since is None:
                    empty_since = self._now()
                if self._now() - empty_since >= self.EMPTY_STABLE_SECONDS:
                    return self._result('completed', 'quota_exhausted')
                self._sleep(self.POLL_INTERVAL)
                continue
            if state not in self.NEXT_STATES:
                return self._result('failed', 'unsupported_state')
            if state == 'other_screen' and back_count >= 12:
                return self._result('failed', 'home_navigation_limit')
            if state == 'result':
                result_seen = True
            if self._guarded_tap(state):
                if state == 'other_screen':
                    back_count += 1
                last_action = state
                quick_pending = quick_pending or state == 'prepare_quick'
                deadline = self._now() + self.STATE_TIMEOUT
                stable_count = 0
                if state in {'other_screen', 'menu'}:
                    self._sleep(0.75)
            else:
                stable_count = 0
            self._sleep(self.POLL_INTERVAL)

    def _result(self, status, reason):
        return {'status': status, 'reason': self.REASONS.get(reason, reason), 'reason_code': reason,
                'completed_runs': self.stats['completed_runs'], 'phase': self._phase}

    def _save_diagnostics(self, result):
        try:
            self.runtime_dir.mkdir(parents=True, exist_ok=True)
            (self.runtime_dir / 'failure.json').write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
            if self.last_screen is not None:
                ok, encoded = cv2.imencode('.png', self.last_screen)
                if ok:
                    (self.runtime_dir / 'arena_failure.png').write_bytes(encoded.tobytes())
        except Exception:
            logger.exception('NPC 아레나 진단 저장 실패')
