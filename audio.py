"""Mic capture: continuous 500ms pre-roll ring buffer + on-demand recording.

The stream follows the macOS default input device and heals itself:
- a watchdog reopens it when the default mic changes (AirPods in/out, external mic)
  or when CoreAudio silently kills it (sleep/wake, device errors);
- Bluetooth mics are only opened while recording, so AirPods aren't forced into
  low-quality call mode all day (no pre-roll in that case).
"""
import collections
import ctypes
import ctypes.util
import threading
import time

import numpy as np
import sounddevice as sd


# --- CoreAudio: read the current default input device (PortAudio caches it at init) ---
class _PropAddr(ctypes.Structure):
    _fields_ = [("selector", ctypes.c_uint32), ("scope", ctypes.c_uint32), ("element", ctypes.c_uint32)]


def _fourcc(s):
    return int.from_bytes(s.encode(), "big")


_ca = ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreAudio"))
_ca.AudioObjectGetPropertyData.argtypes = [
    ctypes.c_uint32, ctypes.POINTER(_PropAddr), ctypes.c_uint32, ctypes.c_void_p,
    ctypes.POINTER(ctypes.c_uint32), ctypes.c_void_p,
]
_ca.AudioObjectGetPropertyData.restype = ctypes.c_int32
_SYSTEM_OBJECT = 1
_GLOBAL = _fourcc("glob")
_BLUETOOTH = {_fourcc("blue"), _fourcc("blea")}


def _get_u32(obj, selector):
    addr = _PropAddr(_fourcc(selector), _GLOBAL, 0)
    out, size = ctypes.c_uint32(0), ctypes.c_uint32(4)
    err = _ca.AudioObjectGetPropertyData(obj, ctypes.byref(addr), 0, None, ctypes.byref(size), ctypes.byref(out))
    return out.value if err == 0 else None


def default_input_device():
    """CoreAudio id of the current default input (0/None = no mic)."""
    return _get_u32(_SYSTEM_OBJECT, "dIn ")


def _log(msg):
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} [audio] {msg}")


def is_bluetooth(device_id):
    return bool(device_id) and _get_u32(device_id, "tran") in _BLUETOOTH


class Recorder:
    STALL_SECONDS = 2.0   # no callback for this long = stream is dead
    WATCH_INTERVAL = 1.0
    MAX_BACKOFF = 30.0    # cap between reopen attempts while the mic stays dead

    def __init__(self, sample_rate=16000, channels=1, preroll_ms=500, blocksize=320):
        self.sample_rate = sample_rate
        self.channels = channels
        self.blocksize = blocksize
        preroll_blocks = max(1, int(sample_rate * preroll_ms / 1000 / blocksize))
        self._preroll = collections.deque(maxlen=preroll_blocks)
        self._chunks = []
        self._recording = False
        self.level = 0.0
        self._lock = threading.Lock()      # guards buffers (shared with the audio callback)
        self._ctl = threading.RLock()      # guards stream open/close
        self._stream = None
        self._device_id = None
        self._on_demand = False            # True for Bluetooth mics
        self._last_cb = 0.0
        self._closed = False
        self._failures = 0                 # consecutive stalled reopens (for backoff)
        self._next_retry = 0.0
        self._got_audio = False            # a callback arrived since the last open
        self._mic_name = None

    def _callback(self, indata, frames, time_info, status):
        self._last_cb = time.monotonic()
        self._got_audio = True
        block = indata.copy()
        with self._lock:
            if self._recording:
                self._chunks.append(block)
                self.level = float(np.sqrt((block ** 2).mean()))  # RMS for the waveform UI
            else:
                self._preroll.append(block)

    # --- stream management ---
    def _close_stream(self):
        with self._ctl:
            if self._stream is not None:
                try:
                    self._stream.abort()
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None
            with self._lock:
                self._preroll.clear()

    def _open_stream(self):
        """(Re)open on the current default mic. Re-inits PortAudio so it sees device changes."""
        with self._ctl:
            self._close_stream()
            self._device_id = default_input_device()
            self._on_demand = is_bluetooth(self._device_id)
            if not self._device_id:
                return False
            try:
                sd._terminate()
                sd._initialize()
                self._stream = sd.InputStream(
                    samplerate=self.sample_rate, channels=self.channels, dtype="float32",
                    blocksize=self.blocksize, callback=self._callback,
                )
                self._got_audio = False
                self._last_cb = time.monotonic() + 3.0  # grace: AirPods take a moment to switch to mic mode
                self._stream.start()
                name = sd.query_devices(kind="input")["name"]
                if name != self._mic_name:
                    self._mic_name = name
                    _log(f"mic: {name}{' (bluetooth: opened only while recording)' if self._on_demand else ''}")
                return True
            except Exception as e:
                _log(f"could not open mic: {e}")
                self._close_stream()
                return False

    def _healthy(self):
        s = self._stream
        return (s is not None and s.active
                and time.monotonic() - self._last_cb < self.STALL_SECONDS)

    def _sync(self, force=False):
        """Make the stream match the current device and mode; reopen if it died.

        Repeated stalls back off (1s, 2s, 4s... up to MAX_BACKOFF) unless force=True,
        which is used when the user presses the hotkey.
        """
        with self._ctl:
            now = time.monotonic()
            dev = default_input_device()
            if dev != self._device_id:
                self._device_id = dev
                self._on_demand = is_bluetooth(dev)
                self._failures = 0
                self._next_retry = 0.0
                self._close_stream()
            needed = self._recording or not self._on_demand
            if needed and self._healthy():
                if self._got_audio:  # only real audio proves recovery (not the open grace period)
                    self._failures = 0
                    self._next_retry = 0.0
            elif needed:
                if not force and now < self._next_retry:
                    return
                if self._stream is not None:  # was open but went silent (vs. first open)
                    self._failures += 1
                    if self._failures == 1 or self._failures % 20 == 0:
                        _log(f"mic stream stalled, reopening (attempt {self._failures})")
                if not self._open_stream():
                    self._failures += 1
                self._next_retry = now + min(self.MAX_BACKOFF, 2 ** max(0, self._failures - 1))
            elif self._stream is not None:
                self._close_stream()

    def _watchdog(self):
        while not self._closed:
            time.sleep(self.WATCH_INTERVAL)
            try:
                self._sync()
            except Exception as e:
                _log(f"watchdog error: {e}")

    def start_stream(self):
        self._sync()
        if self._stream is None and not self._on_demand:
            self._open_stream()
        threading.Thread(target=self._watchdog, daemon=True).start()

    # --- recording ---
    def start(self):
        """Begin recording; the pre-roll buffer is prepended so the first word isn't clipped."""
        with self._ctl:
            with self._lock:
                self._chunks = list(self._preroll)
                self._preroll.clear()
                self._recording = True
            self._sync(force=True)  # never record into a dead stream; opens Bluetooth mics on demand

    def stop(self):
        """Stop recording and return mono float32 audio."""
        with self._lock:
            self._recording = False
            chunks, self._chunks = self._chunks, []
            self.level = 0.0
        if self._on_demand:
            self._close_stream()  # release AirPods mic so they return to high-quality mode
        if not chunks:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(chunks).flatten()

    def close(self):
        self._closed = True
        self._close_stream()
