"""
voice_engine.py
Handles: wake-word listening, speech-to-text, and text-to-speech.
Wake word default: "ultron"

Audio capture uses sounddevice instead of PyAudio (no C++ compiler
needed). TTS output is post-processed with a robotic voice effect
(pitch drop + metallic comb-filter echo + ring modulation) using only
numpy/wave/winsound, no ffmpeg or extra installs required.
"""

import speech_recognition as sr
import pyttsx3
import threading
import queue
import wave
import os
import tempfile
import numpy as np
import sounddevice as sd

try:
    import winsound
    _HAS_WINSOUND = True
except ImportError:
    _HAS_WINSOUND = False

SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH = 2

ROBOT_VOICE_ENABLED = True


def _robotize(input_path, output_path,
              pitch_factor=0.82,
              echo_delay_ms=18,
              echo_decay=0.45,
              ring_mod_freq=35):
    with wave.open(input_path, "rb") as wf:
        n_channels = wf.getnchannels()
        framerate = wf.getframerate()
        n_frames = wf.getnframes()
        raw = wf.readframes(n_frames)

    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float64)
    if n_channels == 2:
        samples = samples.reshape(-1, 2).mean(axis=1)

    if samples.size == 0:
        return False

    new_framerate = max(4000, int(framerate * pitch_factor))

    delay_samples = int(framerate * echo_delay_ms / 1000)
    out = samples.copy()
    if 0 < delay_samples < len(samples):
        out[delay_samples:] += echo_decay * samples[:-delay_samples]

    t = np.arange(len(out)) / framerate
    modulator = 1.0 + 0.15 * np.sin(2 * np.pi * ring_mod_freq * t)
    out = out * modulator

    max_val = np.max(np.abs(out)) or 1.0
    out = (out / max_val * 32000).astype(np.int16)

    with wave.open(output_path, "wb") as wf_out:
        wf_out.setnchannels(1)
        wf_out.setsampwidth(2)
        wf_out.setframerate(new_framerate)
        wf_out.writeframes(out.tobytes())
    return True


