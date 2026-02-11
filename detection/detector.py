"""
TensorFlow Lite Object Detector
Uses MobileNet SSD for lightweight detection on RPi Zero 2W
"""

import os
import zipfile
import urllib.request
import numpy as np
import cv2

try:
    import tflite_runtime.interpreter as tflite
    TFLITE_AVAILABLE = True
except ImportError:
    TFLITE_AVAILABLE = False
    print("Warning: tflite_runtime not available. Detection will be mocked.")

import config

try:
    from processing.async_log import log as plog
except ImportError:
    plog = lambda msg, *a, **k: print(msg % a if a else msg)


class TFLiteDetector:
    """
    TensorFlow Lite detector using MobileNet SSD.
    Optimized for RPi Zero 2W with quantized model.
    """
    
    def __init__(self, threshold=None, num_threads=None):
        """
        Initialize the TFLite detector.
        
        Args:
            threshold: Detection confidence threshold (default from config)
            num_threads: Number of inference threads (default from config)
        """
        self.threshold = threshold or config.DETECTION_THRESHOLD
        self.num_threads = num_threads or config.TFLITE_NUM_THREADS
        
        self.interpreter = None
        self.input_details = None
        self.output_details = None
        self.input_shape = None
        
        # OPTIMIZATION I: Pre-compute static values
        self.input_h = None
        self.input_w = None
        
        self.detection_mode = config.DEFAULT_DETECTION_MODE
        self.target_class_id = config.COCO_CLASSES[self.detection_mode]
        self._last_perf = None  # Timing breakdown from last detect() call
        
        self._ensure_model_exists()
        # Don't keep model loaded at startup — TFLite worker threads busy-wait
        # (spin) even when idle, wasting ~100% of one CPU core.
        # Model is loaded on demand and unloaded after 10s idle.
        plog("TFLite model ready (will load on first motion detection)")
        self._warmup_file_cache()
        
    def _ensure_model_exists(self):
        """Download model if not present"""
        os.makedirs(config.MODELS_DIR, exist_ok=True)
        model_path = os.path.join(config.MODELS_DIR, config.MODEL_FILENAME)
        
        if not os.path.exists(model_path):
            plog("Downloading TFLite model...")
            self._download_model()
            
    def _download_model(self):
        """Download and extract the COCO SSD MobileNet model"""
        zip_path = os.path.join(config.MODELS_DIR, "model.zip")
        
        try:
            # Download
            urllib.request.urlretrieve(config.MODEL_URL, zip_path)
            
            # Extract
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(config.MODELS_DIR)
                
            # Cleanup
            os.remove(zip_path)
            plog("Model downloaded successfully")
            
        except Exception as e:
            plog("Error downloading model: %s", e)
            plog("Please download manually from: %s", config.MODEL_URL)
            
    def _load_model(self):
        """Load the TFLite model"""
        if not TFLITE_AVAILABLE:
            plog("TFLite not available - using mock detections")
            return
            
        model_path = os.path.join(config.MODELS_DIR, config.MODEL_FILENAME)
        
        if not os.path.exists(model_path):
            plog("Model file not found: %s", model_path)
            return
            
        try:
            # Create interpreter with optimized settings for RPi Zero 2W
            self.interpreter = tflite.Interpreter(
                model_path=model_path,
                num_threads=self.num_threads
            )
            self.interpreter.allocate_tensors()
            
            # Get input/output details
            self.input_details = self.interpreter.get_input_details()
            self.output_details = self.interpreter.get_output_details()
            
            # Get expected input shape
            self.input_shape = self.input_details[0]['shape']
            
            # OPTIMIZATION I: Pre-compute input dimensions
            self.input_h = self.input_shape[1]
            self.input_w = self.input_shape[2]
            
            # Pre-allocate input buffer (avoids ~540KB alloc per inference)
            self._input_buf = np.empty((1, self.input_h, self.input_w, 3), dtype=np.uint8)
            
            plog("Model loaded. Input shape: %s", self.input_shape)
            
        except Exception as e:
            plog("Error loading model: %s", e)
            self.interpreter = None
            
    def _warmup_file_cache(self):
        """Pre-load model into OS file cache, run one dummy invoke, then unload.
        
        This warms the OS page cache (model file stays in RAM) and triggers
        XNNPACK JIT compilation so subsequent loads are fast (~100-200ms
        instead of ~1200ms). The interpreter is unloaded immediately after
        to avoid the XNNPACK spin-wait CPU burn.
        
        Called once at startup. Adds ~3.5s to boot time but makes the first
        real detection ~6x faster (3.5s -> 0.5s).
        """
        if not TFLITE_AVAILABLE:
            return
        model_path = os.path.join(config.MODELS_DIR, config.MODEL_FILENAME)
        if not os.path.exists(model_path):
            return
        
        import time as _time
        t_total = _time.perf_counter()
        plog("[DETECTOR] Warming file cache (one-time)...")
        
        t0 = _time.perf_counter()
        self._load_model()
        load_ms = round((_time.perf_counter() - t0) * 1000, 1)
        if self.interpreter is None:
            return
        plog("[DETECTOR] Warmup load: %.1fms", load_ms)
        
        # Run one dummy invoke to trigger XNNPACK JIT kernel compilation.
        # Without this, the first real invoke is ~2.3s; with it, ~200-400ms.
        try:
            dummy = np.zeros((1, self.input_h, self.input_w, 3), dtype=np.uint8)
            self.interpreter.set_tensor(self.input_details[0]['index'], dummy)
            t1 = _time.perf_counter()
            self.interpreter.invoke()
            invoke_ms = round((_time.perf_counter() - t1) * 1000, 1)
            plog("[DETECTOR] Warmup invoke: %.1fms", invoke_ms)
        except Exception as e:
            plog("[DETECTOR] Warmup invoke failed: %s", e)
        
        # Unload: kills XNNPACK spin-wait threads, but OS page cache retains
        # the model file in RAM. Next _load_model() reads from RAM (~100ms).
        self.unload_model()
        total_ms = round((_time.perf_counter() - t_total) * 1000, 1)
        plog("[DETECTOR] File cache warm, TFLite unloaded (total %.1fms)", total_ms)
    
    def unload_model(self):
        """Unload the TFLite model to free CPU (stops spin-wait worker threads).
        Model will be reloaded automatically on next detect() call."""
        if self.interpreter is not None:
            self.interpreter = None
            self.input_details = None
            self.output_details = None
            plog("[DETECTOR] Model unloaded (TFLite threads stopped)")
    
    def is_loaded(self):
        """Check if the TFLite model is currently loaded."""
        return self.interpreter is not None
    
    def set_detection_mode(self, mode):
        """
        Set the detection mode.
        
        Args:
            mode: "cat" or "ball"
        """
        if mode in config.COCO_CLASSES:
            self.detection_mode = mode
            self.target_class_id = config.COCO_CLASSES[mode]
            plog("Detection mode set to: %s (class ID: %s)", mode, self.target_class_id)
        else:
            plog("Invalid mode: %s. Valid modes: %s", mode, list(config.COCO_CLASSES.keys()))
            
    def get_detection_mode(self):
        """Get current detection mode"""
        return self.detection_mode
    
    def set_threshold(self, threshold):
        """
        Set the detection confidence threshold.
        
        Args:
            threshold: Value between 0.0 and 1.0
        """
        threshold = max(0.1, min(0.9, float(threshold)))
        self.threshold = threshold
        plog("Detection threshold set to: %s", threshold)
    
    def get_threshold(self):
        """Get current detection threshold"""
        return self.threshold
        
    def detect(self, frame):
        """
        Run detection on a frame.
        
        Args:
            frame: BGR image (numpy array)
            
        Returns:
            List of detections: [(x1, y1, x2, y2, confidence, class_id), ...]
        """
        import time as _time
        # Load model on demand (avoids TFLite spin-wait threads when idle)
        t_load = _time.perf_counter()
        if self.interpreter is None:
            self._load_model()
        load_ms = round((_time.perf_counter() - t_load) * 1000, 1)
        
        if self.interpreter is None:
            return self._mock_detect(frame)
            
        # Get frame dimensions
        frame_h, frame_w = frame.shape[:2]
        
        # Resize + color convert to model input
        t_pre = _time.perf_counter()
        if frame_w == self.input_w and frame_h == self.input_h:
            cv2.cvtColor(frame, cv2.COLOR_BGR2RGB, dst=self._input_buf[0])
        else:
            resized = cv2.resize(frame, (self.input_w, self.input_h))
            cv2.cvtColor(resized, cv2.COLOR_BGR2RGB, dst=self._input_buf[0])
        pre_ms = round((_time.perf_counter() - t_pre) * 1000, 1)
        
        # Run inference
        t_invoke = _time.perf_counter()
        self.interpreter.set_tensor(self.input_details[0]['index'], self._input_buf)
        self.interpreter.invoke()
        invoke_ms = round((_time.perf_counter() - t_invoke) * 1000, 1)
        
        # Get outputs + filter
        t_post = _time.perf_counter()
        boxes = self.interpreter.get_tensor(self.output_details[0]['index'])[0]
        classes = self.interpreter.get_tensor(self.output_details[1]['index'])[0]
        scores = self.interpreter.get_tensor(self.output_details[2]['index'])[0]
        
        detections = []
        
        for i in range(len(scores)):
            score = float(scores[i])
            if score < self.threshold:
                continue
            
            class_id = int(classes[i]) + 1  # COCO classes are 1-indexed in labels
            if class_id != self.target_class_id:
                continue
                
            y1, x1, y2, x2 = boxes[i]
            x1 = max(0, min(int(x1 * frame_w), frame_w))
            y1 = max(0, min(int(y1 * frame_h), frame_h))
            x2 = max(0, min(int(x2 * frame_w), frame_w))
            y2 = max(0, min(int(y2 * frame_h), frame_h))
            
            detections.append((x1, y1, x2, y2, score, class_id))
        post_ms = round((_time.perf_counter() - t_post) * 1000, 1)
        
        # Store last timing breakdown for caller to read
        self._last_perf = {
            "load": load_ms,
            "pre": pre_ms,      # resize + BGR→RGB
            "invoke": invoke_ms, # TFLite invoke
            "post": post_ms      # get_tensor + filter
        }
            
        return detections
        
    def _mock_detect(self, frame):
        """Generate mock detections for testing"""
        import random
        
        # Occasionally return a mock detection
        if random.random() < 0.3:
            h, w = frame.shape[:2]
            cx = random.randint(w // 4, 3 * w // 4)
            cy = random.randint(h // 4, 3 * h // 4)
            size = random.randint(50, 100)
            
            return [(
                cx - size // 2,
                cy - size // 2,
                cx + size // 2,
                cy + size // 2,
                random.uniform(0.6, 0.95),
                self.target_class_id
            )]
        return []
        
    def draw_detections(self, frame, detections, tracked_objects=None):
        """
        Draw detection boxes and labels on frame.
        
        Args:
            frame: BGR image to draw on
            detections: List of (x1, y1, x2, y2, confidence, class_id)
            tracked_objects: Optional dict of {object_id: centroid} for tracking labels
            
        Returns:
            Frame with drawn detections
        """
        # Choose color based on detection mode
        if self.detection_mode == "cat":
            box_color = config.BOX_COLOR_CAT
        else:
            box_color = config.BOX_COLOR_BALL
            
        for det in detections:
            x1, y1, x2, y2, conf, class_id = det
            
            # Draw bounding box
            cv2.rectangle(frame, (x1, y1), (x2, y2), box_color, config.BOX_THICKNESS)
            
            # Prepare label
            class_name = config.CLASS_NAMES.get(class_id, f"Class {class_id}")
            label = f"{class_name}: {conf:.2f}"
            
            # Add tracking ID if available
            if tracked_objects:
                cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
                for obj_id, centroid in tracked_objects.items():
                    if abs(centroid[0] - cx) < 20 and abs(centroid[1] - cy) < 20:
                        label = f"ID:{obj_id} {label}"
                        break
            
            # Draw label background
            (text_w, text_h), _ = cv2.getTextSize(
                label, cv2.FONT_HERSHEY_SIMPLEX, 
                config.FONT_SCALE, config.FONT_THICKNESS
            )
            cv2.rectangle(
                frame, 
                (x1, y1 - text_h - 10), 
                (x1 + text_w + 5, y1),
                config.TEXT_BG_COLOR, 
                -1
            )
            
            # Draw label text
            cv2.putText(
                frame,
                label,
                (x1 + 2, y1 - 5),
                cv2.FONT_HERSHEY_SIMPLEX,
                config.FONT_SCALE,
                config.TEXT_COLOR,
                config.FONT_THICKNESS
            )
            
        return frame
