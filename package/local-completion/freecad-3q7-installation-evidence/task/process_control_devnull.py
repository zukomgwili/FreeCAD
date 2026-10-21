"""POSIX, serial, bounded process ownership for the standalone 5ar QA drivers."""

from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import signal
import subprocess
import time


def assert_serial(extra_names=()):
    processes = subprocess.run(
        ["ps", "-axo", "pid=,comm="], check=True, capture_output=True,
        text=True, timeout=10,
    ).stdout
    names = {
        "FreeCAD", "FreeCADCmd", "ctest", "ccx", "ccx_2.23_conda",
        "ccx-force-accounting", "NativeMpcComponentUnit", *extra_names,
    }
    for line in processes.splitlines():
        fields = line.strip().split(None, 1)
        if (
            len(fields) == 2 and int(fields[0]) != os.getpid()
            and Path(fields[1]).name in names
        ):
            raise RuntimeError("Serial native guard: existing process " + line.strip())


def group_exists(identifier):
    try:
        os.killpg(identifier, 0)
        return True
    except ProcessLookupError:
        return False


def _signal_group(identifier, signum):
    try:
        os.killpg(identifier, signum)
    except ProcessLookupError:
        pass


def _interrupt(signum, _frame):
    raise SystemExit(128 + signum)


@contextmanager
def _interruption_handlers():
    watched = (signal.SIGTERM, signal.SIGHUP)
    previous = {signum: signal.getsignal(signum) for signum in watched}
    try:
        for signum in watched:
            signal.signal(signum, _interrupt)
        yield
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def _reap_owned_group(child):
    """Always clean ONLY the new session created for this exact Popen child."""
    watched = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
    previous = {signum: signal.getsignal(signum) for signum in watched}
    try:
        # A second interrupt cannot abandon the bounded cleanup of our child.
        for signum in watched:
            signal.signal(signum, signal.SIG_IGN)
        if child.poll() is None or group_exists(child.pid):
            _signal_group(child.pid, signal.SIGTERM)
            try:
                child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
        if group_exists(child.pid):
            _signal_group(child.pid, signal.SIGKILL)
        if child.poll() is None:
            child.wait(timeout=2)
        until = time.monotonic() + 1
        while group_exists(child.pid) and time.monotonic() < until:
            time.sleep(0.05)
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def run_bounded(command, *, cwd, log, timeout, environment=None):
    """Reap on timeout, exception, Ctrl-C, SIGTERM or SIGHUP; never run a shell.

    SIGKILL cannot be handled by any supervisor; the caller must retain outer
    process ownership when forcibly killing this supervisor. This function is
    called by main-thread CLI drivers.
    """
    if os.name != "posix":
        raise RuntimeError("This native QA supervisor requires POSIX process groups")
    started, timed_out, child = time.monotonic(), False, None
    with _interruption_handlers(), Path(log).open("xb") as output:
        try:
            child = subprocess.Popen(
                command, cwd=cwd, env=environment, stdout=output,
                stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True,
            )
            child.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
        finally:
            if child is not None:
                _reap_owned_group(child)
    return {
        "command": [str(item) for item in command],
        "pid": child.pid, "process_group": child.pid,
        "returncode": child.returncode, "timed_out": timed_out,
        "reaped": child.poll() is not None, "child_reaped": child.poll() is not None,
        "process_group_gone": not group_exists(child.pid),
        "elapsed_seconds": time.monotonic() - started,
        "log_sha256": hashlib.sha256(Path(log).read_bytes()).hexdigest(),
    }
