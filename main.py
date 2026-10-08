"""VoiceBud: hold ctrl+alt to dictate anywhere. Fully offline.

Setup (5 lines):
  python3.12 -m venv .venv && source .venv/bin/activate
  pip install -r requirements.txt
  Grant Terminal: Microphone, Accessibility, Input Monitoring (System Settings -> Privacy & Security)
  ollama serve   (in another terminal, if not already running)
  python main.py
"""
import os
import threading
import time
import wave

import numpy as np

import yaml

import inject
from audio import Recorder
from cleanup import Cleaner
from hotkey import PushToTalk
from transcribe import Transcriber

APP_NAME = "VoiceBud"
LAST_RECORDING = os.path.expanduser("~/Library/Caches/VoiceBud/last.wav")


def save_last_recording(audio, sample_rate):
    """Keep only the latest dictation on disk (local) so transcription issues can be replayed."""
    try:
        os.makedirs(os.path.dirname(LAST_RECORDING), exist_ok=True)
        with wave.open(LAST_RECORDING, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sample_rate)
            w.writeframes((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes())
    except Exception as e:
        print(f"(could not save last recording: {e})")


def check_permissions():
    """Best-effort permission probes; print one-time setup guidance if missing."""
    import Quartz
    msgs = []
    try:
        if not Quartz.CGPreflightListenEventAccess():
            msgs.append("Input Monitoring (for the global hotkey)")
    except AttributeError:
        pass
    try:
        from ApplicationServices import AXIsProcessTrusted
        if not AXIsProcessTrusted():
            msgs.append("Accessibility (to paste text into other apps)")
    except Exception:
        pass
    if msgs:
        print("SETUP NEEDED — grant your terminal these permissions in")
        print("System Settings -> Privacy & Security, then restart this app:")
        for m in msgs:
            print(f"  - {m}")
        print("  - Microphone (macOS will prompt on first recording)")


def rename_app():
    """Best-effort: show 'VoiceBud' instead of 'Python' where macOS reads the bundle name."""
    try:
        from Foundation import NSBundle, NSProcessInfo
        NSProcessInfo.processInfo().setProcessName_(APP_NAME)
        info = NSBundle.mainBundle().infoDictionary()
        if info is not None:
            info["CFBundleName"] = APP_NAME
    except Exception:
        pass


def main():
    with open("config.yaml") as f:
        cfg = yaml.safe_load(f)

    check_permissions()

    from AppKit import NSApplication
    from PyObjCTools import AppHelper
    from overlay import Overlay

    rename_app()
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(1)  # accessory: no Dock icon

    # menu bar icon so VoiceBud is visible/controllable like a normal app
    from AppKit import NSStatusBar, NSMenu, NSMenuItem
    status = NSStatusBar.systemStatusBar().statusItemWithLength_(-1)
    status.button().setTitle_("🎙️")
    menu = NSMenu.alloc().init()
    item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        f"{APP_NAME} — press {cfg['hotkey']['key']} to dictate", None, "")
    item.setEnabled_(False)
    menu.addItem_(item)
    quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Quit " + APP_NAME, "terminate:", "q")
    menu.addItem_(quit_item)
    status.setMenu_(menu)

    print(f"Loading STT model ({cfg['stt']['model']})...")
    stt = Transcriber(cfg["stt"])
    cleaner = Cleaner(cfg["llm"], vocabulary=cfg["stt"].get("vocabulary"))
    rec = Recorder(
        sample_rate=cfg["audio"]["sample_rate"],
        channels=cfg["audio"]["channels"],
        preroll_ms=cfg["audio"]["preroll_ms"],
    )
    rec.start_stream()
    overlay = Overlay(lambda: rec.level)

    def on_press():
        rec.start()
        AppHelper.callAfter(overlay.show)

    def process(audio):
        t0 = time.time()
        save_last_recording(audio, cfg["audio"]["sample_rate"])
        raw = stt.transcribe(audio)
        if not raw:
            print("(no speech detected)")
            return
        print(f'  raw: "{raw}"')
        text = cleaner.clean(raw)
        inject.inject(text, cfg["inject"])
        print(f'→ "{text}"  ({time.time() - t0:.2f}s)')

    def on_release():
        audio = rec.stop()
        AppHelper.callAfter(overlay.hide)
        threading.Thread(target=process, args=(audio,), daemon=True).start()

    key = cfg["hotkey"]["key"]
    mode = cfg["hotkey"].get("mode", "hold")
    PushToTalk(key, on_press, on_release, mode=mode).start()
    action = "Press" if mode == "toggle" else "Hold"
    print(f"{APP_NAME} ready. {action} [{key}] to dictate ({mode} mode).")
    try:
        AppHelper.runEventLoop()
    finally:
        rec.close()


if __name__ == "__main__":
    main()
