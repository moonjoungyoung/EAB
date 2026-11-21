import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from src.arena_bot import ArenaBot


STATES = [None, 'lobby', 'arena_gate', 'arena_list', 'npc_list', 'npc_selected',
          'prepare_quick', 'prepare_empty', 'warning', 'result', 'menu', 'other_screen', 'screensaver']


def frame(state):
    image = np.zeros((720, 1280, 3), dtype=np.uint8)
    image[0, 0, 0] = STATES.index(state)
    return image


class Observer:
    def observe(self, image):
        return STATES[int(image[0, 0, 0])]

    def action(self, state):
        if state == 'screensaver':
            return (950, 580)
        return (STATES.index(state), 100)


class Controller:
    def __init__(self, sequence):
        self.frames = [frame(state) for state in sequence]
        self.index = 0
        self.taps = []
        self.on_capture = None

    def capture_frame(self):
        image = self.frames[min(self.index, len(self.frames) - 1)]
        self.index += 1
        if self.on_capture:
            self.on_capture()
        return image

    def tap(self, x, y, delay=0):
        self.taps.append((x, y))
        return True


class Clock:
    def __init__(self):
        self.now = 0.0
        self.on_sleep = None

    def sleep(self, seconds):
        self.now += max(seconds, 0.001)
        if self.now > 600:
            raise RuntimeError('test_clock_limit')
        if self.on_sleep:
            self.on_sleep()


class ArenaBotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.clock = Clock()
        for target, value in [('src.arena_bot.time.monotonic', lambda: self.clock.now),
                              ('src.arena_bot.time.sleep', self.clock.sleep)]:
            patcher = patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def bot(self, sequence):
        controller = Controller(sequence)
        bot = ArenaBot(controller, observer=Observer(), runtime_dir=self.temp.name)
        return bot, controller

    def test_full_flow_counts_only_after_result_returns_to_npc_list(self):
        path = ['lobby', 'arena_gate', 'arena_list', 'npc_list', 'npc_selected',
                'prepare_quick', 'warning', 'result', 'npc_list']
        # Returning to the list consumes two frames for accounting, then fresh
        # stable frames plus the tap guard are required to select the next NPC.
        sequence = [state for state in path[:-1] for _ in range(3)]
        sequence += ['npc_list'] * 5 + ['npc_selected'] * 3 + ['prepare_empty'] * 30
        bot, controller = self.bot(sequence)
        result = bot.run()
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['reason_code'], 'quota_exhausted')
        self.assertEqual(result['completed_runs'], 1)
        self.assertEqual(controller.taps.count((STATES.index('prepare_quick'), 100)), 1)
        self.assertEqual(controller.taps.count((STATES.index('warning'), 100)), 1)
        self.assertFalse(bot.is_running)

    def test_quick_button_is_never_retried_when_result_times_out(self):
        bot, controller = self.bot(['prepare_quick'] * 3 + [None, 'prepare_quick'] * 150)
        result = bot.run()
        self.assertEqual(result['reason_code'], 'result_timeout')
        self.assertEqual(controller.taps, [(STATES.index('prepare_quick'), 100)])
        self.assertEqual(result['completed_runs'], 0)
        saved = json.loads((Path(self.temp.name) / 'failure.json').read_text(encoding='utf-8'))
        self.assertEqual(saved['reason_code'], 'result_timeout')
        self.assertTrue((Path(self.temp.name) / 'arena_failure.png').is_file())

    def test_empty_prepare_requires_five_continuous_seconds(self):
        bot, controller = self.bot(['prepare_empty'] * 12 + [None] + ['prepare_empty'] * 30)
        result = bot.run()
        self.assertEqual(result['reason_code'], 'quota_exhausted')
        self.assertGreaterEqual(self.clock.now, 8.0)
        self.assertEqual(controller.taps, [])

    def test_changed_frame_immediately_before_tap_is_not_clicked(self):
        bot, controller = self.bot(['prepare_quick'] * 2 + ['prepare_empty'] * 30)
        self.assertEqual(bot.run()['reason_code'], 'quota_exhausted')
        self.assertEqual(controller.taps, [])

    def test_unknown_start_never_clicks(self):
        bot, controller = self.bot([None])
        self.assertEqual(bot.run()['reason_code'], 'state_timeout')
        self.assertEqual(controller.taps, [])

    def test_recognized_screensaver_is_clicked_only_once(self):
        bot, controller = self.bot(['screensaver'])
        self.assertEqual(bot.run()['reason_code'], 'state_timeout')
        self.assertEqual(controller.taps, [(950, 580)])

    def test_gate_can_open_remembered_npc_tab_directly(self):
        bot, controller = self.bot(['arena_gate'] * 3 + ['npc_list'] * 3 +
                                   ['npc_selected'] * 3 + ['prepare_empty'] * 30)
        self.assertEqual(bot.run()['reason_code'], 'quota_exhausted')
        self.assertEqual(controller.taps, [(STATES.index(state), 100)
                                          for state in ('arena_gate', 'npc_list', 'npc_selected')])

    def test_unknown_after_known_screen_never_uses_unlock_tap(self):
        bot, controller = self.bot(['lobby'] * 3 + [None])
        self.assertEqual(bot.run()['reason_code'], 'state_timeout')
        self.assertNotIn((950, 580), controller.taps)

    def test_stop_before_run_prevents_all_capture_and_input(self):
        bot, controller = self.bot(['lobby'])
        bot.stop()
        self.assertEqual(bot.run()['status'], 'stopped')
        self.assertEqual(controller.index, 0)
        self.assertEqual(controller.taps, [])

    def test_shared_session_api_returns_snapshot_and_routes_actions(self):
        bot, _ = self.bot(['lobby'])
        stats = bot.get_stats()
        stats['completed_runs'] = 99
        self.assertEqual(bot.stats['completed_runs'], 0)
        bot.set_user_action('pause')
        self.assertTrue(bot._pause.is_set())
        bot.set_user_action('resume')
        self.assertFalse(bot._pause.is_set())
        bot.set_user_action('stop')
        self.assertTrue(bot._stop.is_set())

    def test_stop_during_pause_cancels_without_input(self):
        bot, controller = self.bot(['lobby'])
        bot.pause()
        self.clock.on_sleep = bot.stop
        self.assertEqual(bot.run()['status'], 'stopped')
        self.assertEqual(controller.taps, [])
        self.assertFalse(bot.is_paused)

    def test_pause_during_guard_invalidates_previous_screen(self):
        bot, controller = self.bot(['prepare_quick'])
        controller.on_capture = bot.pause
        self.clock.on_sleep = bot.resume
        self.assertFalse(bot._guarded_tap('prepare_quick'))
        self.assertEqual(controller.taps, [])

    def test_pause_time_is_excluded_from_state_timeout(self):
        bot, controller = self.bot(['prepare_empty'] * 40)
        def pause_once():
            controller.on_capture = None
            bot.pause()
        controller.on_capture = pause_once
        def resume_later():
            if self.clock.now >= 45:
                bot.resume()
        self.clock.on_sleep = resume_later
        self.assertEqual(bot.run()['reason_code'], 'quota_exhausted')
        self.assertGreater(self.clock.now, 50)

    def test_invalid_resolution_fails_without_input(self):
        bot, controller = self.bot(['lobby'])
        controller.frames = [np.zeros((1080, 1920, 3), dtype=np.uint8)]
        with patch('src.arena_bot.logger.exception'):
            result = bot.run()
        self.assertEqual(result['reason_code'], 'invalid_capture_size')
        self.assertEqual(controller.taps, [])

    def test_back_navigation_has_a_twelve_input_limit(self):
        bot, controller = self.bot(['other_screen'])
        self.assertEqual(bot.run()['reason_code'], 'home_navigation_limit')
        self.assertEqual(len(controller.taps), 12)

    def test_arena_animation_never_triggers_back_navigation(self):
        bot, controller = self.bot(['npc_selected'] * 3 + ['other_screen'] * 5 +
                                   ['prepare_empty'] * 30)
        self.assertEqual(bot.run()['reason_code'], 'quota_exhausted')
        self.assertEqual(controller.taps, [(STATES.index('npc_selected'), 100)])

    def test_menu_closes_then_back_returns_to_recognized_arena_flow(self):
        bot, controller = self.bot(['menu'] * 3 + ['other_screen'] * 3 + ['prepare_empty'] * 30)
        self.assertEqual(bot.run()['reason_code'], 'quota_exhausted')
        self.assertEqual(controller.taps, [(STATES.index('menu'), 100),
                                           (STATES.index('other_screen'), 100)])

    def test_run_limit_fails_before_another_selection(self):
        bot, controller = self.bot(['result'] * 3 + ['npc_list'] * 4)
        bot.stats['completed_runs'] = 29
        self.assertEqual(bot.run()['reason_code'], 'run_limit_reached')
        self.assertEqual(bot.stats['completed_runs'], 30)
        self.assertEqual(controller.taps, [(STATES.index('result'), 100)])

    def test_diagnostic_write_failure_keeps_original_result(self):
        bot, _ = self.bot([None])
        with patch('src.arena_bot.Path.mkdir', side_effect=OSError('unavailable')), \
                patch('src.arena_bot.logger.exception'):
            self.assertEqual(bot.run()['reason_code'], 'state_timeout')


if __name__ == '__main__':
    unittest.main()
