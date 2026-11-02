import os
import sys
import math
import time
import random
import threading
from collections import deque
import numpy as np
import psutil
import sounddevice as sd
import speech_recognition as sr

from PyQt5.QtWidgets import (
    QApplication, QWidget, QLabel, QMenu, QActionGroup,
    QInputDialog, QFileDialog, QMessageBox
)
from PyQt5.QtCore import Qt, QTimer, QPoint, pyqtSignal, QObject
from PyQt5.QtGui import QPixmap, QFont

from config_and_sprites import (
    ASSETS_DIR, SPRITE_VERSION_FILE, load_config, save_config_file,
    build_sprites_if_needed, trim_own_memory
)
from system_tools import (
    real_system_ram_cleaner, scan_all_installed_pc_apps,
    get_active_window_title, capture_desktop_screen, capture_webcam,
    execute_agent_steps_with_verification
)
from ai_brain import (
    MODEL_COOLDOWN, KEY_COOLDOWN, needs_webcam_vision, needs_screen_vision,
    call_resilient_multi_brain, generate_proactive_interaction
)
from voice_and_ear import (
    MIC_AVAILABLE, VOICE_PROFILES, TTS_COOLDOWN,
    check_and_strip_wake_word, generate_gemini_hd_tts_multi_key,
    generate_edge_anime_tts_cached, play_audio_windows,
    get_working_input_devices, compute_speech_formant_rms,
    normalize_and_clean_wav_bytes, recognize_bilingual_fast,
    volume_bar_string
)

class MoonSignals(QObject):
    set_emotion = pyqtSignal(str)
    show_bubble = pyqtSignal(str, int)
    set_status = pyqtSignal(str)
    start_lipsync = pyqtSignal()
    stop_lipsync = pyqtSignal(str)

