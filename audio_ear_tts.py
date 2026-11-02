import os
import re
import io
import wave
import time
import ctypes
import hashlib
import asyncio
import threading
from collections import deque
from concurrent.futures import ThreadPoolExecutor
import numpy as np
import edge_tts

try:
    import sounddevice as sd
    import speech_recognition as sr
    AUDIO_AVAILABLE = True
except Exception:
    AUDIO_AVAILABLE = False

try:
    webrtcvad = __import__("webrtcvad")
    WEBRTCVAD_AVAILABLE = True
except Exception:
    WEBRTCVAD_AVAILABLE = False

from vision_screen_cam import ASSETS_DIR

VOICE_CACHE_DIR = os.path.join(ASSETS_DIR, "voice_cache_v18_prod")

VOICE_PROFILES = {
    "gemini_zephyr": {
        "label": "🌸 Gemini Zephyr HD (Warm & Playful Anime Friend)",
        "type": "gemini_tts",
        "voice": "Zephyr",
        "fallback_voice": "hi-IN-SwaraNeural",
        "script": "devanagari"
    },
    "gemini_leda": {
        "label": "💎 Gemini Leda HD + Swara Neural Fallback",
        "type": "gemini_tts",
        "voice": "Leda",
        "fallback_voice": "hi-IN-SwaraNeural",
        "script": "devanagari"
    },
    "gemini_aoede": {
        "label": "✨ Gemini Aoede HD + Neerja Neural Fallback",
        "type": "gemini_tts",
        "voice": "Aoede",
        "fallback_voice": "hi-IN-SwaraNeural",
        "script": "devanagari"
    },
    "swara_anime": {
        "label": "🎀 Swara Expressive Anime Girl (Edge-TTS Neural)",
        "type": "edge",
        "voice": "hi-IN-SwaraNeural",
        "script": "devanagari"
    },
    "neerja_anime": {
        "label": "💖 Neerja Cute Hinglish Anime Dub (Edge-TTS Neural)",
        "type": "edge",
        "voice": "en-IN-NeerjaExpressiveNeural",
        "script": "roman"
    },
    "ana_cute": {
        "label": "🍭 Ana Sweet Waifu (Cute English + Anime Accent)",
        "type": "edge",
        "voice": "en-US-AnaNeural",
        "script": "roman"
    },
    "nanami_waifu": {
        "label": "🎌 Nanami Waifu (Japanese Anime Girl Accent)",
        "type": "edge",
        "voice": "ja-JP-NanamiNeural",
        "script": "roman"
    }
}

FUZZY_WAKE_PATTERNS = [
    r"\bmoon\b", r"\bmun\b", r"\bmon\b", r"\bmonu\b", r"\bmona\b", r"\bmaun\b", r"\bnoon\b",
    r"\boye\s+moon\b", r"\bsun\s+na\s+moon\b", r"\bmoon\s+yaar\b", r"\bhello\s+moon\b",
    r"\bsuno\s+moon\b", r"\bhey\s+moon\b", r"\bare\s+moon\b",
    r"मून", r"मुन", r"मोन", r"मोनू", r"मोना", r"मौन", r"नून",
    r"ओए\s*मून", r"सुन\s*ना\s*मून", r"मून\s*यार", r"हेलो\s*मून", r"सुनो\s*मून"
]


def detect_and_extract_wake_command(text):
    """
    Fuzzy Wake-Word Trigger:
    Triggers the instant the user says 'Moon' or phonetic variations anywhere in a sentence
    ('Oye Moon', 'Sun na Moon', 'Moon yaar', 'Moon VS Code kholo').
    """
    if not text:
        return False, ""
    clean_in = text.strip()
    low = clean_in.lower()

    matched = any(re.search(pat, low, flags=re.I) for pat in FUZZY_WAKE_PATTERNS)

    # Strip leading wake phrase while keeping the rest of the command intact
    cleaned = re.sub(
        r"^(?:oye|are|hello|hey|hi|suno|sun\s+na|sun|ओए|अरे|हेलो|सुनो|सुन\s*ना)?\s*"
        r"(?:moon|मून|मुन|मोन|मोनू|मोना|मौन|mun|mon|monu|mona|maun|noon|नून)\s*"
        r"(?:yaar|यार|जी|ji|babe|baby|दोस्त)?\b[\s,.:!\-]*",
        "",
        clean_in,
        flags=re.I
    ).strip()

    if matched and not cleaned:
        return True, "Oye Moon! Kya haal hai?"
    if matched:
        return True, cleaned
    return False, clean_in


