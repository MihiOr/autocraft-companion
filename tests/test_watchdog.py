import unittest
from creator_watchdog import CreatorWatchdog


class WatchdogTests(unittest.TestCase):
    def test_restart_only_after_observed_exit_and_no_launch_loop(self):
        w = CreatorWatchdog()
        self.assertFalse(w.poll(False, True, 0))
        self.assertFalse(w.poll(True, True, 2))
        self.assertFalse(w.poll(False, True, 4))
        self.assertTrue(w.poll(False, True, 6))
        self.assertFalse(w.poll(False, True, 200))

    def test_launch_cooldown_and_subsequent_crash(self):
        w = CreatorWatchdog()
        w.launched(0)
        self.assertFalse(w.poll(True, True, 2))
        self.assertFalse(w.poll(False, True, 4))
        self.assertFalse(w.poll(False, True, 6))
        self.assertTrue(w.poll(False, True, 60))
        self.assertFalse(w.poll(True, True, 70))
        self.assertFalse(w.poll(False, True, 130))
        self.assertTrue(w.poll(False, True, 132))

    def test_disabled_and_transient_absence(self):
        w = CreatorWatchdog()
        w.poll(True, True, 0)
        self.assertFalse(w.poll(False, True, 2))
        self.assertFalse(w.poll(True, True, 4))
        self.assertFalse(w.poll(False, False, 6))
        self.assertFalse(w.poll(False, True, 8))
