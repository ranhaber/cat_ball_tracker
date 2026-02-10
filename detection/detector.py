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
        
        self._ensure_model_exists()
        # Don't load model at startup — TFLite worker threads busy-wait (spin)
        # even when idle, wasting ~100% of one CPU core.
        # Model is loaded on motion detection and unloaded when idle.
        print("TFLite model ready (will load on first motion detection)")
        
    def _ensure_model_exists(self):
        """Download model if not present"""
        os.makedirs(config.MODELS_DIR, exist_ok=True)
        model_path = os.path.join(config.MODELS_DIR, config.MODEL_FILENAME)
        
        if not os.path.exists(model_path):
            print("Downloading TFLite model...")
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
            print("Model downloaded successfully")
            
        except Exception as e:
            print(f"Error downloading model: {e}")
            print("Please download manually from:", config.MODEL_URL)
            
    def _load_model(self):
        """Load the TFLite model"""
        if not TFLITE_AVAILABLE:
            print("TFLite not available - using mock detections")
            return
            
        model_path = os.path.join(config.MODELS_DIR, config.MODEL_FILENAME)
        
        if not os.path.exists(model_path):
            print(f"Model file not found: {model_path}")
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
            
            print(f"Model loaded. Input shape: {self.input_shape}")
            
        except Exception as e:
            print(f"Error loading model: {e}")
            self.interpreter = None
            
    def unload_model(self):
        """Unload the TFLite model to free CPU (stops spin-wait worker threads).
        Model will be reloaded automatically on next detect() call."""
        if self.interpreter is not None:
            self.interpreter = None
            self.input_details = None
            self.output_details = None
            print("[DETECTOR] Model unloaded (TFLite threads stopped)")
    
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
            print(f"Detection mode set to: {mode} (class ID: {self.target_class_id})")
        else:
            print(f"Invalid mode: {mode}. Valid modes: {list(config.COCO_CLASSES.keys())}")
            
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
        print(f"Detection threshold set to: {threshold}")
    
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
        # Load model on demand (avoids TFLite spin-wait threads when idle)
        if self.interpreter is None:
            self._load_model()
        
        if self.interpreter is None:
            return self._mock_detect(frame)
            
        # Get frame dimensions
        frame_h, frame_w = frame.shape[:2]
        
        # Resize and convert BGR→RGB directly into pre-allocated buffer
        resized = cv2.resize(frame, (self.input_w, self.input_h))
        cv2.cvtColor(resized, cv2.COLOR_BGR2RGB, dst=self._input_buf[0])
        
        # Run inference (input buffer already has batch dimension)
        self.interpreter.set_tensor(self.input_details[0]['index'], self._input_buf)
        self.interpreter.invoke()
        
        # Get outputs
        # Output format: boxes, classes, scores, num_detections
        boxes = self.interpreter.get_tensor(self.output_details[0]['index'])[0]
        classes = self.interpreter.get_tensor(self.output_details[1]['index'])[0]
        scores = self.interpreter.get_tensor(self.output_details[2]['index'])[0]
        
        # Filter detections (no debug allocs in hot path)
        detections = []
        
        for i in range(len(scores)):
            score = float(scores[i])
            if score < self.threshold:
                continue
            
            class_id = int(classes[i]) + 1  # COCO classes are 1-indexed in labels
            if class_id != self.target_class_id:
                continue
                
            # Convert normalized coordinates to pixel coordinates
            y1, x1, y2, x2 = boxes[i]
            x1 = max(0, min(int(x1 * frame_w), frame_w))
            y1 = max(0, min(int(y1 * frame_h), frame_h))
            x2 = max(0, min(int(x2 * frame_w), frame_w))
            y2 = max(0, min(int(y2 * frame_h), frame_h))
            
            detections.append((x1, y1, x2, y2, score, class_id))
            
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