def is_user_typing_on_keyboard(last_key_state):
    if os.name != "nt":
        return False
    try:
        user32 = ctypes.windll.user32
        keys_to_check = [0x08, 0x09, 0x0D, 0x20] + list(range(0x30, 0x3A)) + list(range(0x41, 0x5B))
        for vk in keys_to_check:
            if user32.GetAsyncKeyState(vk) & 0x8000:
                last_key_state["t"] = time.time()
                return True
    except Exception:
        pass
    return (time.time() - last_key_state.get("t", 0.0)) < 0.25


def get_working_input_devices():
    devices = []
    if not AUDIO_AVAILABLE:
        return devices
    try:
        for idx, d in enumerate(sd.query_devices()):
            if d.get("max_input_channels", 0) > 0 and d.get("hostapi", 0) == 0:
                name = d.get("name", f"Mic {idx}")
                if "stereo mix" not in name.lower():
                    devices.append((idx, name))
    except Exception:
        pass
    return devices


class DedicatedAsyncTTSLoop:
    """
    Runs a single persistent background `asyncio` event loop for `edge-tts`
    so we NEVER leak event loops or socket handles across TTS calls.
    """

    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run_loop, daemon=True, name="EdgeTTSLoopThread")
        self.thread.start()

    def _run_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def synthesize_sync(self, text, voice_name, pitch_str, rate_str, out_path, timeout=7.0):
        async def _task():
            comm = edge_tts.Communicate(text, voice=voice_name, pitch=pitch_str, rate=rate_str)
            await comm.save(out_path)

        fut = asyncio.run_coroutine_threadsafe(_task(), self.loop)
        fut.result(timeout=timeout)
        return out_path


