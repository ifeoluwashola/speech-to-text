import os
import wave
import struct
import math
import tempfile
from services.audio_extractor import extract_youtube_video_id, try_fetch_youtube_captions
from services.transcriber import get_model, transcribe_audio, format_segments_to_paragraphs


def test_youtube_id_extraction():
    urls = [
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://youtu.be/dQw4w9WgXcQ?si=123", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/embed/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ]
    for url, expected in urls:
        extracted = extract_youtube_video_id(url)
        assert extracted == expected, f"Failed for {url}: got {extracted}, expected {expected}"
    print("✓ YouTube URL extraction passed.")


def test_synthetic_audio_transcription():
    # Generate a tiny 2-second 16kHz mono WAV file
    sample_rate = 16000
    duration = 2.0
    num_samples = int(sample_rate * duration)
    
    with tempfile.TemporaryDirectory() as tmpdir:
        wav_path = os.path.join(tmpdir, "test.wav")
        with wave.open(wav_path, "w") as wav_file:
            wav_file.setnchannels(1)  # Mono
            wav_file.setsampwidth(2)  # 16-bit
            wav_file.setframerate(sample_rate)
            # 440 Hz tone
            for i in range(num_samples):
                val = int(32767.0 * 0.5 * math.sin(2.0 * math.pi * 440.0 * i / sample_rate))
                wav_file.writeframes(struct.pack('<h', val))
        
        assert os.path.exists(wav_path)
        print(f"✓ Synthetic WAV generated: {wav_path}")
        
        # Test loading model and transcribing
        print("Testing Whisper base.en model...")
        result = transcribe_audio(wav_path, model_name="base.en", language="en")
        print("✓ Whisper transcription executed successfully. Result:", result)
        assert "text" in result
        assert "word_count" in result
        assert "duration_seconds" in result
        
    # Verify tmpdir was deleted
    assert not os.path.exists(tmpdir)
    print("✓ Ephemeral cleanup verified: temporary files successfully purged.")


if __name__ == "__main__":
    print("Running system verification tests...")
    test_youtube_id_extraction()
    test_synthetic_audio_transcription()
    print("\n🎉 ALL TESTS PASSED SUCCESSFULLY!")
