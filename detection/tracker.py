"""
Centroid-based Object Tracker
Lightweight tracking algorithm optimized for RPi Zero 2W
"""

import numpy as np
from collections import OrderedDict
from scipy.spatial import distance as dist

import config


class CentroidTracker:
    """
    Simple centroid-based multi-object tracker.
    
    Tracks objects by associating detections across frames based on
    the distance between centroids. Optimized for low resource usage.
    """
    
    def __init__(self, max_disappeared=None, max_distance=None):
        """
        Initialize the centroid tracker.
        
        Args:
            max_disappeared: Frames before removing lost object (default from config)
            max_distance: Max distance to associate detection (default from config)
        """
        self.max_disappeared = max_disappeared or config.MAX_DISAPPEARED_FRAMES
        self.max_distance = max_distance or config.MAX_TRACKING_DISTANCE
        
        # Object tracking state
        self.next_object_id = 0
        self.objects = OrderedDict()      # {object_id: centroid}
        self.bboxes = OrderedDict()       # {object_id: (x1, y1, x2, y2)}
        self.disappeared = OrderedDict()  # {object_id: frames_disappeared}
        
    def reset(self):
        """Reset all tracking state"""
        self.next_object_id = 0
        self.objects.clear()
        self.bboxes.clear()
        self.disappeared.clear()
        
    def _register(self, centroid, bbox):
        """Register a new object with given centroid and bounding box"""
        self.objects[self.next_object_id] = centroid
        self.bboxes[self.next_object_id] = bbox
        self.disappeared[self.next_object_id] = 0
        self.next_object_id += 1
        
    def _deregister(self, object_id):
        """Deregister an object that has been lost"""
        del self.objects[object_id]
        del self.bboxes[object_id]
        del self.disappeared[object_id]
        
    def update(self, detections):
        """
        Update tracker with new detections.
        
        Args:
            detections: List of (x1, y1, x2, y2, confidence, class_id)
            
        Returns:
            OrderedDict of {object_id: centroid} for currently tracked objects
        """
        # If no detections, mark all objects as disappeared
        if len(detections) == 0:
            for object_id in list(self.disappeared.keys()):
                self.disappeared[object_id] += 1
                
                if self.disappeared[object_id] > self.max_disappeared:
                    self._deregister(object_id)
                    
            return self.objects
            
        # Extract centroids and bboxes from detections
        input_centroids = np.zeros((len(detections), 2), dtype=np.float32)
        input_bboxes = []
        
        for i, det in enumerate(detections):
            x1, y1, x2, y2 = det[:4]
            cx = (x1 + x2) / 2.0
            cy = (y1 + y2) / 2.0
            input_centroids[i] = (cx, cy)
            input_bboxes.append((x1, y1, x2, y2))
            
        # If no existing objects, register all new detections
        if len(self.objects) == 0:
            for i in range(len(input_centroids)):
                self._register(input_centroids[i], input_bboxes[i])
        else:
            # Match existing objects to new detections
            object_ids = list(self.objects.keys())
            object_centroids = list(self.objects.values())
            
            # Compute distance matrix between existing and new centroids
            D = dist.cdist(np.array(object_centroids), input_centroids)
            
            # Find best matches (Hungarian algorithm approximation)
            # Sort by row minimum to process closest matches first
            rows = D.min(axis=1).argsort()
            cols = D.argmin(axis=1)[rows]
            
            used_rows = set()
            used_cols = set()
            
            for row, col in zip(rows, cols):
                if row in used_rows or col in used_cols:
                    continue
                    
                # Check if distance is within threshold
                if D[row, col] > self.max_distance:
                    continue
                    
                # Update the object
                object_id = object_ids[row]
                self.objects[object_id] = input_centroids[col]
                self.bboxes[object_id] = input_bboxes[col]
                self.disappeared[object_id] = 0
                
                used_rows.add(row)
                used_cols.add(col)
                
            # Handle unmatched existing objects (disappeared)
            unused_rows = set(range(len(object_centroids))) - used_rows
            for row in unused_rows:
                object_id = object_ids[row]
                self.disappeared[object_id] += 1
                
                if self.disappeared[object_id] > self.max_disappeared:
                    self._deregister(object_id)
                    
            # Handle unmatched new detections (new objects)
            unused_cols = set(range(len(input_centroids))) - used_cols
            for col in unused_cols:
                self._register(input_centroids[col], input_bboxes[col])
                
        return self.objects
        
    def get_objects(self):
        """Get currently tracked objects"""
        return self.objects.copy()
        
    def get_bboxes(self):
        """Get bounding boxes for tracked objects"""
        return self.bboxes.copy()
        
    def get_object_count(self):
        """Get number of currently tracked objects"""
        return len(self.objects)
