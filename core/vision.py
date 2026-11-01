import io
import os
from PIL import Image, ImageGrab

def capture_screen_bytes(max_size: tuple[int, int] = (1280, 720)) -> bytes:
    """
    Captures the current desktop screen, resizes to save memory/tokens,
    and returns compressed JPEG bytes.
    """
    screenshot = ImageGrab.grab()
    screenshot.thumbnail(max_size, Image.Resampling.LANCZOS)
    
    buffer = io.BytesIO()
    screenshot.save(buffer, format="JPEG", quality=75)
    return buffer.getvalue()

def capture_webcam_bytes(camera_index: int = 0, max_size: tuple[int, int] = (640, 480)) -> bytes | None:
    """
    Captures a single snapshot frame from the webcam using OpenCV.
    Returns compressed JPEG bytes or None if camera is unavailable.
    """
    try:
        import cv2
        cap = cv2.VideoCapture(camera_index)
        if not cap.isOpened():
            print("[Vision] Could not open webcam.")
            return None
        
        ret, frame = cap.read()
        cap.release()
        
        if not ret:
            print("[Vision] Failed to grab frame from webcam.")
            return None
        
        # Resize to conserve memory
        frame = cv2.resize(frame, max_size)
        _, buffer = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
        return buffer.tobytes()
    except ImportError:
        print("[Vision Notice] OpenCV (cv2) not installed yet. Webcam snapshot requires opencv-python.")
        return None
    except Exception as e:
        print(f"[Vision Error] Error accessing camera: {e}")
        return None

if __name__ == "__main__":
    print("Testing Screen Capture...")
    img_data = capture_screen_bytes()
    print(f"Captured screen size: {len(img_data)} bytes (~{len(img_data)//1024} KB)")
