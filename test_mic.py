"""
test_mic.py
Standalone diagnostic: lists audio devices, records from the default
input AND from a WASAPI device (usually cleaner than MME on Windows),
saves both as playable .wav files so you can listen to exactly what
was captured, and attempts speech recognition on each.

Usage:
    python test_mic.py
"""

import wave
import numpy as np
import sounddevice as sd
import speech_recognition as sr

SAMPLE_RATE = 16000
DURATION = 4


def save_wav(filename, recording, sample_rate=SAMPLE_RATE):
    with wave.open(filename, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # int16
        wf.setframerate(sample_rate)
        wf.writeframes(recording.tobytes())


def record_from(device_index, label):
    print(f"\n--- Recording from: {label} (device {device_index}) ---")
    input(f"Press ENTER, then say 'Ultron, open chrome' clearly for {DURATION} seconds...")
    recording = sd.rec(
        int(DURATION * SAMPLE_RATE),
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="int16",
        device=device_index
    )
    sd.wait()
    print("Done recording.")

    samples = recording.flatten()
    rms = np.sqrt(np.mean(samples.astype(np.float64) ** 2))
    peak = np.max(np.abs(samples))
    clipped = np.sum(np.abs(samples) >= 32760)
    print(f"RMS: {rms:.1f}   Peak: {peak}/32767   Clipped samples: {clipped}")

    filename = f"test_recording_{label.replace(' ', '_')}.wav"
    save_wav(filename, recording)
    print(f"Saved playback file: {filename}  <-- double-click this to listen to it")

    audio = sr.AudioData(recording.tobytes(), SAMPLE_RATE, 2)
    r = sr.Recognizer()
    try:
        text = r.recognize_google(audio)
        print(f"RECOGNIZED: {text!r}")
        return True
    except sr.UnknownValueError:
        print("Google could not understand this audio.")
        return False
    except sr.RequestError as e:
        print(f"Could not reach Google's recognition service: {e}")
        return False


def find_wasapi_mic():
    """Find a WASAPI-hosted microphone input, usually cleaner than MME."""
    devices = sd.query_devices()
    hostapis = sd.query_hostapis()
    for i, d in enumerate(devices):
        if d["max_input_channels"] > 0:
            api_name = hostapis[d["hostapi"]]["name"]
            if "WASAPI" in api_name and "mic" in d["name"].lower():
                return i, d["name"]
    return None, None


def main():
    print("=== Available audio devices ===")
    print(sd.query_devices())

    default_in = sd.default.device[0]
    default_name = sd.query_devices(default_in)["name"] if default_in is not None else "unknown"
    print(f"\nDefault input: [{default_in}] {default_name}")

    # Test 1: whatever sounddevice currently uses by default (likely MME)
    ok_default = record_from(None, "default")

    # Test 2: explicit WASAPI mic, if one exists and differs from default
    wasapi_idx, wasapi_name = find_wasapi_mic()
    if wasapi_idx is not None and wasapi_idx != default_in:
        ok_wasapi = record_from(wasapi_idx, "wasapi")
    else:
        ok_wasapi = None
        print("\n(No distinct WASAPI mic found to test separately.)")

    print("\n=== Summary ===")
    print(f"Default device recognition worked: {ok_default}")
    if ok_wasapi is not None:
        print(f"WASAPI device recognition worked: {ok_wasapi}")
        if ok_wasapi and not ok_default:
            print(f">>> Fix: set sd.default.device = {wasapi_idx} near the top of voice_engine.py")

    if not ok_default and ok_wasapi is not True:
        print("\nNeither worked. Next steps:")
        print("1. Play back the saved .wav file(s) above — does it sound clear, or")
        print("   faint/distorted/silent? That tells us if it's a hardware/OS gain issue.")
        print("2. Check Windows mic volume: Settings > System > Sound > Input > your mic")
        print("   > Volume — try setting it to 80-100.")
        print("3. Check Control Panel > Sound > Recording > (your mic) > Levels tab >")
        print("   enable 'Microphone Boost' if available.")
        print("4. Make sure no other app is also holding the microphone open.")


if __name__ == "__main__":
    main()