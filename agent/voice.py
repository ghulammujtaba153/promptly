import io
import os

from groq import Groq

WHISPER_MODEL = os.getenv("GROQ_WHISPER_MODEL", "whisper-large-v3-turbo")


def transcribe_audio(audio_bytes: bytes, mime_type: str = "audio/wav") -> str:
    """Transcribe microphone audio using Groq Whisper."""
    ext = ".webm"
    if "wav" in mime_type:
        ext = ".wav"
    elif "mp4" in mime_type or "m4a" in mime_type:
        ext = ".m4a"
    elif "ogg" in mime_type:
        ext = ".ogg"

    file_obj = io.BytesIO(audio_bytes)
    file_obj.name = f"prompt{ext}"

    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    result = client.audio.transcriptions.create(
        file=file_obj,
        model=WHISPER_MODEL,
        response_format="text",
    )
    return result if isinstance(result, str) else result.text