class AudioEarAndTTSManager:
    """
    Handles:
    1. Expressive Anime TTS (`edge-tts` with configurable pitch/speed sliders + Gemini HD TTS)
    2. Real-time audio amplitude extraction for live avatar mouth lip-sync
    3. Continuous Non-Blocking Ear (`sounddevice` + `webrtcvad` + Harmonic Spectral Flatness VAD)
    4. Instant Barge-In (interrupts Moon's speech the moment the user talks over her)
    """

    def __init__(
        self,
        api_pool,
        config,
        on_speech_recognized,
        on_barge_in,
        on_status_update,
        on_emotion_update,
        on_amplitude_update,
        on_activity_reset,
        log_callback=None
    ):
        self.api_pool = api_pool
        self.config = config
        self.on_speech_recognized = on_speech_recognized
        self.on_barge_in = on_barge_in
        self.on_status_update = on_status_update
        self.on_emotion_update = on_emotion_update
        self.on_amplitude_update = on_amplitude_update
        self.on_activity_reset = on_activity_reset
        self.log_callback = log_callback

        os.makedirs(VOICE_CACHE_DIR, exist_ok=True)
        self.edge_loop = DedicatedAsyncTTSLoop()

        # Live runtime state wired to Control Panel toggles & sliders
        self.mic_muted = bool(config.get("mic_muted", False))
        self.wake_word_only = bool(config.get("wake_word_only", True))
        self.mic_device_index = config.get("mic_device_index", None)
        self.voice_profile = config.get("voice_profile", "swara_anime")
        if self.voice_profile not in VOICE_PROFILES:
            self.voice_profile = "swara_anime"

        self.tts_pitch_hz = int(config.get("tts_pitch_hz", 15))
        self.tts_rate_pct = int(config.get("tts_rate_pct", 10))

        self.is_speaking = False
        self.is_processing = False
        self.force_listen_now = False
        self.finish_listen_now = False
        self.restart_mic_flag = False
        self.stop_playback_event = threading.Event()
        self.speech_lock = threading.Lock()
        self.active_convo_until = 0.0
        self.speech_started_at = 0.0
        self.current_tts_rms = 0.0
        self._last_key_state = {"t": 0.0}

        self.vad = webrtcvad.Vad(2) if WEBRTCVAD_AVAILABLE else None
        self._ear_thread = None
        self._running = True

    def _log(self, msg, level="INFO"):
        if self.log_callback:
            try:
                self.log_callback(f"[Audio-Ear][{level}] {msg}")
            except Exception:
                pass

    def start_ear_daemon(self):
        if not AUDIO_AVAILABLE:
            self._log("sounddevice / SpeechRecognition unavailable!", "ERROR")
            return
        if self._ear_thread is None or not self._ear_thread.is_alive():
            self._ear_thread = threading.Thread(target=self._continuous_ear_loop, daemon=True, name="MoonEarDaemon")
            self._ear_thread.start()
            self._log(
                f"Continuous Ear started (webrtcvad={'ON' if self.vad else 'Harmonic-Fallback'}, Barge-In=ON)."
            )

    def set_mic_muted(self, muted: bool):
        self.mic_muted = bool(muted)
        if self.mic_muted:
            self.force_listen_now = False
            self.on_status_update("🔇 Mic Muted (Hardware Buffer Halted)")
            self._log("Microphone Muted — audio buffer capture halted.")
        else:
            self.on_status_update(self.default_mic_label())
            self._log("Microphone Unmuted — listening resumed.")

    def set_voice_tuning(self, pitch_hz: int, rate_pct: int, voice_profile: str = None):
        self.tts_pitch_hz = int(pitch_hz)
        self.tts_rate_pct = int(rate_pct)
        if voice_profile and voice_profile in VOICE_PROFILES:
            self.voice_profile = voice_profile
        self._log(f"Voice Tuner updated: Profile={self.voice_profile}, Pitch={self.tts_pitch_hz:+d}Hz, Speed={self.tts_rate_pct:+d}%")

    def default_mic_label(self):
        if self.mic_muted:
            return "🔇 Mic Muted"
        return "🟢 Say 'Oye Moon' / 'Moon'" if self.wake_word_only else "🟢 Mic Active (Barge-In ON)"

    def stop_tts_playback(self):
        """Immediately halts TTS audio output (used by Barge-In and manual click)."""
        self.stop_playback_event.set()
        if AUDIO_AVAILABLE:
            try:
                sd.stop()
            except Exception:
                pass
        self.is_speaking = False
        self.on_amplitude_update(0.0)

    def synthesize_tts_file(self, voice_text, roman_text, emotion="happy"):
        prof = VOICE_PROFILES.get(self.voice_profile, VOICE_PROFILES["swara_anime"])
        pitch_str = f"{self.tts_pitch_hz:+d}Hz"
        rate_str = f"{self.tts_rate_pct:+d}%"

        if prof["type"] == "gemini_tts":
            cache_key = hashlib.md5(f"gem18::{prof['voice']}::{emotion}::{voice_text}".encode("utf-8")).hexdigest()
            wav_path = os.path.join(VOICE_CACHE_DIR, f"{cache_key}.wav")
            if os.path.exists(wav_path) and os.path.getsize(wav_path) > 1000:
                return wav_path
            res = self.api_pool.generate_gemini_tts_wav(voice_text, prof["voice"], emotion, wav_path)
            if res and os.path.exists(res):
                return res
            edge_voice = prof.get("fallback_voice", "hi-IN-SwaraNeural")
        else:
            edge_voice = prof["voice"]

        tts_input = roman_text if prof.get("script") == "roman" else voice_text
        cache_key = hashlib.md5(f"edge18::{edge_voice}::{pitch_str}::{rate_str}::{tts_input}".encode("utf-8")).hexdigest()
        mp3_path = os.path.join(VOICE_CACHE_DIR, f"{cache_key}.mp3")
        if os.path.exists(mp3_path) and os.path.getsize(mp3_path) > 800:
            return mp3_path

        try:
            self.edge_loop.synthesize_sync(tts_input, edge_voice, pitch_str, rate_str, mp3_path, timeout=7.0)
            if os.path.exists(mp3_path) and os.path.getsize(mp3_path) > 500:
                return mp3_path
        except Exception as e:
            self._log(f"Edge-TTS synthesis error: {e}", "WARN")
        return None

    def play_audio_interruptible_with_lipsync(self, file_path, max_wait_seconds=25.0):
        """
        Plays WAV or MP3 while emitting real-time lip-sync amplitude (0.0 .. 1.0)
        and checking `self.stop_playback_event` every 40ms for instant Barge-In interruption!
        """
        if not file_path or not os.path.exists(file_path):
            return
        self.stop_playback_event.clear()
        abs_path = os.path.abspath(file_path)
        ext = os.path.splitext(abs_path)[1].lower()

        if ext == ".wav" and AUDIO_AVAILABLE:
            try:
                with wave.open(abs_path, "rb") as wf:
                    sr_rate = wf.getframerate()
                    n_ch = wf.getnchannels()
                    raw_bytes = wf.readframes(wf.getnframes())
                    audio_np = np.frombuffer(raw_bytes, dtype=np.int16)
                    if n_ch > 1:
                        audio_np = audio_np.reshape(-1, n_ch)

                total_frames = len(audio_np)
                step_samples = max(1, int(sr_rate * 0.045))
                sd.play(audio_np, samplerate=sr_rate)
                start_t = time.perf_counter()

                while (time.perf_counter() - start_t) < (total_frames / float(sr_rate)) + 0.15:
                    if self.stop_playback_event.is_set():
                        sd.stop()
                        break
                    idx = int((time.perf_counter() - start_t) * sr_rate)
                    if idx < total_frames:
                        chunk = audio_np[idx:min(idx + step_samples, total_frames)].astype(np.float32)
                        rms = float(np.sqrt(np.mean(chunk ** 2))) / 8500.0
                        amp = min(max(rms, 0.05), 1.0)
                        self.current_tts_rms = amp
                        self.on_amplitude_update(amp)
                    time.sleep(0.04)
                sd.stop()
                self.current_tts_rms = 0.0
                self.on_amplitude_update(0.0)
                return
            except Exception as e:
                self._log(f"WAV playback fallback to winmm: {e}", "WARN")

        # MP3 / fallback via WinMM MCI with simulated envelope + instant stop_playback_event check
        if os.name == "nt":
            alias = f"moon_snd_{int(time.time() * 1000)}_{threading.get_ident()}"
            winmm = ctypes.windll.winmm
            dev_type = "waveaudio" if ext == ".wav" else "mpegvideo"
            mci_path = abs_path
            try:
                pbuf = ctypes.create_unicode_buffer(512)
                if ctypes.windll.kernel32.GetShortPathNameW(abs_path, pbuf, 512) > 0:
                    mci_path = pbuf.value
            except Exception:
                mci_path = abs_path
            try:
                winmm.mciSendStringW(f'open "{mci_path}" type {dev_type} alias {alias}', None, 0, None)
                winmm.mciSendStringW(f'play {alias}', None, 0, None)
                buf = ctypes.create_unicode_buffer(128)
                start_t = time.perf_counter()
                phase = 0.0
                while (time.perf_counter() - start_t) < max_wait_seconds:
                    if self.stop_playback_event.is_set():
                        winmm.mciSendStringW(f'stop {alias}', None, 0, None)
                        break
                    winmm.mciSendStringW(f'status {alias} mode', buf, 128, None)
                    mode = buf.value.strip().lower()
                    if mode not in ("playing", "seeking"):
                        break
                    phase += 0.65
                    amp = 0.25 + 0.65 * abs(np.sin(phase)) * (0.6 + 0.4 * np.cos(phase * 0.37))
                    self.current_tts_rms = float(amp)
                    self.on_amplitude_update(float(amp))
                    time.sleep(0.045)
            except Exception as e:
                self._log(f"WinMM playback error: {e}", "WARN")
            finally:
                try:
                    winmm.mciSendStringW(f'close {alias}', None, 0, None)
                except Exception:
                    pass
                self.current_tts_rms = 0.0
                self.on_amplitude_update(0.0)

    def speak_synchronously(self, voice_text, roman_text=None, display_text=None, emotion="happy", show_bubble_cb=None):
        with self.speech_lock:
            self.stop_playback_event.clear()
            self.is_speaking = True
            self.speech_started_at = time.time()
            self.on_activity_reset()

            if roman_text is None:
                roman_text = voice_text
            if display_text is None:
                display_text = voice_text

            self.on_status_update("🔊 Synthesizing Anime Voice...")
            audio_file = self.synthesize_tts_file(voice_text, roman_text, emotion)

            if self.stop_playback_event.is_set():
                self.is_speaking = False
                return

            self.on_emotion_update(emotion)
            if show_bubble_cb:
                show_bubble_cb(display_text, max(len(display_text) * 95, 4800))
            self.on_status_update("🔊 Speaking (Speak to Barge-In)...")

            try:
                if audio_file and os.path.exists(audio_file):
                    self.play_audio_interruptible_with_lipsync(audio_file)
            finally:
                self.is_speaking = False
                self.on_amplitude_update(0.0)
                self.on_emotion_update(emotion)
                self.on_status_update(self.default_mic_label())

    # =====================================================================
    # HARMONIC + WEBRTCVAD VOCAL DETECTOR WITH BARGE-IN SUPPORT
    # =====================================================================
    def _compute_vocal_metrics(self, audio_int16, sample_rate=16000):
        """
        Computes:
        1) Vocal formant band RMS (110Hz - 3400Hz)
        2) Spectral flatness (Wiener entropy) to reject fans/AC/broadband noise
        3) `webrtcvad` 30ms frame speech decision
        """
        if is_user_typing_on_keyboard(self._last_key_state):
            return 0.0, False

        samples = audio_int16.astype(np.float32).flatten()
        if len(samples) == 0:
            return 0.0, False
        samples = samples - np.mean(samples)

        fft_mag = np.abs(np.fft.rfft(samples)) + 1e-6
        freqs = np.fft.rfftfreq(len(samples), d=1.0 / sample_rate)
        voice_mask = (freqs >= 115.0) & (freqs <= 3400.0)
        band_mag = fft_mag[voice_mask]
        if len(band_mag) == 0:
            return 0.0, False

        geo_mean = float(np.exp(np.mean(np.log(band_mag))))
        arith_mean = float(np.mean(band_mag))
        flatness = geo_mean / max(arith_mean, 1e-6)
        raw_rms = float(np.sqrt(np.mean(samples ** 2)))

        # Suppress flat fan/white noise
        effective_rms = raw_rms * 0.28 if flatness > 0.56 else raw_rms

        vad_is_speech = (flatness < 0.52 and effective_rms > 22.0)
        if self.vad is not None:
            try:
                frame_len = int(sample_rate * 0.03)  # 480 samples (30ms)
                speech_subframes = 0
                total_subframes = 0
                for i in range(0, len(audio_int16) - frame_len + 1, frame_len):
                    sub = audio_int16[i:i + frame_len].tobytes()
                    total_subframes += 1
                    if self.vad.is_speech(sub, sample_rate):
                        speech_subframes += 1
                if total_subframes > 0:
                    vad_is_speech = (speech_subframes / float(total_subframes)) >= 0.5 and flatness < 0.58
            except Exception:
                pass

        return effective_rms, vad_is_speech

    @staticmethod
    def _normalize_audio_int16(audio_int16, sample_rate=16000):
        samples = audio_int16.astype(np.float32).flatten()
        samples = samples - np.mean(samples)
        fft_vals = np.fft.rfft(samples)
        freqs = np.fft.rfftfreq(len(samples), d=1.0 / sample_rate)
        fft_vals[freqs < 85.0] *= 0.1
        clean = np.fft.irfft(fft_vals, n=len(samples))
        peak = float(np.max(np.abs(clean)))
        if peak > 5.0:
            clean = clean * min(24000.0 / peak, 9.5)
        return np.clip(clean, -32767, 32767).astype(np.int16)

    @staticmethod
    def _recognize_bilingual(recognizer, clean_int16, sample_rate=16000):
        audio_data = sr.AudioData(clean_int16.tobytes(), sample_rate, 2)

        def _google_stt(lang):
            try:
                return recognizer.recognize_google(audio_data, language=lang)
            except Exception:
                return None

        with ThreadPoolExecutor(max_workers=2) as ex:
            fut_hi = ex.submit(_google_stt, "hi-IN")
            fut_en = ex.submit(_google_stt, "en-IN")
            try:
                res_hi = fut_hi.result(timeout=3.8)
            except Exception:
                res_hi = None
            try:
                res_en = fut_en.result(timeout=3.8)
            except Exception:
                res_en = None

        if res_en and any(re.search(p, res_en.lower()) for p in FUZZY_WAKE_PATTERNS):
            return res_en.strip()
        if res_hi and any(re.search(p, res_hi.lower()) for p in FUZZY_WAKE_PATTERNS):
            return res_hi.strip()
        if res_en and res_en.strip():
            return res_en.strip()
        if res_hi and res_hi.strip():
            return res_hi.strip()
        return None

    def _continuous_ear_loop(self):
        recognizer = sr.Recognizer()
        sample_rate = 16000
        chunk_duration = 0.09  # 90ms (divisible by 30ms webrtcvad frames: 3 * 30ms)
        chunk_samples = int(sample_rate * chunk_duration)

        while self._running:
            self.restart_mic_flag = False
            if self.mic_muted:
                time.sleep(0.15)
                continue

            noise_floor = 16.0
            try:
                with sd.InputStream(
                    device=self.mic_device_index,
                    samplerate=sample_rate,
                    channels=1,
                    dtype="int16"
                ) as stream:
                    cal_vals = []
                    for _ in range(6):
                        data, _ = stream.read(chunk_samples)
                        rms, _ = self._compute_vocal_metrics(data, sample_rate)
                        cal_vals.append(rms)
                    noise_floor = max(min(float(np.median(cal_vals)), 280.0), 6.0)
            except Exception as e:
                self._log(f"Mic calibration warning on device {self.mic_device_index}: {e}", "WARN")
                if self.mic_device_index is not None:
                    self.mic_device_index = None
                self.on_status_update("⚠️ Check Microphone Device")
                time.sleep(1.5)
                continue

            self.on_status_update(self.default_mic_label())
            self._log(f"Mic Calibrated: Dynamic Noise Floor = {noise_floor:.1f}")

            while not self.restart_mic_flag and self._running:
                if self.mic_muted:
                    break
                if self.is_processing:
                    time.sleep(0.06)
                    continue

                captured_frames = []
                has_spoken = False
                was_clicked = False

                try:
                    with sd.InputStream(
                        device=self.mic_device_index,
                        samplerate=sample_rate,
                        channels=1,
                        dtype="int16"
                    ) as stream:
                        pre_buffer = deque(maxlen=8)
                        recording = False
                        silence_chunks = 0
                        speech_chunks = 0
                        barge_in_hits = 0
                        max_speech_chunks = int(6.5 / chunk_duration)

                        while not self.restart_mic_flag and not self.mic_muted and not self.is_processing:
                            data, _ = stream.read(chunk_samples)
                            vol, vad_speech = self._compute_vocal_metrics(data, sample_rate)

                            start_threshold = max(noise_floor * 1.9 + 14.0, 20.0)
                            keep_threshold = max(noise_floor * 1.35 + 7.0, 13.0)

                            # BARGE-IN DETECTION WHILE MOON IS SPEAKING
                            if self.is_speaking:
                                # Require close-up loud human voice above speaker echo to trigger Barge-In
                                barge_threshold = max(start_threshold * 2.6, 135.0)
                                if (time.time() - self.speech_started_at) > 0.45 and vol > barge_threshold and vad_speech:
                                    barge_in_hits += 1
                                    pre_buffer.append(data.copy())
                                    if barge_in_hits >= 3:
                                        self._log("BARGE-IN DETECTED! Stopping TTS and listening to user immediately.")
                                        self.stop_tts_playback()
                                        if self.on_barge_in:
                                            self.on_barge_in()
                                        recording = True
                                        has_spoken = True
                                        was_clicked = True
                                        speech_chunks = 3
                                        silence_chunks = 0
                                        captured_frames.extend(pre_buffer)
                                        self.on_emotion_update("listening")
                                        self.on_status_update("👂 Barge-In! बोलिए...")
                                else:
                                    barge_in_hits = 0
                                continue

                            if not recording:
                                pre_buffer.append(data.copy())
                                if self.force_listen_now:
                                    recording = True
                                    was_clicked = True
                                    has_spoken = True
                                    self.force_listen_now = False
                                    self.finish_listen_now = False
                                    silence_chunks = 0
                                    speech_chunks = 3
                                    captured_frames.extend(pre_buffer)
                                    self.on_emotion_update("listening")
                                    self.on_status_update("👂 बोलिए, सुन रही हूँ...")
                                elif vol > start_threshold and vad_speech:
                                    recording = True
                                    was_clicked = False
                                    has_spoken = True
                                    self.finish_listen_now = False
                                    silence_chunks = 0
                                    speech_chunks = 1
                                    captured_frames.extend(pre_buffer)
                                    self.on_emotion_update("listening")
                                    self.on_status_update("👂 सुन रही हूँ...")
                                else:
                                    if vol > 0.0:
                                        noise_floor = min(max(noise_floor * 0.93 + vol * 0.07, 6.0), 320.0)
                            else:
                                captured_frames.append(data.copy())
                                if vol > keep_threshold:
                                    silence_chunks = 0
                                    speech_chunks += 1
                                else:
                                    silence_chunks += 1

                                min_chunks = 14 if was_clicked else 8
                                if (
                                    (len(captured_frames) >= min_chunks and silence_chunks >= 8)
                                    or len(captured_frames) >= max_speech_chunks
                                    or self.finish_listen_now
                                ):
                                    self.finish_listen_now = False
                                    break

                    if (has_spoken and speech_chunks >= 3) or (was_clicked and len(captured_frames) >= 6):
                        self.is_processing = True
                        self.on_status_update("🔍 Recognizing Speech...")
                        raw_np = np.concatenate(captured_frames, axis=0)
                        clean_int16 = self._normalize_audio_int16(raw_np, sample_rate)
                        user_text = self._recognize_bilingual(recognizer, clean_int16, sample_rate)

                        if user_text:
                            self._log(f"Heard raw speech: '{user_text}'")
                            in_convo = (time.time() < self.active_convo_until)
                            has_wake, stripped_cmd = detect_and_extract_wake_command(user_text)

                            if not self.wake_word_only or was_clicked or has_wake or in_convo:
                                final_cmd = stripped_cmd if has_wake else user_text
                                self.on_activity_reset()
                                self.active_convo_until = time.time() + 22.0
                                self.on_speech_recognized(final_cmd)
                            else:
                                self._log(f"Ignored non-wake speech (Wake-Word ON): '{user_text}'")
                                self.on_emotion_update("idle")
                                self.on_status_update(self.default_mic_label())
                        else:
                            if was_clicked:
                                threading.Thread(
                                    target=self.speak_synchronously,
                                    args=(
                                        "अरे बॉस, आपकी आवाज़ साफ़ नहीं आई, थोड़ा पास से बोलो ना!",
                                        "Are boss, aapki aawaaz saaf nahi aayi, thoda paas se bolo na!",
                                        "🎙️ थोड़ा पास से बोलिए!",
                                        "teasing"
                                    ),
                                    daemon=True
                                ).start()
                            else:
                                self.on_emotion_update("idle")
                                self.on_status_update(self.default_mic_label())

                        self.is_processing = False
                    else:
                        self.on_emotion_update("idle")
                        self.on_status_update(self.default_mic_label())

                except Exception as e:
                    self.is_processing = False
                    self._log(f"Ear stream loop exception: {e}", "WARN")
                    time.sleep(0.25)