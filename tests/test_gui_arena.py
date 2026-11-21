import tkinter as tk
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src import i18n
from src.arena_bot import ArenaBot
from src.gui import SessionView


class ArenaSessionTests(unittest.TestCase):
    def setUp(self):
        i18n.set_language('ko', persist=False)
        self.view = view = object.__new__(SessionView)
        view.name = 'arena test'
        view.current_mode = 'arena'
        view.is_running = True
        view.was_stopped_by_user = False
        view.bot_thread = None
        view.adb_controller = object()
        view.runtime_dir = 'test_runtime'
        view.debug_mode_var = Mock(get=Mock(return_value=False))
        view.bot = SimpleNamespace(
            is_paused=False, stats={'completed_runs': 2},
            pause=Mock(), resume=Mock(), stop=Mock(), run=Mock())
        view.app = SimpleNamespace(is_closing=False)
        view.root = Mock()
        view.log = Mock()
        view._arena_status_raw = '진행 중'
        view._last_arena_stats = {'completed_runs': 2}
        for name in ('arena_start_btn', 'arena_stop_btn', 'arena_pause_btn',
                     'arena_resume_btn', 'arena_status_label', 'pause_label',
                     'pause_btn', 'resume_btn'):
            setattr(view, name, Mock())
        view._set_running_ui = Mock()
        view._play_complete_sound = Mock()
        view._play_stopped_sound = Mock()
        view._save_failure_report = Mock()

    def test_stop_retains_lock_and_blocks_other_modes_until_worker_finishes(self):
        view = self.view
        view._stop_bot()
        self.assertTrue(view.is_running)
        view.bot.stop.assert_called_once()
        view.arena_start_btn.config.assert_called_with(state=tk.DISABLED)
        view.arena_stop_btn.config.assert_called_with(state=tk.DISABLED)
        view.arena_pause_btn.config.assert_called_with(state=tk.DISABLED)
        view.arena_resume_btn.config.assert_called_with(state=tk.DISABLED)
        with patch('src.gui.ArenaBot') as arena, patch('src.gui.PenguinBot') as penguin:
            view._start_arena_bot()
            view._start_penguin_bot()
            view._start_bot()
            arena.assert_not_called()
            penguin.assert_not_called()
        view._set_running_ui.assert_not_called()

    def test_pause_resume_and_close_use_arena_api(self):
        view = self.view
        view._pause_bot()
        view.bot.pause.assert_called_once()
        view.bot.is_paused = True
        view._update_arena_controls()
        view.arena_pause_btn.config.assert_called_with(state=tk.DISABLED)
        view.arena_resume_btn.config.assert_called_with(state=tk.NORMAL)
        view._resume_bot()
        view.bot.resume.assert_called_once()
        view.request_stop_for_close()
        view.bot.stop.assert_called_once()

    def test_stopping_cannot_be_resumed(self):
        self.view._stop_bot()
        self.view._pause_bot()
        self.view._resume_bot()
        self.view.bot.pause.assert_not_called()
        self.view.bot.resume.assert_not_called()

    def test_stats_refresh_uses_arena_stats_without_shop_api(self):
        view = self.view
        view._update_running_state()
        self.assertEqual(view._last_arena_stats, {'completed_runs': 2})
        self.assertIn('완료 2회', view.arena_status_label.config.call_args.kwargs['text'])
        view.root.after.assert_called_once_with(500, view._update_running_state)

    def test_start_passes_existing_controller_and_locks_session(self):
        view = self.view
        view.is_running = False
        with patch('src.gui.ArenaBot', return_value=view.bot) as factory, \
                patch('src.gui.threading.Thread') as thread:
            view._start_arena_bot()
        factory.assert_called_once_with(view.adb_controller, debug_mode=False, runtime_dir='test_runtime')
        thread.return_value.start.assert_called_once()
        self.assertTrue(view.is_running)
        self.assertEqual(view.current_mode, 'arena')
        view._set_running_ui.assert_called_once_with(True)

    def test_start_rejects_unfinished_worker_and_disconnected_device(self):
        view = self.view
        view.is_running = False
        view.bot_thread = Mock(is_alive=Mock(return_value=True))
        with patch('src.gui.ArenaBot') as factory, patch('src.gui.messagebox.showerror') as error:
            view._start_arena_bot()
            factory.assert_not_called()
            error.assert_not_called()
            view.bot_thread = None
            view.adb_controller = None
            view._start_arena_bot()
            factory.assert_not_called()
            error.assert_called_once()

    def test_thread_start_error_restores_controls(self):
        view = self.view
        view.is_running = False
        with patch('src.gui.ArenaBot', return_value=view.bot), \
                patch('src.gui.threading.Thread') as thread, \
                patch('src.gui.messagebox.showerror'):
            thread.return_value.start.side_effect = RuntimeError('thread unavailable')
            view._start_arena_bot()
        self.assertFalse(view.is_running)
        view._set_running_ui.assert_called_with(False)
        self.assertEqual(view._arena_status_raw, '실행 실패')

    def test_worker_exception_reports_failure_and_restores_controls(self):
        view = self.view
        view.bot.run.side_effect = RuntimeError('test failure')
        with patch('src.gui.logger.exception'):
            view._run_arena_bot()
        view._save_failure_report.assert_called_once_with(
            {'status': 'failed', 'reason': 'test failure', 'completed_runs': 2})
        delay, finish = view.root.after.call_args.args
        self.assertEqual(delay, 0)
        finish()
        self.assertFalse(view.is_running)
        view._set_running_ui.assert_called_once_with(False)
        view._play_complete_sound.assert_not_called()
        view._play_stopped_sound.assert_called_once()

    def test_completion_sound_only_for_success(self):
        self.view._finish_arena_run({'status': 'completed', 'completed_runs': 4})
        self.assertFalse(self.view.is_running)
        self.view._play_complete_sound.assert_called_once()
        self.view._play_stopped_sound.assert_not_called()

    def test_completed_arena_session_can_be_closed_after_mode_is_cleared(self):
        view = self.view
        view.bot = ArenaBot(view.adb_controller, observer=object())
        view._set_running_ui.side_effect = lambda running: setattr(view, 'current_mode', None)
        view._finish_arena_run({'status': 'completed', 'completed_runs': 4})
        self.assertIsNone(view.current_mode)
        view.request_stop_for_close()
        self.assertTrue(view.bot._stop.is_set())
        self.assertFalse(view.is_running)

    def test_start_button_tracks_connection_and_other_running_modes(self):
        view = self.view
        view.is_running = False
        view._update_arena_controls()
        view.arena_start_btn.config.assert_called_with(state=tk.NORMAL)
        view.adb_controller = None
        view._update_arena_controls()
        view.arena_start_btn.config.assert_called_with(state=tk.DISABLED)
        view.adb_controller = object()
        view.is_running = True
        view.current_mode = 'shop'
        view._update_arena_controls()
        view.arena_start_btn.config.assert_called_with(state=tk.DISABLED)
        view.arena_stop_btn.config.assert_called_with(state=tk.DISABLED)


if __name__ == '__main__':
    unittest.main()
