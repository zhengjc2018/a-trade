"""Unix socket reload server 测试。"""
import os
import socket
import time

import pytest


def _start_scheduler_with_socket(tmp_path, monkeypatch):
    from atrade.scheduler.runner import DailyScheduler
    sched = DailyScheduler.__new__(DailyScheduler)
    sched.reload_from_disk = lambda: {"holdings": 1, "t_symbols": 2}
    sock_path = "/tmp/atrade-test-sock-" + str(os.getpid())
    monkeypatch.setattr("atrade.scheduler.runner._RELOAD_SOCK_PATH", sock_path)
    sched._start_reload_socket()
    # 等 server ready
    deadline = time.time() + 2
    while time.time() < deadline:
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(0.2)
            s.connect(sock_path)
            s.close()
            break
        except (FileNotFoundError, ConnectionRefusedError, OSError):
            time.sleep(0.05)
    return sched, sock_path


def test_reload_command_returns_ok(tmp_path, monkeypatch):
    sched, sock_path = _start_scheduler_with_socket(tmp_path, monkeypatch)

    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(2)
    try:
        s.connect(sock_path)
        s.sendall(b"reload\n")
        chunks = []
        deadline = time.time() + 2
        while time.time() < deadline:
            chunk = s.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)
            if b"\n" in chunk:
                break
        resp = b"".join(chunks).decode("utf-8", errors="ignore")
        assert resp.startswith("OK "), f"unexpected: {resp}"
        assert "holdings" in resp
    finally:
        s.close()


def test_unknown_command_returns_err(tmp_path, monkeypatch):
    sched, sock_path = _start_scheduler_with_socket(tmp_path, monkeypatch)

    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(2)
    try:
        s.connect(sock_path)
        s.sendall(b"foo\n")
        time.sleep(0.2)
        resp = s.recv(4096).decode("utf-8", errors="ignore")
        assert resp.startswith("ERR"), f"unexpected: {resp}"
        assert "unknown" in resp
    finally:
        s.close()


def test_reload_failure_returns_err(tmp_path, monkeypatch):
    from atrade.scheduler.runner import DailyScheduler
    sched = DailyScheduler.__new__(DailyScheduler)

    def boom():
        raise RuntimeError("disk full")

    sched.reload_from_disk = boom
    sock_path = "/tmp/atrade-test-sock-" + str(os.getpid())
    monkeypatch.setattr("atrade.scheduler.runner._RELOAD_SOCK_PATH", sock_path)
    sched._start_reload_socket()
    time.sleep(0.2)

    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(2)
    try:
        s.connect(sock_path)
        s.sendall(b"reload\n")
        time.sleep(0.2)
        resp = s.recv(4096).decode("utf-8", errors="ignore")
        assert resp.startswith("ERR")
        assert "disk full" in resp
    finally:
        s.close()


@pytest.fixture(autouse=True)
def cleanup_sock():
    import glob
    yield
    for f in glob.glob('/tmp/atrade-test-sock-*'):
        try:
            os.remove(f)
        except OSError:
            pass
