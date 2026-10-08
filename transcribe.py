"""Local STT: mlx-whisper on the Apple GPU (default) or faster-whisper (CTranslate2) on CPU."""
import numpy as np
from faster_whisper.vad import get_speech_timestamps


def has_speech(audio):
    """Silero VAD gate: on pure silence whisper hallucinates text like "Thank you."."""
    return bool(get_speech_timestamps(audio))


class Transcriber:
    def __init__(self, cfg):
        self.cfg = cfg
        # Names and jargon whisper can't guess ("Ollama", "VoiceBud"). Fed as the initial prompt,
        # which biases spelling without forcing the words in.
        vocab = cfg.get("vocabulary") or []
        self._prompt = ", ".join(vocab) + "." if vocab else None
        engine = cfg.get("engine", "faster-whisper")
        if engine == "mlx-whisper":
            import mlx_whisper  # Apple GPU path
            self._mlx = mlx_whisper
            self._model = None
            self._repo = cfg.get("model", "mlx-community/whisper-large-v3-turbo")
            self._mlx.transcribe(np.zeros(16000, dtype=np.float32), path_or_hf_repo=self._repo)  # load + warm up
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
            if not has_speech(audio):
                return ""
            result = self._mlx.transcribe(
                audio,
                path_or_hf_repo=self._repo,
                language=self.cfg.get("language"),
                initial_prompt=self._prompt,
            )
            return result.get("text", "").strip()
        segments, _ = self._model.transcribe(
            audio,
            language=self.cfg.get("language"),
            vad_filter=True,
            beam_size=1,
            initial_prompt=self._prompt,
        )
        return " ".join(seg.text.strip() for seg in segments).strip()
