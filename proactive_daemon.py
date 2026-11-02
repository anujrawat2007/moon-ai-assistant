import time
import threading
import psutil


class ProactiveIdleDaemon:
    """
    Proactive Idle Monitoring Daemon (Screen + Webcam):
    - Resets timer whenever the user speaks or interacts with Moon.
    - When the user is silent for `idle_minutes` (configurable via Control Panel slider, e.g., 1–30 mins):
      1. Silently captures 1 frame from the Screen (`mss`) and 1 frame from the Webcam (`cv2.VideoCapture`,
         releasing the camera hardware immediately so the LED light never stays stuck on).
      2. Sends both frames + active window title + `masti_level` to the Gemini API Pool.
      3. Moon initiates spontaneous, context-aware "masti-khor" Hinglish conversation based on what she sees!
    """

    def __init__(
        self,
        api_pool,
        vision_manager,
        os_executor,
        config,
        is_busy_callback,
        on_proactive_speak_callback,
        log_callback=None
    ):
        self.api_pool = api_pool
        self.vision_manager = vision_manager
        self.os_executor = os_executor
        self.config = config
        self.is_busy_callback = is_busy_callback
        self.on_proactive_speak_callback = on_proactive_speak_callback
        self.log_callback = log_callback

        self.proactive_enabled = bool(config.get("proactive_mode", False))
        self.idle_minutes = float(config.get("proactive_idle_minutes", 5.0))
        self.last_user_activity_time = time.time()
        self._running = True
        self._thread = None

    def _log(self, msg, level="INFO"):
        if self.log_callback:
            try:
                self.log_callback(f"[Proactive][{level}] {msg}")
            except Exception:
                pass

    def reset_idle_timer(self):
        self.last_user_activity_time = time.time()

    def set_proactive_config(self, enabled: bool, idle_minutes: float):
        self.proactive_enabled = bool(enabled)
        self.idle_minutes = max(1.0, float(idle_minutes))
        self.reset_idle_timer()
        self._log(
            f"Proactive Mode set to: {'ON' if self.proactive_enabled else 'OFF'} "
            f"(Idle Trigger = {self.idle_minutes:.1f} mins)"
        )

    def start_daemon(self):
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._daemon_loop, daemon=True, name="MoonProactiveDaemon")
            self._thread.start()
            self._log(
                f"Proactive Idle Daemon started (Enabled={self.proactive_enabled}, Timeout={self.idle_minutes}m)."
            )

    def _daemon_loop(self):
        while self._running:
            time.sleep(5.0)
            if not self.proactive_enabled:
                continue
            if self.is_busy_callback():
                self.reset_idle_timer()
                continue

            idle_elapsed = time.time() - self.last_user_activity_time
            target_seconds = self.idle_minutes * 60.0
            if idle_elapsed >= target_seconds:
                self.reset_idle_timer()
                self.trigger_proactive_check_in(manual_trigger=False)

    def trigger_proactive_check_in(self, manual_trigger=False):
        if self.is_busy_callback() and not manual_trigger:
            return

        threading.Thread(
            target=self._run_check_in_worker,
            args=(manual_trigger,),
            daemon=True,
            name="ProactiveWorker"
        ).start()

    def _run_check_in_worker(self, manual_trigger=False):
        try:
            self._log("Capturing Screen + Webcam frames for Proactive Check-In...")
            active_win = self.os_executor.get_active_window_title()
            ram_pct = int(psutil.virtual_memory().percent)
            masti_level = int(self.config.get("masti_level", 75))

            images = []
            frame_descriptions = []

            screen_img = self.vision_manager.capture_raw_screen(max_size=(1280, 720))
            if screen_img is not None:
                images.append(screen_img)
                frame_descriptions.append("Image 1: User's live Desktop Screen")

            cam_img = self.vision_manager.capture_webcam_frame()
            if cam_img is not None:
                images.append(cam_img)
                frame_descriptions.append(f"Image {len(images)}: User's live Webcam photo")

            attached_info = ", ".join(frame_descriptions) if frame_descriptions else "No images attached (privacy toggles OFF)"

            prompt = (
                f"[PROACTIVE IDLE CHECK-IN]: The user has been quiet for {self.idle_minutes:.0f} minutes. "
                f"Active Window Title: '{active_win}' | PC RAM Usage: {ram_pct}%. "
                f"Attached Visuals: {attached_info}. "
                f"Your Masti/Teasing Level is {masti_level}% (1%=Professional, 100%=Full Savage/Cute Anime Teasing). "
                f"Look closely at what the user is doing on their screen (e.g., coding, syntax error, watching YouTube/Reels, idle) "
                f"and how they look on the webcam (e.g., posture, tired face, looking at phone, smiling). "
                f"Initiate a spontaneous, super lively 1-2 sentence Hinglish conversation based on what you see! "
                f"Set 'tasks' to []."
            )

            parsed, key_used, lat = self.api_pool.generate_multimodal_response(
                user_text=prompt,
                chat_history=None,
                pil_images=images,
                masti_level=masti_level,
                expect_json=True
            )
            self._log(f"Proactive response generated via {key_used} ({lat}ms): {parsed.get('roman_text', '')}")
            self.on_proactive_speak_callback(parsed)

        except Exception as e:
            self._log(f"Proactive check-in skipped/error: {e}", "WARN")