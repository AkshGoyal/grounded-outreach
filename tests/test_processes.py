"""Worker recovery must observe processes without terminating them."""

import subprocess
import sys

from outreach.web.processes import process_alive


def test_liveness_check_leaves_running_worker_alive_and_detects_its_exit():
    worker = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        assert process_alive(worker.pid)
        assert process_alive(worker.pid)
        assert worker.poll() is None
    finally:
        worker.terminate()
        worker.wait(timeout=10)
    assert not process_alive(worker.pid)


def test_invalid_pid_is_not_alive():
    assert not process_alive(0)
    assert not process_alive(-1)
