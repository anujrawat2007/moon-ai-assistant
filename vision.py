import io
import os
import cv2
import mss
import numpy as np
from PIL import Image

def capture_screen_fast(max_size: tuple[int, int] = (1280, 720), quality: int = 75) -> bytes:
    """
    Ultra-fast desktop / VS Code screen capture using MSS.
    Resizes and compresses to JPEG bytes for instant API analysis.
    """
    with mss.mss() as sct:
        # Capture primary monitor
        monitor = sct.monitors[1]
        sct_img = sct.grab(monitor)
        
        # Convert to PIL Image
        img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
        img.thumbnail(max_size, Image.Resampling.LANCZOS)
        
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=quality)
        return buffer.getvalue()

def capture_webcam_frame(camera_index: int = 0, max_size: tuple[int, int] = (640, 480)) -> bytes | None:
    """
    Captures a single crisp snapshot from the user's webcam using OpenCV.
    Returns JPEG bytes or None if camera is unavailable/busy.
    """
    cap = None
    try:
        cap = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW) # DirectShow for fast startup on Windows
        if not cap.isOpened():
            cap = cv2.VideoCapture(camera_index)
        
        if not cap.isOpened():
            print("[Vision] Cannot access webcam.")
            return None

        ret, frame = cap.read()
        if not ret or frame is None:
            print("[Vision] Failed to read webcam frame.")
            return None

        # Resize to save bandwidth & memory
        frame_resized = cv2.resize(frame, max_size)
        _, buffer = cv2.imencode(".jpg", frame_resized, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        return buffer.tobytes()
    except Exception as e:
        print(f"[Vision Error] Webcam capture failed: {e}")
        return None
    finally:
        if cap is not None:
            cap.release()

if __name__ == "__main__":
    print("Testing Vision Module...")
    screen_data = capture_screen_fast()
    print(f"Screen captured successfully: {len(screen_data)} bytes (~{len(screen_data)//1024} KB)")
    
    print("Testing webcam snapshot...")
    cam_data = capture_webcam_frame()
    if cam_data:
        print(f"Webcam captured successfully: {len(cam_data)} bytes (~{len(cam_data)//1024} KB)")
    else:
        print("Webcam not connected or in use.")

