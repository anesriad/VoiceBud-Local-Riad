"""Local STT: mlx-whisper on the Apple GPU (default) or faster-whisper (CTranslate2) on CPU."""
import re

import numpy as np
from faster_whisper.vad import VadOptions, get_speech_timestamps

SR = 16000
MAX_CHUNK_S = 28  # stay under whisper's 30s window

# split long speech at the best pause; Silero VAD also gates pure silence,
# where whisper hallucinates text like "Thank you."
_VAD = VadOptions(max_speech_duration_s=25, min_silence_duration_ms=500, speech_pad_ms=200)


def speech_chunks(audio):
    """Speech regions packed into <=28s chunks, cut at natural pauses. [] = no speech.

    Each chunk is transcribed separately with the vocabulary prompt, instead of letting
    whisper slide its own 30s windows. Whisper's sliding windows feed each window's text
    into the next: one bad window then loops ("What do you think? What do you think?...")
    to the end, and with that conditioning off the prompt is dropped after the first window.
    """
    segs = get_speech_timestamps(audio, _VAD)
    chunks = []
    for seg in segs:
        if chunks and seg["end"] - chunks[-1][0] <= MAX_CHUNK_S * SR:
            chunks[-1][1] = seg["end"]
        else:
            chunks.append([seg["start"], seg["end"]])
    return [audio[a:b] for a, b in chunks]


def collapse_repeats(text):
    """Safety net: a phrase repeated 3+ times in a row is a whisper loop, keep one copy."""
    return re.sub(r"(\b.{4,120}?[.?!,]?)(?:\s+\1){2,}", r"\1", text, flags=re.IGNORECASE)


class Transcriber:
    def __init__(self, cfg):
        self.cfg = cfg
        # Names and jargon whisper can't guess ("Ollama", "VoiceBud"). Fed as the initial prompt,
        # which biases spelling without forcing the words in.
        vocab = cfg.get("vocabulary") or []
        self._prompt = ", ".join(vocab) + "." if vocab else None
        self._fixes = [(re.compile(rf"\b{re.escape(k)}\b", re.IGNORECASE), v)
                       for k, v in (cfg.get("replacements") or {}).items()]
        engine = cfg.get("engine", "faster-whisper")
        if engine == "mlx-whisper":
            import mlx_whisper  # Apple GPU path
            self._mlx = mlx_whisper
            self._model = None
            self._repo = cfg.get("model", "mlx-community/whisper-large-v3-turbo")
            self._mlx.transcribe(np.zeros(16000, dtype=np.float32), path_or_hf_repo=self._repo)  # load + warm up
            if self._prompt:
                from mlx_whisper.tokenizer import get_tokenizer
                n = len(get_tokenizer(multilingual=True, language="en").encode(" " + self._prompt))
                if n > 223:  # whisper keeps only the LAST 223 prompt tokens
                    print(f"Vocabulary is {n} tokens; whisper ignores the first {n - 223}. Trim stt.vocabulary.")
        else:
            from faster_whisper import WhisperModel
            self._mlx = None
            self._model = WhisperModel(
                cfg.get("model", "base"),
                device="cpu",
                compute_type=cfg.get("compute_type", "int8"),
            )

    def transcribe(self, audio):
        """audio: mono float32 numpy array at 16kHz. Returns text."""
        if audio.size == 0:
            return ""
        if self._mlx is not None:
            parts = [
                self._mlx.transcribe(
                    chunk,
                    path_or_hf_repo=self._repo,
                    language=self.cfg.get("language"),
                    initial_prompt=self._prompt,
                    condition_on_previous_text=False,
                )["text"].strip()
                for chunk in speech_chunks(audio)
            ]
            return self._fix(" ".join(p for p in parts if p))
        segments, _ = self._model.transcribe(
            audio,
            language=self.cfg.get("language"),
            vad_filter=True,
            beam_size=1,
            initial_prompt=self._prompt,
            condition_on_previous_text=False,
        )
        return self._fix(" ".join(seg.text.strip() for seg in segments).strip())

    def _fix(self, text):
        text = collapse_repeats(text)
        for pattern, word in self._fixes:
            text = pattern.sub(word, text)
        return text
