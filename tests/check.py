#!/usr/bin/env python3
"""Exercise the shell application on a private D-Bus, without a desktop session."""

import json
from contextlib import closing
import os
from pathlib import Path
import fcntl
import pty
import select
import signal
import shutil
import sqlite3
import struct
import subprocess
import sys
import tempfile
import termios
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = Path(os.environ.get(
    "NOTIFICATION_HISTORY_SCRIPT",
    ROOT / "src/notification-history",
))


class NotificationHistory(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="notification history 'test ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = dict(os.environ, XDG_DATA_HOME=str(self.root / "data"))
        self.database = self.root / "data/notification-history/history.sqlite3"
        self.mocks = self.root / "bin"
        self.mocks.mkdir()
        temporary = self.root / "temporary files"
        temporary.mkdir()
        self.env.update(
            PATH=f"{self.mocks}:{self.env['PATH']}",
            MOCK_LOG=str(self.root / "commands.jsonl"),
            MOCK_COPY=str(self.root / "clipboard"),
            FZF_POPUP_LAUNCHER=str(self.mocks / "launcher"),
            REAL_FZF=os.environ.get("REAL_FZF", shutil.which("fzf") or "fzf"),
            REAL_NVIM=os.environ.get("REAL_NVIM", shutil.which("nvim") or "nvim"),
            MOCK_VIEW=str(self.root / "view.json"),
            MOCK_NVIM_STATE=str(self.root / "nvim-state"),
            TMPDIR=str(temporary),
        )
        mock = f"#!{sys.executable}\n" + '''
import json, os, pathlib, subprocess, sys
name = pathlib.Path(sys.argv[0]).name
with open(os.environ['MOCK_LOG'], 'a') as log:
    log.write(json.dumps([name, *sys.argv[1:]]) + '\\n')
if name == 'wl-copy':
    pathlib.Path(os.environ['MOCK_COPY']).write_bytes(sys.stdin.buffer.read())
elif name == 'fzf':
    if os.environ.get('MOCK_USE_REAL_FZF'):
        with open('/dev/tty') as tty:
            pathlib.Path(os.environ['MOCK_VIEW'] + '.tty').write_text(str(os.fstat(tty.fileno()).st_rdev))
        os.execv(os.environ['REAL_FZF'], [os.environ['REAL_FZF'], *sys.argv[1:]])
    lines = sys.stdin.read().splitlines()
    pathlib.Path(os.environ['MOCK_LOG'] + '.list').write_text('\\n'.join(lines))
    status = int(os.environ.get('MOCK_FZF_EXIT', '0'))
    if status: sys.exit(status)
    if lines: print(lines[0])
elif name == 'launcher':
    sys.exit(subprocess.call(sys.argv[1:]))
elif name == 'nvim':
    file = pathlib.Path(sys.argv[-1])
    pathlib.Path(os.environ['MOCK_VIEW']).write_text(json.dumps({
        'path': str(file), 'content': file.read_text(),
        'mode': file.stat().st_mode & 0o777,
        'tty': [os.fstat(fd).st_rdev if os.isatty(fd) else None for fd in (0, 1, 2)],
    }))
    if os.environ.get('MOCK_USE_REAL_NVIM'):
        os.execv(os.environ['REAL_NVIM'], [os.environ['REAL_NVIM'], '-u', 'NONE',
            '--cmd', 'autocmd VimEnter * call writefile([string(&readonly), string(&modeline)], $MOCK_NVIM_STATE)',
            *sys.argv[1:]])
    sys.exit(int(os.environ.get('MOCK_NVIM_EXIT', '0')))
'''
        for name in ("wl-copy", "fzf", "launcher", "nvim"):
            path = self.mocks / name
            path.write_text(mock)
            path.chmod(0o755)
        self.listener = None
        self.addCleanup(self.stop_listener)
        self.start_listener()

    def run_app(self, *args, check=True, **kwargs):
        return subprocess.run(
            ["bash", str(SCRIPT), *args], env=self.env,
            capture_output=True, check=check, **kwargs,
        )

    def start_listener(self):
        self.listener = subprocess.Popen(
            ["bash", str(SCRIPT), "listen"], env=self.env,
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            start_new_session=True,
        )
        # A sentinel request proves monitoring is ready, rather than assuming a delay.
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if self.listener.poll() is not None:
                self.fail(self.listener.stderr.read().decode())
            self.send("ready", "", app="test-readiness")
            if self.database.exists():
                try:
                    with closing(sqlite3.connect(self.database)) as db:
                        ready = db.execute(
                            "SELECT count(*) FROM notifications WHERE app_name='test-readiness'"
                        ).fetchone()[0]
                        if ready:
                            break
                except sqlite3.OperationalError:
                    pass
            time.sleep(0.05)
        else:
            self.fail("listener never became ready")
        # Drain all outstanding readiness probes using an ordered final marker.
        self.send("barrier", "", app="test-readiness-end")
        while time.monotonic() < deadline:
            with closing(sqlite3.connect(self.database)) as db:
                if db.execute("SELECT count(*) FROM notifications WHERE app_name='test-readiness-end'").fetchone()[0]:
                    db.execute("DELETE FROM notifications WHERE app_name IN ('test-readiness', 'test-readiness-end')")
                    db.commit()
                    return
            time.sleep(0.02)
        self.fail("listener did not process the readiness barrier")

    def stop_listener(self):
        if self.listener is not None:
            if self.listener.poll() is None:
                os.killpg(self.listener.pid, signal.SIGTERM)
            self.listener.wait(timeout=5)
            self.listener.stderr.close()
            self.listener = None

    def send(self, summary, body, app="test-app", replaces_id=0):
        # No real notification daemon or popup is needed to observe the request.
        subprocess.run([
            "busctl", "--user", "--expect-reply=no", "--auto-start=no", "call", "--",
            "org.freedesktop.Notifications", "/org/freedesktop/Notifications",
            "org.freedesktop.Notifications", "Notify", "susssasa{sv}i",
            app, str(replaces_id), "", summary, body, "0", "1", "urgency", "y", "1", "-1",
        ], env=self.env, check=True, capture_output=True)

    def rows(self, count):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            with closing(sqlite3.connect(self.database)) as db:
                rows = db.execute(
                    "SELECT id, app_name, summary, body FROM notifications ORDER BY id"
                ).fetchall()
            if len(rows) == count:
                return rows
            time.sleep(0.02)
        self.fail(f"expected {count} records, got {rows!r}")

    def test_unicode_multiline_and_sql_text_round_trip(self):
        summary = "中文 'quoted' \\ title\nsecond line"
        body = "Robert'); DROP TABLE notifications;--\n正文\tdata\n\n"
        self.send(summary, body)
        row = self.rows(1)[0]
        self.assertEqual(row[1:], ("test-app", summary, body))
        preview = self.run_app("preview", str(row[0])).stdout.decode()
        self.assertIn(summary, preview)
        self.assertTrue(preview.endswith(body))
        self.run_app("copy", str(row[0]))
        self.assertEqual((self.root / "clipboard").read_bytes(),
                         (summary + "\n" + body).encode())

    def test_persistence_and_updates_are_separate(self):
        self.send("first", "original")
        first = self.rows(1)[0]
        self.send("update", "updated", replaces_id=first[0])
        original = self.rows(2)
        self.stop_listener()
        self.start_listener()
        self.assertEqual(self.rows(2), original)
        self.send("third", "")
        self.assertEqual(self.rows(3)[-1][2], "third")

    def test_large_body(self):
        body = "long正文\n" * 10000
        self.send("Large notification", body)
        row = self.rows(1)[0]
        self.assertEqual(row[3], body)
        self.run_app("copy", str(row[0]))
        self.assertEqual((self.root / "clipboard").read_bytes(),
                         ("Large notification\n" + body).encode())

    def test_empty_body_and_missing_id_preserve_clipboard(self):
        self.send("Only a title", "")
        row = self.rows(1)[0]
        self.run_app("copy", str(row[0]))
        clipboard = self.root / "clipboard"
        self.assertEqual(clipboard.read_text(), "Only a title")
        for invalid in ("999999", "1; DROP TABLE notifications", "-1"):
            self.assertNotEqual(self.run_app("copy", invalid, check=False).returncode, 0)
            self.assertEqual(clipboard.read_text(), "Only a title")

    def test_control_characters_only_filtered_for_display(self):
        summary = "title\x1b[31m\x07"
        body = "body\x1b]52;c;data\x07\n\tend\u009b"
        self.send(summary, body)
        row = self.rows(1)[0]
        preview = self.run_app("preview", str(row[0])).stdout.decode()
        for control in ("\x1b", "\x07", "\u009b"):
            self.assertNotIn(control, preview)
        self.assertIn("\n\tend", preview)
        self.run_app("copy", str(row[0]))
        self.assertEqual((self.root / "clipboard").read_bytes(),
                         (summary + "\n" + body).encode())

    def test_floating_picker_order_and_cancel(self):
        self.send("older\nline", "old")
        self.rows(1)
        self.send("newer\tline", "new")
        newest = self.rows(2)[-1]
        self.run_app()  # Default command opens the floating terminal.
        self.assertFalse((self.root / "clipboard").exists())
        commands = [json.loads(line) for line in
                    (self.root / "commands.jsonl").read_text().splitlines()]
        self.assertEqual(commands[0][0], "launcher")
        fzf = next(command for command in commands if command[0] == "fzf")
        self.assertIn("--preview-window=right,60%,wrap", fzf)
        self.assertIn("preview {1}", next(arg for arg in fzf if arg.startswith("--preview=")))
        self.assertIn("view {1} </dev/tty >/dev/tty 2>&1",
                      next(arg for arg in fzf if arg.startswith("--bind=enter:become(")))
        self.assertIn("--header=Enter: view in Neovim · Esc: close", fzf)
        listing = (self.root / "commands.jsonl.list").read_text().splitlines()
        self.assertTrue(listing[0].startswith(str(newest[0]) + "\t"))
        self.assertEqual(len(listing), 2)
        clipboard = self.root / "clipboard"
        clipboard.write_bytes(b"existing clipboard")
        self.env["MOCK_FZF_EXIT"] = "130"
        self.run_app("browse")
        self.assertEqual(clipboard.read_bytes(), b"existing clipboard")
        self.env["MOCK_FZF_EXIT"] = "2"
        self.assertEqual(self.run_app("browse", check=False).returncode, 2)

    def test_empty_database(self):
        self.env["MOCK_FZF_EXIT"] = "130"
        self.run_app("browse")
        self.assertFalse((self.root / "clipboard").exists())
        commands = (self.root / "commands.jsonl").read_text()
        self.assertIn("No notifications saved yet", commands)
        self.stop_listener()
        self.env["XDG_DATA_HOME"] = str(self.root / "unused")
        self.run_app("browse")
        self.assertFalse((self.root / "unused").exists())

    def test_view_content_permissions_and_cleanup(self):
        clipboard = self.root / "clipboard"
        clipboard.write_bytes(b"existing clipboard")
        notifications = [("中文 'quoted' \\ title\nline", "正文\n\tend\n\n"),
                         ("Only a title", ""),
                         ("control\x1b[31m", "body\x07\u009b")]
        for count, (summary, body) in enumerate(notifications, 1):
            self.send(summary, body)
            row = self.rows(count)[-1]
            self.run_app("view", str(row[0]))
            view = json.loads((self.root / "view.json").read_text())
            self.assertEqual(view["content"], summary + ("\n" + body if body else ""))
            self.assertEqual(view["mode"], 0o600)
            self.assertFalse(Path(view["path"]).exists())
        commands = [json.loads(line) for line in
                    (self.root / "commands.jsonl").read_text().splitlines()]
        editors = [command for command in commands if command[0] == "nvim"]
        self.assertEqual(len(editors), len(notifications))
        for command in editors:
            self.assertEqual(command[1:-1], ["-R", "-n", "-i", "NONE", "--cmd", "set nomodeline", "--"])
        self.env["MOCK_NVIM_EXIT"] = "7"
        self.assertEqual(self.run_app("view", str(row[0]), check=False).returncode, 7)
        self.assertFalse(Path(json.loads((self.root / "view.json").read_text())["path"]).exists())
        self.assertEqual(clipboard.read_bytes(), b"existing clipboard")
        self.assertEqual(list(Path(self.env["TMPDIR"]).iterdir()), [])
        previous = (self.root / "commands.jsonl").read_bytes()
        for invalid in ("999999", "1; DROP TABLE notifications", "-1", "0", ""):
            self.assertNotEqual(self.run_app("view", invalid, check=False).returncode, 0)
        self.assertEqual((self.root / "commands.jsonl").read_bytes(), previous)
        self.assertEqual(list(Path(self.env["TMPDIR"]).iterdir()), [])

    def test_real_fzf_preview_and_enter(self):
        self.send("Interactive title", "PREVIEW-CONTENT-MARKER")
        self.rows(1)
        self.env.update(MOCK_USE_REAL_FZF="1", MOCK_USE_REAL_NVIM="1", TERM="xterm-256color",
                        FZF_DEFAULT_OPTS="")
        clipboard = self.root / "clipboard"
        clipboard.write_bytes(b"existing clipboard")
        pid, terminal = pty.fork()
        if pid == 0:
            os.execvpe("bash", ["bash", str(SCRIPT), "_picker"], self.env)
        output = bytearray()
        exited = False
        try:
            fcntl.ioctl(terminal, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 120, 0, 0))
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if select.select([terminal], [], [], 0.1)[0]:
                    chunk = os.read(terminal, 65536)
                    output.extend(chunk)
                    if b"\x1b[6n" in chunk:
                        os.write(terminal, b"\x1b[1;1R")
                    if b"PREVIEW-CONTENT-MARKER" in output:
                        break
            self.assertIn(b"PREVIEW-CONTENT-MARKER", output)
            os.write(terminal, b"\r")
            state = self.root / "nvim-state"
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if select.select([terminal], [], [], 0.05)[0]:
                    chunk = os.read(terminal, 65536)
                    output.extend(chunk)
                    if b"\x1b[6n" in chunk:
                        os.write(terminal, b"\x1b[1;1R")
                if state.exists():
                    break
            self.assertTrue(state.exists(), "Enter did not open Neovim")
            self.assertEqual(state.read_text().splitlines(), ["1", "0"])
            view = json.loads((self.root / "view.json").read_text())
            self.assertEqual(view["content"], "Interactive title\nPREVIEW-CONTENT-MARKER")
            self.assertEqual(view["mode"], 0o600)
            tty = int((self.root / "view.json.tty").read_text())
            self.assertEqual(view["tty"], [tty, tty, tty])
            self.assertTrue(Path(view["path"]).exists())
            self.assertEqual(os.waitpid(pid, os.WNOHANG)[0], 0)
            os.write(terminal, b"\x1b:q!\r")
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if select.select([terminal], [], [], 0.02)[0]:
                    try:
                        os.read(terminal, 65536)
                    except OSError:
                        pass
                child, status = os.waitpid(pid, os.WNOHANG)
                if child:
                    exited = True
                    self.assertEqual(os.waitstatus_to_exitcode(status), 0)
                    break
                time.sleep(0.02)
            self.assertTrue(exited, "menu did not close after quitting Neovim")
            self.assertFalse(Path(view["path"]).exists())
            self.assertEqual(clipboard.read_bytes(), b"existing clipboard")
            commands = [json.loads(line) for line in
                        (self.root / "commands.jsonl").read_text().splitlines()]
            self.assertEqual(sum(command[0] == "launcher" for command in commands), 1)
            # Neovim owns a separate nvim.<user> temporary directory. Only the
            # application's files and popup working directory must be gone.
            self.assertTrue(all(path.is_dir() and path.name.startswith("nvim.")
                                for path in Path(self.env["TMPDIR"]).iterdir()))
        finally:
            if not exited:
                os.killpg(pid, signal.SIGKILL)
                os.waitpid(pid, 0)
            os.close(terminal)

    def test_duplicate_listener_and_concurrent_write(self):
        duplicate = self.run_app("listen", check=False)
        self.assertNotEqual(duplicate.returncode, 0)
        self.assertIn(b"already running", duplicate.stderr)
        with closing(sqlite3.connect(self.database)) as db:
            self.assertEqual(db.execute("PRAGMA journal_mode").fetchone()[0], "wal")
            db.execute("BEGIN IMMEDIATE")
            self.send("pending", "wait for writer")
            time.sleep(0.1)
            # Readers can still access history during a write transaction.
            self.assertEqual(self.run_app("preview", "99999").returncode, 0)
            db.commit()
        self.assertEqual(self.rows(1)[0][2], "pending")
        self.assertEqual(self.database.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    if "--private-bus" not in sys.argv:
        command = ["dbus-run-session"]
        if config := os.environ.get("DBUS_SESSION_CONF"):
            command.append(f"--config-file={config}")
        raise SystemExit(subprocess.call([
            *command, sys.executable, str(Path(__file__).resolve()), "--private-bus",
        ]))
    sys.argv.remove("--private-bus")
    unittest.main()
