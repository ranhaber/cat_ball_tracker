"""
Non-blocking logging for the process loop and hot path.

Enqueues log messages and writes them from a dedicated thread so the
detection loop never blocks on stdout/pipe/journal I/O. Real-time oriented:
bounded queue, drop on full (no blocking), daemon writer thread.
"""

import logging
import queue
import sys
import threading

# Bounded queue; writer thread drains to stdout. If full, emit drops (no block).
_LOG_QUEUE_MAXSIZE = 512

_queue = None
_writer_thread = None
_logger = None


class _QueueHandler(logging.Handler):
    """Enqueues log records for the writer thread. emit() is non-blocking."""

    def __init__(self, log_queue):
        super().__init__()
        self._q = log_queue

    def emit(self, record):
        try:
            msg = self.format(record)
            self._q.put_nowait(msg)
        except queue.Full:
            pass  # Drop to avoid blocking; real-time first
        except Exception:
            self.handleError(record)


def _writer_loop(log_queue):
    """Drain queue to stdout. Runs in a dedicated thread."""
    try:
        import ctypes
        libc = ctypes.CDLL('libc.so.6')
        PR_SET_NAME = 15
        libc.prctl(PR_SET_NAME, b'CatDome-Log', 0, 0, 0)
    except Exception:
        pass
    while True:
        try:
            msg = log_queue.get(timeout=0.25)
            sys.stdout.write(msg + "\n")
            sys.stdout.flush()
        except queue.Empty:
            continue
        except Exception:
            break


def setup_async_logging():
    """Install async logging: handler on 'cat_dome' logger, start writer thread.
    Call once at startup (e.g. from main.py). Safe to call multiple times (no-op after first).
    """
    global _queue, _writer_thread, _logger
    if _logger is not None:
        return
    _queue = queue.Queue(maxsize=_LOG_QUEUE_MAXSIZE)
    _logger = logging.getLogger("cat_dome")
    _logger.setLevel(logging.DEBUG)
    _logger.propagate = False
    handler = _QueueHandler(_queue)
    handler.setFormatter(logging.Formatter("%(message)s"))
    _logger.addHandler(handler)
    _writer_thread = threading.Thread(target=_writer_loop, args=(_queue,), daemon=True, name="CatDome-Log")
    _writer_thread.start()


def get_logger():
    """Return the async logger. Use after setup_async_logging()."""
    return _logger if _logger is not None else logging.getLogger("cat_dome")


def log(msg, *args, **kwargs):
    """Log a message asynchronously (no block on I/O). msg can use % formatting."""
    logger = get_logger()
    if not logger.handlers:
        # Not set up (e.g. tests): fallback to print so output is not lost
        try:
            print(msg % args if args else msg)
        except (TypeError, KeyError):
            print(msg, *args)
        return
    if args or kwargs:
        logger.info(msg, *args, **kwargs)
    else:
        logger.info(msg)
