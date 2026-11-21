"""Recognition regression using real game captures and negative mutations."""
from pathlib import Path
import unittest
import numpy as np

from src.arena_observer import ArenaObserver
from src.image_matcher import read_image


FIXTURES = Path(__file__).parent / 'fixtures/arena'


class ArenaObserverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.observer = ArenaObserver()

    def test_actual_screens(self):
        expected = {1:'screensaver',2:'lobby',3:'arena_gate',4:'npc_list',
                    6:'npc_selected',8:'prepare_quick',9:None,10:'result',
                    12:'menu',14:'arena_list',21:'warning',22:'prepare_empty'}
        for sequence,state in expected.items():
            with self.subTest(sequence=sequence):
                self.assertEqual(self.observer.observe(read_image(FIXTURES/f'{sequence}.png')),state)

    def test_no_quick_icon_is_not_enough_to_report_exhaustion(self):
        frame=read_image(FIXTURES/'8.png')
        frame[625:705,670:990]=0
        self.assertIsNone(self.observer.observe(frame))

    def test_black_loading_frame_is_not_exhaustion(self):
        self.assertIsNone(self.observer.observe(np.zeros((720,1280,3),np.uint8)))

    def test_exhaustion_needs_regular_button_and_spent_quick_icon(self):
        original=read_image(FIXTURES/'22.png')
        self.assertEqual(self.observer.observe(original),'prepare_empty')
        for box in ((935,638,42,46),(675,635,15,50)):
            frame=original.copy()
            x,y,w,h=box
            frame[y:y+h,x:x+w]=0
            self.assertIsNone(self.observer.observe(frame))

    def test_modal_dimmed_background_cannot_trigger_click(self):
        for sequence in (2,3,4,6,8,10,14):
            with self.subTest(sequence=sequence):
                frame=read_image(FIXTURES/f'{sequence}.png')
                self.assertIsNone(self.observer.observe((frame*.4).astype(np.uint8)))

    def test_reject_wrong_resolution(self):
        with self.assertRaises(RuntimeError):
            self.observer.observe(np.zeros((1080,1920,3),np.uint8))

    def test_arena_tab_never_challenges_pvp_list(self):
        state=self.observer.observe(read_image(FIXTURES/'14.png'))
        self.assertEqual(state,'arena_list')
        self.assertEqual(self.observer.action(state),(1110,215))

    def test_warning_requires_all_three_buttons_and_arena_context(self):
        original=read_image(FIXTURES/'21.png')
        for box in ((325,525,34,61),(540,525,34,61),(755,525,34,61),(936,640,34,42)):
            frame=original.copy()
            x,y,w,h=box
            frame[y:y+h,x:x+w]=0
            self.assertNotEqual(self.observer.observe(frame),'warning')
        self.assertEqual(self.observer.action('warning'),(854,556))


if __name__=='__main__':
    unittest.main()
