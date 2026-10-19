"""Disposable isolated work-capture integration harness."""
from pathlib import Path
import time

from sensors.filesystem_watcher import FilesystemWatcher
from sensors.terminal_receiver import start_terminal_receiver

root = Path(__file__).parent.resolve()
project_root = root / "project"
database_path = root / "capture.db"

watcher = FilesystemWatcher([project_root], database_path=database_path)
start_terminal_receiver(database_path=database_path)
watcher.start()
print("READY", flush=True)

try:
    while True:
        time.sleep(1)
finally:
    watcher.stop()
