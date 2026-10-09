"""Detect a running creator disappearing without repeated launch requests."""
import psutil


def creator_running():
    for process in psutil.process_iter(['name']):
        if (process.info['name'] or '').casefold() == 'autocraft.exe':
            return True
    return False


class CreatorWatchdog:
    def __init__(self):
        self.seen_running = False
        self.missing = 0
        self.next_launch = 0

    def launched(self, now):
        self.seen_running = False
        self.missing = 0
        self.next_launch = now + 60

    def poll(self, running, enabled, now):
        if not enabled:
            self.seen_running = False
            self.missing = 0
            return False
        if running:
            self.seen_running = True
            self.missing = 0
        elif self.seen_running:
            self.missing += 1
            if self.missing >= 2 and now >= self.next_launch:
                self.launched(now)
                return True
        return False
