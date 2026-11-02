"""Own-process protection and failed-start cleanup without changing the database."""
from copy import deepcopy
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import application
import runtime


class ProcessOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.state = {"pid": 123, "python_executable": sys.executable,
                      "project_root": str(application.ROOT),
                      "script_path": str(application.SCRIPT), "creation_time": "456"}
        self.info = {"ExecutablePath": sys.executable, "CreationDate": "456"}

    def test_pid_reuse_is_rejected(self):
        self.info["CreationDate"] = "789"
        self.assertFalse(application.matches_own_process(self.state, self.info))

    def test_other_project_and_script_are_rejected(self):
        for key in ("project_root", "script_path", "python_executable"):
            state = deepcopy(self.state)
            state[key] += ".other"
            with self.subTest(key=key):
                self.assertFalse(application.matches_own_process(state, self.info))

    def test_registered_native_identity_matches(self):
        self.assertTrue(application.matches_own_process(self.state, self.info))
        self.assertFalse(application.matches_own_process(self.state, None))

    @unittest.skipUnless(os.name == "nt", "Windows native process handle check")
    def test_native_identity_and_exact_child_stop_without_cim(self):
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                                 creationflags=runtime.HIDDEN)
        try:
            info = application.process_details(child.pid)
            state = dict(self.state, pid=child.pid, creation_time=info["CreationDate"])
            self.assertTrue(application.is_own_process(state))
            self.assertTrue(application.terminate_own_process(state))
            child.wait(timeout=5)
            self.assertFalse(application.is_own_process(state))
        finally:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=5)

    def test_failed_readiness_stops_exact_child_and_clears_state(self):
        with tempfile.TemporaryDirectory(prefix=".runtime-test-", dir=ROOT / "tests") as directory:
            folder = Path(directory)
            (folder / "config.json").write_text("{}")
            state_file = folder / "server.json"
            with patch.object(application, "RUNTIME", folder), \
                 patch.object(runtime, "RUNTIME", folder), \
                 patch.object(application, "STATE", state_file), \
                 patch.object(application, "load_owner"), \
                 patch.object(application, "process_details", return_value=self.info), \
                 patch.object(application, "healthy", return_value=False), \
                 patch.object(application.time, "sleep"), \
                 patch("socket.socket"), \
                 patch.object(application.subprocess, "Popen") as popen:
                popen.return_value.poll.return_value = None
                popen.return_value.pid = 123
                with self.assertRaisesRegex(RuntimeError, "keine Bereitschaft"):
                    application.start()
                popen.return_value.terminate.assert_called_once()
                popen.return_value.wait.assert_called_once_with(timeout=10)
                self.assertFalse(state_file.exists())


class CopiedClusterProtectionTests(unittest.TestCase):
    def check_cluster(self, copied):
        with tempfile.TemporaryDirectory(prefix=".runtime-test-", dir=ROOT / "tests") as directory:
            folder = Path(directory)
            data = folder / "pgdata"
            data.mkdir()
            (data / "bookbridge_cluster_id").write_text("test-cluster-id\n", encoding="ascii")
            recorded_path = ROOT / "old-copy/pgdata" if copied else data
            (data / "postmaster.pid").write_text(f"123\n{recorded_path}\n", encoding="utf-8")
            with patch.object(runtime, "DATA", data), patch.object(runtime, "RUNTIME", folder):
                runtime.validate_cluster({"cluster_id": "test-cluster-id"})

    def test_pid_for_current_data_directory_is_allowed(self):
        self.check_cluster(copied=False)

    def test_copied_running_cluster_cannot_control_original_process(self):
        with self.assertRaisesRegex(RuntimeError, "anderen Datenordner"):
            self.check_cluster(copied=True)


if __name__ == "__main__":
    unittest.main()
