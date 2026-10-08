"""Transcript cleanup via a local Ollama LLM. Model name comes ONLY from config."""
import difflib
import re
import threading
import time

import requests


class Cleaner:
    RECHECK_SECONDS = 30  # how long an Ollama availability check is trusted

    def __init__(self, cfg):
        self.cfg = cfg
        self.enabled = bool(cfg.get("enabled", True))
        self.model = cfg["model"]
        self.base_url = cfg.get("base_url", "http://localhost:11434").rstrip("/")
        self.min_words = int(cfg.get("min_words_for_cleanup", 10))
        self.min_similarity = float(cfg.get("min_similarity", 0.8))
        self.keep_alive = cfg.get("keep_alive", "30m")
        self._available = None
        self._checked_at = 0.0
        if self.enabled:
            # Ollama often starts after VoiceBud at login: never disable for good, just
            # re-check lazily. Warm the model in the background so the first dictation is fast.
            threading.Thread(target=self._warm, daemon=True).start()

    # --- Ollama availability ---
    def _check(self):
        try:
            r = requests.get(f"{self.base_url}/api/tags", timeout=3)
            names = [m["name"] for m in r.json().get("models", [])]
            if any(n == self.model or n.split(":")[0] == self.model for n in names):
                return True
            print(f"Model {self.model} not installed — run: ollama pull {self.model}")
        except requests.RequestException:
            print(f"Ollama not reachable at {self.base_url} — using raw transcripts until it is.")
        return False

    def _ready(self):
        now = time.monotonic()
        if self._available is None or now - self._checked_at > self.RECHECK_SECONDS:
            was = self._available
            self._available = self._check()
            self._checked_at = now
            if self._available and was is False:
                print("Ollama is back — cleanup enabled.")
        return self._available

    def _warm(self):
        for _ in range(20):  # keep trying for ~10 min while Ollama boots
            if self._ready():
                try:
                    requests.post(f"{self.base_url}/api/generate",
                                  json={"model": self.model, "prompt": "", "keep_alive": self.keep_alive},
                                  timeout=60)
                except requests.RequestException:
                    pass
                return
            time.sleep(30)

    # --- cleanup ---
    def _chat(self, text, temperature):
        messages = [{"role": "system", "content": self.cfg.get("system_prompt", "")}]
        if self.cfg.get("example_input") and self.cfg.get("example_output"):
            # one worked example: small models copy the format much better than they follow rules
            messages += [
                {"role": "user", "content": self.cfg["example_input"].strip()},
                {"role": "assistant", "content": self.cfg["example_output"].strip()},
            ]
        messages.append({"role": "user", "content": text})
        r = requests.post(
            f"{self.base_url}/api/chat",
            json={
                "model": self.model,
                "messages": messages,
                "stream": False,
                "think": False,  # disable reasoning mode (qwen3 etc.) — cleanup must be instant
                "keep_alive": self.keep_alive,
                "options": {"temperature": temperature},
            },
            timeout=30,
        )
        return r.json().get("message", {}).get("content", "")

    def clean(self, text):
        # LATENCY RULE: short utterances skip the LLM entirely.
        if not self.enabled or not text or len(text.split()) < self.min_words:
            return text
        if not self._ready():
            return text
        try:
            for temperature in (float(self.cfg.get("temperature", 0.1)), 0.0):
                cleaned = normalize(self._chat(text, temperature), text)
                ratio = similarity(text, cleaned)
                if cleaned and ratio >= self.min_similarity:
                    return cleaned
                print(f"Cleanup changed too many words (similarity {ratio:.2f}) — retrying.")
            print("Cleanup kept rewording; using raw transcript.")
            return text
        except requests.RequestException as e:
            self._available = None  # force a re-check next time
            print(f"Cleanup failed ({e}); using raw transcript.")
            return text


def _words(s):
    return re.findall(r"[a-z0-9']+", s.lower().replace("’", "'"))


def similarity(raw, cleaned):
    """Word-level similarity (0-1). Filler removal and punctuation barely move it; rewording does."""
    return difflib.SequenceMatcher(None, _words(raw), _words(cleaned), autojunk=False).ratio()


def normalize(out, raw):
    """Strip LLM typography habits so the text reads like the speaker typed it."""
    out = out.strip()
    if len(out) > 1 and out[0] == out[-1] == '"' and not raw.strip().startswith('"'):
        out = out[1:-1].strip()
    out = out.translate({0x2018: "'", 0x2019: "'", 0x201C: '"', 0x201D: '"'})
    out = re.sub(r"(\d)\s*[–—]\s*(\d)", r"\1-\2", out)  # 30–300 -> 30-300
    out = re.sub(r"\s*[–—]\s*", ", ", out)                 # em/en dash -> comma
    out = re.sub(r",\s*([,.!?;:])", r"\1", out)                      # ", ." -> "."
    out = "\n".join(line.rstrip() for line in out.splitlines())
    return re.sub(r"\n{3,}", "\n\n", out).strip()