class VoiceEngine:
    def __init__(self, wake_word="ultron", on_command=None, on_state_change=None,
                 phrase_seconds=4, command_seconds=6):
        self.wake_word = wake_word.lower()
        self.on_command = on_command
        self.on_state_change = on_state_change
        self.recognizer = sr.Recognizer()
        self.phrase_seconds = phrase_seconds
        self.command_seconds = command_seconds
        self._tts_queue = queue.Queue()
        self._stop_flag = threading.Event()

        default_in = sd.default.device[0] if sd.default.device else None
        dev_name = sd.query_devices(default_in)["name"] if default_in is not None and default_in >= 0 else "UNKNOWN"
        print(f"[debug] VoiceEngine using input device [{default_in}] {dev_name}")

        self._tts_thread = threading.Thread(target=self._tts_worker, daemon=True)
        self._tts_thread.start()

    def _tts_worker(self):
        engine = pyttsx3.init()
        engine.setProperty("rate", 178)
        voices = engine.getProperty("voices")
        for v in voices:
            if "david" in v.name.lower() or "male" in v.name.lower():
                engine.setProperty("voice", v.id)
                break

        tmp_dir = tempfile.gettempdir()
        raw_path = os.path.join(tmp_dir, "ultron_tts_raw.wav")
        fx_path = os.path.join(tmp_dir, "ultron_tts_fx.wav")

        while not self._stop_flag.is_set():
            text = self._tts_queue.get()
            if text is None:
                break
            self._set_state("speaking")

            if ROBOT_VOICE_ENABLED and _HAS_WINSOUND:
                try:
                    engine.save_to_file(text, raw_path)
                    engine.runAndWait()
                    if _robotize(raw_path, fx_path):
                        winsound.PlaySound(fx_path, winsound.SND_FILENAME)
                    else:
                        winsound.PlaySound(raw_path, winsound.SND_FILENAME)
                except Exception as e:
                    print(f"[voice_engine] robot voice effect failed, using plain TTS: {e}")
                    engine.say(text)
                    engine.runAndWait()
            else:
                engine.say(text)
                engine.runAndWait()

            self._set_state("idle")

    def speak(self, text: str):
        print(f"[ULTRON] {text}")
        self._tts_queue.put(text)

    def _record_clip(self, duration: float) -> sr.AudioData:
        print(f"[debug] starting {duration}s recording...")
        recording = sd.rec(
            int(duration * SAMPLE_RATE),
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="int16"
        )
        sd.wait()
        print("[debug] recording finished")
        audio_bytes = recording.tobytes()
        return sr.AudioData(audio_bytes, SAMPLE_RATE, SAMPLE_WIDTH)

    def _is_silent(self, audio: sr.AudioData, threshold=150) -> bool:
        samples = np.frombuffer(audio.frame_data, dtype=np.int16)
        if samples.size == 0:
            return True
        rms = np.sqrt(np.mean(samples.astype(np.float64) ** 2))
        return rms < threshold

    def _set_state(self, state):
        if self.on_state_change:
            self.on_state_change(state)

    def listen_loop(self):
        while not self._stop_flag.is_set():
            try:
                self._set_state("listening")
                audio = self._record_clip(self.phrase_seconds)
                samples = np.frombuffer(audio.frame_data, dtype=np.int16)
                rms = np.sqrt(np.mean(samples.astype(np.float64) ** 2)) if samples.size else 0
                print(f"[debug] captured clip, RMS={rms:.1f}")

                if self._is_silent(audio):
                    print("[debug] treated as silence, skipping recognition")
                    self._set_state("idle")
                    continue

                self._set_state("thinking")
                text = self._recognize(audio)
                print(f"[debug] recognized text: {text!r}")
                if not text:
                    self._set_state("idle")
                    continue

                text_lower = text.lower()
                if self.wake_word in text_lower:
                    remainder = text_lower.split(self.wake_word, 1)[1].strip()
                    if remainder:
                        self._dispatch(remainder)
                    else:
                        self.speak("Yes?")
                        self._capture_command()
                    self._conversation_mode()
                else:
                    print(f"[debug] wake word '{self.wake_word}' not found in text")
                    self._set_state("idle")
            except Exception as e:
                import traceback
                print(f"[voice_engine] listen loop error: {e}")
                traceback.print_exc()
                self._set_state("idle")

    def _conversation_mode(self, max_consecutive_misses=2):
        misses = 0
        EXIT_PHRASES = ("stop listening", "go to sleep", "that's all", "that will be all")

        while not self._stop_flag.is_set():
            self._set_state("listening")
            audio = self._record_clip(self.command_seconds)
            samples = np.frombuffer(audio.frame_data, dtype=np.int16)
            rms = np.sqrt(np.mean(samples.astype(np.float64) ** 2)) if samples.size else 0
            print(f"[debug][conversation] captured clip, RMS={rms:.1f}")

            if self._is_silent(audio):
                misses += 1
                print(f"[debug][conversation] silence ({misses}/{max_consecutive_misses})")
                if misses >= max_consecutive_misses:
                    break
                continue

            self._set_state("thinking")
            text = self._recognize(audio)
            print(f"[debug][conversation] recognized text: {text!r}")

            if not text:
                misses += 1
                if misses >= max_consecutive_misses:
                    break
                self._set_state("idle")
                continue

            misses = 0
            if any(phrase in text.lower() for phrase in EXIT_PHRASES):
                self.speak("Going back to sleep.")
                break

            self._dispatch(text)

        self._set_state("idle")

    def _capture_command(self):
        self._set_state("listening")
        audio = self._record_clip(self.command_seconds)
        self._set_state("thinking")
        text = self._recognize(audio)
        if text:
            self._dispatch(text)
        else:
            self.speak("I didn't catch that.")
            self._set_state("idle")

    def _recognize(self, audio):
        try:
            return self.recognizer.recognize_google(audio)
        except sr.UnknownValueError:
            return None
        except sr.RequestError as e:
            print(f"[voice_engine] recognition service error: {e}")
            return None

    def _dispatch(self, text):
        if self.on_command:
            self.on_command(text)
        self._set_state("idle")

    def stop(self):
        self._stop_flag.set()
        self._tts_queue.put(None)