class MoonDesktopWidget(QWidget):
    def __init__(self, config):
        super().__init__()
        self.config = config
        self.api_key = config.get("api_key", "")
        saved_vp = config.get("voice_profile", "gemini_leda")
        if saved_vp not in VOICE_PROFILES:
            saved_vp = "gemini_leda"
        self.voice_profile = saved_vp
        self.show_subtitles = config.get("show_subtitles", True)
        self.wake_word_only = config.get("wake_word_only", True)
        self.proactive_mode = config.get("proactive_mode", False)  # OFF by default so she never talks randomly unless enabled!
        self.save_gemini_for_voice = config.get("save_gemini_for_voice", False)
        self.mic_device_index = config.get("mic_device_index", None)

        self.chat_history = []
        self.pixmap_cache = {}
        self.speech_lock = threading.Lock()

        self.signals = MoonSignals()
        self.signals.set_emotion.connect(self.update_sprite)
        self.signals.show_bubble.connect(self.display_speech_bubble)
        self.signals.set_status.connect(self.update_status_pill)
        self.signals.start_lipsync.connect(self.begin_lipsync)
        self.signals.stop_lipsync.connect(self.end_lipsync)

        self.current_emotion = "idle"
        self.lip_frame = 0
        self.voice_enabled = True
        self.is_speaking = False
        self.is_processing = False
        self.is_listening_active = False
        self.force_listen_now = False
        self.finish_listen_now = False
        self.restart_mic_flag = False
        self.mic_thread_alive = False
        self.last_interaction_time = time.time()
        self.active_convo_until = 0.0
        self.breath_phase = 0.0
        self.base_sprite_y = 65

        self.press_global_pos = QPoint()
        self.window_start_pos = QPoint()
        self.is_dragging = False

        self.preload_sprite_cache()
        self.init_ui()

        threading.Thread(target=scan_all_installed_pc_apps, daemon=True).start()

        self.lip_timer = QTimer(self)
        self.lip_timer.timeout.connect(self.animate_mouth)

        self.breath_timer = QTimer(self)
        self.breath_timer.timeout.connect(self.animate_breathing)
        self.breath_timer.start(50)

        self.proactive_timer = QTimer(self)
        self.proactive_timer.timeout.connect(self.check_proactive_life)
        self.proactive_timer.start(60000)
        self.next_proactive_delay = random.uniform(240.0, 360.0)

        self.health_timer = QTimer(self)
        self.health_timer.timeout.connect(self.check_pc_health_and_trim_ram)
        self.health_timer.start(60000)

        if MIC_AVAILABLE:
            self.start_mic_thread()

    def start_mic_thread(self):
        if self.mic_thread_alive:
            return
        self.mic_thread_alive = True
        self.mic_thread = threading.Thread(target=self.voice_listen_loop, daemon=True)
        self.mic_thread.start()

    def default_mic_label(self):
        if not self.voice_enabled:
            return "🔇 Mic Muted"
        return "🟢 Say 'Hello Moon'" if self.wake_word_only else "🟢 Mic Ready"

    def trigger_camera_look_followup(self, prompt_text):
        threading.Thread(target=self.process_user_input, args=(prompt_text, False, True, None), daemon=True).start()

    def check_proactive_life(self):
        if not self.proactive_mode or self.is_speaking or self.is_processing or self.is_listening_active:
            return
        idle_secs = time.time() - self.last_interaction_time
        if idle_secs < self.next_proactive_delay:
            return

        self.last_interaction_time = time.time()
        self.next_proactive_delay = random.uniform(240.0, 400.0)
        use_camera_peek = (random.random() < 0.35)
        threading.Thread(target=self.run_proactive_action, args=(use_camera_peek,), daemon=True).start()

    def run_proactive_action(self, use_camera_peek=False):
        if self.is_speaking or self.is_processing:
            return
        self.is_processing = True
        try:
            active_win = get_active_window_title()
            cam_img = None
            if use_camera_peek:
                self.signals.set_emotion.emit("thinking")
                self.signals.set_status.emit("📷 Moon is peeking at you...")
                cam_img = capture_webcam()

            self.config["api_key"] = self.api_key
            data = generate_proactive_interaction(self.config, self.chat_history, active_win, cam_img)
            emotion = data.get("emotion", "happy")
            voice_text = data.get("voice_text") or data.get("display_text")
            roman_text = data.get("roman_text") or voice_text
            display_text = data.get("display_text") or voice_text
            if voice_text:
                self.speak_text(voice_text, roman_text, display_text, emotion)
                self.active_convo_until = time.time() + 15.0
        except Exception as e:
            print(f"[Proactive Notice]: {e}")
        finally:
            self.is_processing = False
            self.last_interaction_time = time.time()

    def preload_sprite_cache(self):
        emotions = ["idle", "talking_1", "talking_2", "happy", "excited", "shy", "angry", "sad", "thinking", "listening", "hanging"]
        for em in emotions:
            path = os.path.join(ASSETS_DIR, f"{em}.png")
            if os.path.exists(path):
                self.pixmap_cache[em] = QPixmap(path).scaled(250, 305, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        trim_own_memory()

    def init_ui(self):
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(290, 385)

        self.bubble = QLabel("", self)
        self.bubble.setWordWrap(True)
        self.bubble.setAlignment(Qt.AlignCenter)
        self.bubble.setFont(QFont("Segoe UI", 9, QFont.Bold))
        self.bubble.setStyleSheet("""
            QLabel {
                background-color: rgba(18, 16, 30, 225);
                color: #F8F4FF;
                border: 1.5px solid rgba(168, 130, 255, 205);
                border-radius: 13px;
                padding: 6px 10px;
            }
        """)
        self.bubble.setGeometry(10, 2, 270, 58)
        self.bubble.hide()

        self.sprite_label = QLabel(self)
        self.sprite_label.setGeometry(20, self.base_sprite_y, 250, 305)
        self.update_sprite("idle")

        self.status_pill = QLabel(self.default_mic_label(), self)
        self.status_pill.setAlignment(Qt.AlignCenter)
        self.status_pill.setFont(QFont("Segoe UI", 8, QFont.Bold))
        self.status_pill.setStyleSheet("""
            QLabel {
                background-color: rgba(20, 18, 34, 220);
                color: #D2C4FF;
                border: 1px solid rgba(155, 120, 255, 175);
                border-radius: 9px;
                padding: 2px 8px;
            }
        """)
        self.status_pill.setGeometry(25, 355, 240, 22)
        self.status_pill.show()

        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.width() - 300, screen.height() - 385)
        self.show()

    def save_config(self):
        self.config["api_key"] = self.api_key
        self.config["voice_profile"] = self.voice_profile
        self.config["show_subtitles"] = self.show_subtitles
        self.config["wake_word_only"] = self.wake_word_only
        self.config["proactive_mode"] = self.proactive_mode
        self.config["save_gemini_for_voice"] = self.save_gemini_for_voice
        self.config["mic_device_index"] = self.mic_device_index
        save_config_file(self.config)

    def animate_breathing(self):
        if self.current_emotion == "hanging" or self.is_dragging:
            self.sprite_label.move(20, self.base_sprite_y)
            return
        self.breath_phase += 0.12
        offset_y = int(math.sin(self.breath_phase) * 3.0)
        self.sprite_label.move(20, self.base_sprite_y + offset_y)

    def update_status_pill(self, text):
        if not text:
            self.status_pill.hide()
        else:
            self.status_pill.setText(text)
            self.status_pill.show()

    def update_sprite(self, emotion):
        self.current_emotion = emotion
        pix = self.pixmap_cache.get(emotion) or self.pixmap_cache.get("idle")
        if pix:
            self.sprite_label.setPixmap(pix)

    def display_speech_bubble(self, text, duration_ms=5500):
        if not self.show_subtitles or not text:
            self.bubble.hide()
            return
        self.bubble.setText(text)
        self.bubble.show()
        QTimer.singleShot(duration_ms, self.bubble.hide)

    def begin_lipsync(self):
        self.lip_timer.start(115)

    def end_lipsync(self, final_emotion):
        self.lip_timer.stop()
        self.update_sprite(final_emotion)
        QTimer.singleShot(3000, lambda: self.update_sprite("idle") if self.current_emotion != "hanging" else None)

    def animate_mouth(self):
        frames = ["talking_1", "talking_2", "idle", "talking_1"]
        self.lip_frame = (self.lip_frame + 1) % len(frames)
        pix = self.pixmap_cache.get(frames[self.lip_frame])
        if pix:
            self.sprite_label.setPixmap(pix)

    def trigger_instant_listen(self):
        if self.is_speaking or self.is_processing:
            return
        if self.is_listening_active:
            self.finish_listen_now = True
        else:
            self.force_listen_now = True
            self.update_sprite("listening")
            self.update_status_pill("👂 बोलिए, मैं सुन रही हूँ...")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.press_global_pos = event.globalPos()
            self.window_start_pos = self.pos()
            self.is_dragging = False

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            dist = (event.globalPos() - self.press_global_pos).manhattanLength()
            if dist > 10:
                self.is_dragging = True
                delta = event.globalPos() - self.press_global_pos
                self.move(self.window_start_pos + delta)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self.is_dragging:
                self.is_dragging = False
                screen = QApplication.primaryScreen().availableGeometry()
                if self.y() > screen.height() - 415:
                    self.move(self.x(), screen.height() - 380)
                    self.update_sprite("hanging")
                elif self.y() < 25:
                    self.move(self.x(), 0)
                    self.update_sprite("hanging")
                else:
                    if self.current_emotion == "hanging":
                        self.update_sprite("idle")
            else:
                self.trigger_instant_listen()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.is_dragging = False
            self.trigger_instant_listen()

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background-color: #1A1726; color: #F2ECFF; border: 1px solid #7C5CFF; border-radius: 8px; padding: 4px; }
            QMenu::item { padding: 6px 20px; border-radius: 4px; }
            QMenu::item:selected { background-color: #6B4CE6; color: white; }
        """)

        act_talk = menu.addAction("🎙️ Speak to Moon Now (Or Click Her!)")
        act_type = menu.addAction("⌨️ Type Multi-Task Command...")
        act_ram = menu.addAction("🧹 Real System RAM & Temp Cleaner")
        menu.addSeparator()

        act_screen = menu.addAction("🖥️ Analyze My Screen / Fix Code Error")
        act_cam = menu.addAction("📷 Open Camera & Look at Me Now")
        act_proactive_now = menu.addAction("✨ Trigger Proactive Camera Peek Now!")
        act_clip = menu.addAction("📋 Explain / Fix Copied Clipboard Text")
        menu.addSeparator()

        voice_menu = menu.addMenu("🎀 Choose Moon's Natural Anime Voice (Multi-Key Gemini HD)")
        voice_group = QActionGroup(self)
        voice_actions = {}
        for v_key, v_info in VOICE_PROFILES.items():
            act = voice_menu.addAction(v_info["label"])
            act.setCheckable(True)
            if v_key == self.voice_profile:
                act.setChecked(True)
            voice_group.addAction(act)
            voice_actions[act] = v_key

        mic_menu = menu.addMenu("🎙️ Select Microphone Device")
        mic_group = QActionGroup(self)
        mic_actions = {}
        act_default_mic = mic_menu.addAction("✨ Windows Default Microphone")
        act_default_mic.setCheckable(True)
        if self.mic_device_index is None:
            act_default_mic.setChecked(True)
        mic_group.addAction(act_default_mic)
        mic_actions[act_default_mic] = None

        for dev_idx, dev_name in get_working_input_devices():
            m_act = mic_menu.addAction(f"🎤 [{dev_idx}] {dev_name[:38]}")
            m_act.setCheckable(True)
            if self.mic_device_index == dev_idx:
                m_act.setChecked(True)
            mic_group.addAction(m_act)
            mic_actions[m_act] = dev_idx

        expr_menu = menu.addMenu("🎭 Preview Moon's Expressions")
        expr_actions = {}
        for em_name in ["happy", "excited", "shy", "angry", "sad", "thinking", "listening", "hanging", "idle"]:
            ea = expr_menu.addAction(f"✨ {em_name.title()}")
            expr_actions[ea] = em_name

        act_wake = menu.addAction(f"🗣️ Wake-Word ('Hello Moon' / 'Suno Moon' Only): {'ON' if self.wake_word_only else 'OFF'}")
        act_proactive = menu.addAction(f"💖 Autonomous Talk & Camera Peek (Every 5m): {'ON' if self.proactive_mode else 'OFF'}")
        act_sub = menu.addAction(f"💬 Subtitles Bubble: {'ON' if self.show_subtitles else 'OFF'}")
        act_mic = menu.addAction(f"🎧 Microphone Listening: {'ON (Unmuted)' if self.voice_enabled else 'OFF (Muted)'}")
        act_key = menu.addAction("🔑 Add/Update Multiple Gemini API Keys (Comma Separated)")
        menu.addSeparator()
        act_quit = menu.addAction("💤 Put Moon to Sleep (Exit)")

        chosen = menu.exec_(self.mapToGlobal(event.pos()))
        if not chosen:
            return
        if chosen in voice_actions:
            self.voice_profile = voice_actions[chosen]
            self.save_config()
            threading.Thread(
                target=self.speak_text,
                args=(
                    "हेहे बॉस! मेरी ये वाली आवाज़ आपको कैसी लग रही है?",
                    "Hehe boss! Meri ye waali aawaaz aapko kaisi lag rahi hai?",
                    "मेरी ये वाली आवाज़ कैसी लगी? 💖",
                    "shy"
                ),
                daemon=True
            ).start()
        elif chosen in mic_actions:
            self.mic_device_index = mic_actions[chosen]
            self.save_config()
            self.restart_mic_flag = True
            self.update_status_pill("🔄 Switching Mic...")
        elif chosen in expr_actions:
            self.update_sprite(expr_actions[chosen])
        elif chosen == act_wake:
            self.wake_word_only = not self.wake_word_only
            self.save_config()
            self.update_status_pill(self.default_mic_label())
        elif chosen == act_proactive:
            self.proactive_mode = not self.proactive_mode
            self.save_config()
        elif chosen == act_proactive_now:
            threading.Thread(target=self.run_proactive_action, args=(True,), daemon=True).start()
        elif chosen == act_ram:
            def run_clean():
                freed_mb, ram_pct, proc_cnt, _ = real_system_ram_cleaner()
                self.speak_text(
                    f"अरे वाह! मैंने {proc_cnt} apps की मेमोरी साफ़ कर दी है और {freed_mb} MB RAM फ्री हो गई है!",
                    f"Are waah! Maine {proc_cnt} apps ki memory saaf kar di hai aur {freed_mb} MB RAM free ho gayi hai!",
                    f"🧹 Trimmed {proc_cnt} apps | Freed {freed_mb} MB | RAM: {ram_pct}%",
                    "excited"
                )
            threading.Thread(target=run_clean, daemon=True).start()
        elif chosen == act_talk:
            self.trigger_instant_listen()
        elif chosen == act_type:
            cmd, ok = QInputDialog.getText(self, "Ask Moon Agent", "Tell Moon any single or multi-step task:")
            if ok and cmd.strip():
                threading.Thread(target=self.process_user_input, args=(cmd.strip(), False, False, None), daemon=True).start()
        elif chosen == act_screen:
            threading.Thread(target=self.process_user_input, args=("मेरी स्क्रीन देखो और बताओ क्या चल रहा है, अगर कोई कोडिंग एरर है तो ठीक कर दो!", True, False, None), daemon=True).start()
        elif chosen == act_cam:
            threading.Thread(target=self.process_user_input, args=("कैमरे से मुझे देखो और बताओ मैं क्या कर रहा हूँ या मेरे हाथ में क्या है?", False, True, None), daemon=True).start()
        elif chosen == act_clip:
            clip_text = QApplication.clipboard().text().strip()
            if clip_text:
                threading.Thread(target=self.process_user_input, args=(f"मैंने ये टेक्स्ट कॉपी किया है, इसे समझाओ या ठीक करो:\n{clip_text[:1500]}", False, False, None), daemon=True).start()
        elif chosen == act_sub:
            self.show_subtitles = not self.show_subtitles
            self.save_config()
            if not self.show_subtitles:
                self.bubble.hide()
        elif chosen == act_mic:
            self.voice_enabled = not self.voice_enabled
            self.update_status_pill(self.default_mic_label())
        elif chosen == act_key:
            new_key, ok = QInputDialog.getText(
                self,
                "Multiple Gemini API Keys Setup",
                "Paste multiple Gemini API Keys separated by comma (key1, key2, key3):",
                text=self.api_key
            )
            if ok:
                self.api_key = new_key.strip()
                MODEL_COOLDOWN.clear()
                KEY_COOLDOWN.clear()
                TTS_COOLDOWN.clear()
                self.save_config()
        elif chosen == act_quit:
            QApplication.quit()

    def check_pc_health_and_trim_ram(self):
        trim_own_memory()
        if psutil.virtual_memory().percent > 88:
            real_system_ram_cleaner()

    def speak_text(self, voice_text, roman_text=None, display_text=None, emotion="happy"):
        with self.speech_lock:
            self.is_speaking = True
            self.last_interaction_time = time.time()
            if display_text is None:
                display_text = voice_text
            if roman_text is None:
                roman_text = voice_text

            self.signals.set_status.emit("🔊 Preparing Voice...")
            audio_file = None
            try:
                prof = VOICE_PROFILES.get(self.voice_profile, VOICE_PROFILES["gemini_leda"])
                vtype = prof.get("type", "gemini_tts")

                if vtype == "gemini_tts":
                    audio_file = generate_gemini_hd_tts_multi_key(
                        self.api_key, voice_text, prof["voice"], emotion
                    )
                    if not audio_file or not os.path.exists(audio_file):
                        fb_txt = roman_text if prof.get("fallback_script") == "roman" else voice_text
                        audio_file = generate_edge_anime_tts_cached(
                            fb_txt,
                            prof["fallback_voice"],
                            prof["fallback_pitch"],
                            prof["fallback_rate"]
                        )
                else:
                    tts_in = roman_text if prof.get("script") == "roman" else voice_text
                    audio_file = generate_edge_anime_tts_cached(
                        tts_in, prof["voice"], prof["pitch"], prof["rate"]
                    )

                self.signals.set_status.emit("🔊 Speaking...")
                self.signals.set_emotion.emit(emotion)
                self.signals.show_bubble.emit(display_text, max(len(display_text) * 95, 4500))
                self.signals.start_lipsync.emit()

                if audio_file and os.path.exists(audio_file):
                    play_audio_windows(audio_file, max_wait_seconds=20.0)
                time.sleep(0.1)
            except Exception as e:
                print(f"[TTS Error]: {e}")
                self.signals.show_bubble.emit(display_text, 4500)
            finally:
                self.is_speaking = False
                self.last_interaction_time = time.time()
                self.signals.set_status.emit(self.default_mic_label())
                self.signals.stop_lipsync.emit(emotion)
                trim_own_memory()

    # =====================================================================
    # SINGLE-THREAD ROCK-SOLID VOICE LISTENER (Zero Noise Hallucinations!)
    # =====================================================================
    def voice_listen_loop(self):
        recognizer = sr.Recognizer()
        sample_rate = 16000
        chunk_duration = 0.10
        chunk_samples = int(sample_rate * chunk_duration)

        while True:
            self.restart_mic_flag = False

            noise_floor = 15.0
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
                        cal_vals.append(compute_speech_formant_rms(data, sample_rate))
                    noise_floor = max(min(float(np.median(cal_vals)), 300.0), 5.0)
            except Exception as e:
                print(f"[Mic Open Warning]: {e}")
                if self.mic_device_index is not None:
                    self.mic_device_index = None
                self.signals.set_status.emit("⚠️ Check Mic Device")
                time.sleep(1.5)
                continue

            self.signals.set_status.emit(self.default_mic_label())
            print(f"[Moon Mic v17] Calibrated! Room Noise Floor={noise_floor:.1f}")

            while not self.restart_mic_flag:
                if self.is_speaking or self.is_processing or (not self.voice_enabled and not self.force_listen_now):
                    time.sleep(0.08)
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
                        pre_buffer = deque(maxlen=7)  # 0.7s pre-buffer so first word is never missed
                        recording = False
                        silence_chunks = 0
                        speech_chunks = 0
                        max_speech_chunks = int(5.0 / chunk_duration)
                        ui_tick = 0

                        while not self.is_speaking and not self.is_processing and not self.restart_mic_flag:
                            if not self.voice_enabled and not self.force_listen_now and not recording:
                                break

                            data, _ = stream.read(chunk_samples)
                            vol = compute_speech_formant_rms(data, sample_rate)

                            start_threshold = max(noise_floor * 1.85 + 12.0, 18.0)
                            keep_threshold = max(noise_floor * 1.35 + 6.0, 12.0)

                            ui_tick += 1
                            if not recording and ui_tick % 5 == 0:
                                bar = volume_bar_string(vol, start_threshold)
                                prefix = "🟢 'Hello Moon'" if self.wake_word_only else "🟢 Mic"
                                self.signals.set_status.emit(f"{prefix} {bar}")

                            if not recording:
                                pre_buffer.append(data.copy())
                                if self.force_listen_now:
                                    recording = True
                                    was_clicked = True
                                    has_spoken = True
                                    self.is_listening_active = True
                                    self.force_listen_now = False
                                    self.finish_listen_now = False
                                    silence_chunks = 0
                                    speech_chunks = 3
                                    captured_frames.extend(pre_buffer)
                                    self.signals.set_emotion.emit("listening")
                                    self.signals.set_status.emit("👂 बोलिए, सुन रही हूँ...")
                                elif vol > start_threshold:
                                    recording = True
                                    was_clicked = False
                                    has_spoken = True
                                    self.is_listening_active = True
                                    self.finish_listen_now = False
                                    silence_chunks = 0
                                    speech_chunks = 1
                                    captured_frames.extend(pre_buffer)
                                    self.signals.set_emotion.emit("listening")
                                    self.signals.set_status.emit("👂 सुन रही हूँ...")
                                else:
                                    if vol > 0.0:
                                        noise_floor = min(max(noise_floor * 0.92 + vol * 0.08, 5.0), 350.0)
                            else:
                                captured_frames.append(data.copy())
                                if vol > keep_threshold:
                                    silence_chunks = 0
                                    speech_chunks += 1
                                else:
                                    silence_chunks += 1

                                min_chunks = 15 if was_clicked else 8
                                # 7 chunks = 0.70s natural pause after finishing your full sentence!
                                if (len(captured_frames) >= min_chunks and silence_chunks >= 7) or len(captured_frames) >= max_speech_chunks or self.finish_listen_now:
                                    if len(captured_frames) >= max_speech_chunks:
                                        noise_floor = min(max(noise_floor * 1.35, vol * 0.9), 380.0)
                                    self.is_listening_active = False
                                    self.finish_listen_now = False
                                    break

                    if (has_spoken and speech_chunks >= 3) or (was_clicked and len(captured_frames) >= 6):
                        self.is_processing = True
                        self.signals.set_status.emit("🔍 Checking Speech...")

                        raw_audio_np = np.concatenate(captured_frames, axis=0)
                        clean_int16, _ = normalize_and_clean_wav_bytes(raw_audio_np, sample_rate)
                        user_text = recognize_bilingual_fast(recognizer, clean_int16, sample_rate)

                        if user_text:
                            print(f"🎙️ [Heard]: '{user_text}'")
                            in_active_convo = (time.time() < self.active_convo_until)
                            has_wake, cleaned_cmd = check_and_strip_wake_word(user_text)

                            if not self.wake_word_only or was_clicked or has_wake or in_active_convo:
                                final_cmd = cleaned_cmd if has_wake else user_text
                                short_preview = final_cmd[:22] + ("..." if len(final_cmd) > 22 else "")
                                self.signals.set_status.emit(f"🗣️ \"{short_preview}\"")
                                self.process_user_input(final_cmd, False, False, None)
                                self.active_convo_until = time.time() + 18.0
                            else:
                                print(f"🔇 [Ignored (Say 'Moon' to talk)]: '{user_text}'")
                                self.signals.set_emotion.emit("idle")
                                self.signals.set_status.emit(self.default_mic_label())
                        else:
                            # If no intelligible words were recognized, it was just background noise!
                            # NEVER send raw noise to Gemini (prevents hallucinated self-talking & saves 100% quota!)
                            if was_clicked:
                                self.speak_text(
                                    "अरे बॉस, आपकी आवाज़ साफ़ नहीं आई, थोड़ा पास से बोलिए ना!",
                                    "Are boss, aapki aawaaz saaf nahi aayi, thoda paas se boliye na!",
                                    "🎙️ फिर से बोलिए!",
                                    "shy"
                                )
                            else:
                                self.signals.set_emotion.emit("idle")
                                self.signals.set_status.emit(self.default_mic_label())

                        self.is_processing = False
                    else:
                        self.is_listening_active = False
                        if self.current_emotion == "listening":
                            self.signals.set_emotion.emit("idle")
                        self.signals.set_status.emit(self.default_mic_label())

                except Exception as e:
                    self.is_listening_active = False
                    self.is_processing = False
                    print(f"[Mic Loop Notice]: {e}")
                    time.sleep(0.3)

    def process_user_input(self, user_text, force_screen=False, force_cam=False, wav_bytes=None):
        self.is_processing = True
        self.last_interaction_time = time.time()
        self.signals.set_emotion.emit("thinking")
        self.signals.set_status.emit("💭 Moon is Thinking...")

        images = []
        auto_cam = needs_webcam_vision(user_text)
        auto_screen = needs_screen_vision(user_text)

        try:
            if force_cam or auto_cam:
                self.signals.set_status.emit("📷 Opening Camera & Looking...")
                cam_img = capture_webcam()
                if cam_img:
                    images.append(cam_img)
                    user_text = f"[Webcam Photo Attached - Look at this photo to answer]: {user_text}"

            if force_screen or auto_screen:
                self.signals.set_status.emit("🖥️ Reading Screen...")
                images.append(capture_desktop_screen())

            self.config["api_key"] = self.api_key
            self.config["save_gemini_for_voice"] = self.save_gemini_for_voice
            data, provider_used = call_resilient_multi_brain(
                self.config, self.chat_history, user_text, images, None
            )
            print(f"🧠 [Brain Provider]: {provider_used}")

            emotion = data.get("emotion", "happy")
            voice_text = data.get("voice_text") or data.get("display_text") or "अरे वाह बॉस, अभी करती हूँ!"
            roman_text = data.get("roman_text") or voice_text
            display_text = data.get("display_text") or voice_text
            steps = data.get("steps", [])

            if steps and isinstance(steps, list):
                threading.Thread(
                    target=execute_agent_steps_with_verification,
                    args=(steps, self.signals.set_status, self),
                    daemon=True
                ).start()

            self.speak_text(voice_text, roman_text, display_text, emotion)
        except Exception as e:
            print(f"[Process Error]: {e}")
        finally:
            self.is_processing = False
            self.last_interaction_time = time.time()

def main():
    app = QApplication(sys.argv)

    default_img = "Suzune  Horikita.jpg"
    if not os.path.exists(SPRITE_VERSION_FILE):
        if not os.path.exists(default_img):
            candidates = [f for f in os.listdir(".") if f.lower().endswith((".jpg", ".jpeg", ".png"))]
            if candidates:
                default_img = candidates[0]
            else:
                QMessageBox.information(None, "Select Moon's Image", "Please select your character image!")
                default_img, _ = QFileDialog.getOpenFileName(None, "Select Character Image", "", "Images (*.jpg *.jpeg *.png)")
                if not default_img:
                    sys.exit(0)
        build_sprites_if_needed(default_img)

    config = load_config()
    if not config.get("api_key"):
        api_key, ok = QInputDialog.getText(
            None,
            "Moon AI Setup — Multiple Gemini API Keys",
            "Paste 1 or more Gemini API Keys separated by comma (key1, key2, key3):"
        )
        config["api_key"] = api_key.strip() if ok and api_key else ""
        save_config_file(config)

    moon = MoonDesktopWidget(config)
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()