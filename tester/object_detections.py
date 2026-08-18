#!/usr/bin/env python3
"""
Ball Detector (Red + Green) dengan Shape Filter & Anti-Carpet
Standalone - TANPA ROS
"""

import cv2
import numpy as np
import math
import time
import sys
import os

class BallDetector:
    def __init__(self, video_source, frame_width=640, frame_height=480):
        # Video configuration
        self.frame_width = frame_width
        self.frame_height = frame_height
        
        # Camera center point - center X dan max Y (bawah tengah)
        self.camera_center_x = self.frame_width // 2
        self.camera_center_y = self.frame_height
        
        # HSV ranges for RED and GREEN balls
        self.color_ranges = {
            'color1': {
                'name': 'Red Ball',
                'lower': np.array([0, 120, 70]),
                'upper': np.array([10, 255, 255]),
                'lower2': np.array([170, 120, 70]),
                'upper2': np.array([180, 255, 255]),
                'bbox_color': (0, 255, 0),
                'text_color': (0, 255, 0),
                'mask_color': (0, 255, 0),
                'min_area': 500,
                'min_circularity': 0.3,
                'max_aspect': 2.0,
                'min_area_ratio': 0.3
            },
            'color2': {
                'name': 'Green Ball',
                'lower': np.array([35, 50, 50]),
                'upper': np.array([85, 255, 255]),
                'bbox_color': (0, 255, 255),
                'text_color': (0, 255, 255),
                'mask_color': (0, 255, 255),
                'min_area': 500,
                'min_circularity': 0.3,
                'max_aspect': 2.0,
                'min_area_ratio': 0.3
            }
        }
        
        # Shape parameters untuk deteksi lingkaran
        self.shape_params = {
            'min_circularity': 0.3,
            'max_circularity': 1.0,
            'min_solidity': 0.4,
            'max_solidity': 1.0,
            'min_aspect': 0.3,
            'max_aspect': 2.0,
            'bottom_fill': 0.05,
            'min_area_ratio': 0.3,
            'max_area_ratio': 1.0,
            'max_defects': 4,
            'max_frame_ratio': 0.12,
            'max_texture_std': 18.0,
            'reject_border_touch': 1
        }
        
        # Initialize video capture
        if os.path.exists(video_source):
            self.cap = cv2.VideoCapture(video_source)
            print(f"Using video file: {video_source}")
        else:
            try:
                video_source = int(video_source)
                self.cap = cv2.VideoCapture(video_source)
                print(f"Using camera: {video_source}")
            except:
                self.cap = cv2.VideoCapture(0)
                print("Using default camera (0)")
        
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.frame_width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.frame_height)
        self.cap.set(cv2.CAP_PROP_FPS, 30)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        
        # FPS tracking
        self.prev_time = time.time()
        self.frame_count = 0
        self.current_fps = 0
        
        # Detection results
        self.detected_balls = {
            'color1': {'center': None, 'area': 0, 'bbox': None, 'circularity': 0, 'shape_type': 'unknown'},
            'color2': {'center': None, 'area': 0, 'bbox': None, 'circularity': 0, 'shape_type': 'unknown'}
        }
        self.current_angle = None
        self.midpoint_between_balls = None
        
        # Mouse click HSV sampling
        self.sample_points = {'color1': [], 'color2': []}
        self.current_sampling_color = 'color1'
        self.sample_radius = 5
        self.hsv_tolerance = 10
        
        # Performance optimization
        self.trackbar_update_interval = 10
        self.show_debug_windows = True
        
        # Setup HSV tuning window
        self.setup_hsv_window()
        
        # Setup mouse callback for HSV sampling
        cv2.namedWindow("Main Detection - Both Colors")
        cv2.setMouseCallback("Main Detection - Both Colors", self.mouse_callback)
        
        print(f"Camera initialized: {self.frame_width}x{self.frame_height}")
        print(f"Camera center: X={self.camera_center_x}, Y={self.camera_center_y} (bottom center)")
        print("Mouse controls:")
        print("  - LEFT CLICK: Sample HSV value for current color")
        print("  - MIDDLE CLICK: Switch sampling color (Red/Green)")
        print("  - RIGHT CLICK: Clear samples for current color")
        print("Controls:")
        print("  [q] Quit")
        print("  [m] Toggle mask display")
        print("  [s] Save current frame")
        print("========================================")

    # ---------- MOUSE CALLBACK ----------
    def mouse_callback(self, event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            self.sample_hsv_value(x, y)
        elif event == cv2.EVENT_MBUTTONDOWN:
            self.switch_sampling_color()
        elif event == cv2.EVENT_RBUTTONDOWN:
            self.clear_samples()

    def sample_hsv_value(self, x, y):
        success, frame = self.cap.read()
        if not success:
            return
        
        hsv_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        h_values, s_values, v_values = [], [], []
        
        for i in range(max(0, y - self.sample_radius), min(self.frame_height, y + self.sample_radius + 1)):
            for j in range(max(0, x - self.sample_radius), min(self.frame_width, x + self.sample_radius + 1)):
                h, s, v = hsv_frame[i, j]
                h_values.append(h); s_values.append(s); v_values.append(v)
        
        if h_values:
            avg_h, avg_s, avg_v = np.mean(h_values), np.mean(s_values), np.mean(v_values)
            self.sample_points[self.current_sampling_color].append((x, y, avg_h, avg_s, avg_v))
            self.update_hsv_range_from_samples()
            print(f"Sampled {self.color_ranges[self.current_sampling_color]['name']} at ({x}, {y}) - HSV: ({avg_h:.1f}, {avg_s:.1f}, {avg_v:.1f})")

    def update_hsv_range_from_samples(self):
        if not self.sample_points[self.current_sampling_color]:
            return
        
        all_h = [s[2] for s in self.sample_points[self.current_sampling_color]]
        all_s = [s[3] for s in self.sample_points[self.current_sampling_color]]
        all_v = [s[4] for s in self.sample_points[self.current_sampling_color]]
        
        h_min = max(0, int(np.min(all_h) - self.hsv_tolerance))
        h_max = min(179, int(np.max(all_h) + self.hsv_tolerance))
        s_min = max(0, int(np.min(all_s) - self.hsv_tolerance))
        s_max = min(255, int(np.max(all_s) + self.hsv_tolerance))
        v_min = max(0, int(np.min(all_v) - self.hsv_tolerance))
        v_max = min(255, int(np.max(all_v) + self.hsv_tolerance))
        
        if self.current_sampling_color == 'color1':
            # Red color (wraps around)
            if h_min < 10 or h_max > 170:
                self.color_ranges['color1']['lower'] = np.array([0, s_min, v_min])
                self.color_ranges['color1']['upper'] = np.array([h_max, s_max, v_max])
                self.color_ranges['color1']['lower2'] = np.array([170, s_min, v_min])
                self.color_ranges['color1']['upper2'] = np.array([180, s_max, v_max])
            else:
                self.color_ranges['color1']['lower'] = np.array([h_min, s_min, v_min])
                self.color_ranges['color1']['upper'] = np.array([h_max, s_max, v_max])
        else:
            # Green color
            self.color_ranges['color2']['lower'] = np.array([h_min, s_min, v_min])
            self.color_ranges['color2']['upper'] = np.array([h_max, s_max, v_max])
        
        self.update_trackbars_from_range()

    def update_trackbars_from_range(self):
        if self.current_sampling_color == 'color1':
            window_name = "HSV Tuning - Color 1 (Red)"
            lower = self.color_ranges['color1']['lower']
            upper = self.color_ranges['color1']['upper']
        else:
            window_name = "HSV Tuning - Color 2 (Green)"
            lower = self.color_ranges['color2']['lower']
            upper = self.color_ranges['color2']['upper']
        
        cv2.setTrackbarPos("Hue Min", window_name, lower[0])
        cv2.setTrackbarPos("Hue Max", window_name, upper[0])
        cv2.setTrackbarPos("Sat Min", window_name, lower[1])
        cv2.setTrackbarPos("Sat Max", window_name, upper[1])
        cv2.setTrackbarPos("Val Min", window_name, lower[2])
        cv2.setTrackbarPos("Val Max", window_name, upper[2])

    def switch_sampling_color(self):
        self.current_sampling_color = 'color1' if self.current_sampling_color == 'color2' else 'color2'
        print(f"Switched to sampling: {self.color_ranges[self.current_sampling_color]['name']}")

    def clear_samples(self):
        self.sample_points[self.current_sampling_color] = []
        print(f"Cleared all samples for {self.color_ranges[self.current_sampling_color]['name']}")

    # ---------- SETUP HSV WINDOW ----------
    def setup_hsv_window(self):
        cv2.namedWindow("HSV Tuning - Color 1 (Red)")
        cv2.resizeWindow("HSV Tuning - Color 1 (Red)", 400, 350)
        cv2.namedWindow("HSV Tuning - Color 2 (Green)")
        cv2.resizeWindow("HSV Tuning - Color 2 (Green)", 400, 350)
        
        trackbars_color1 = [
            ("Hue Min", 0, 179), ("Hue Max", 10, 179),
            ("Sat Min", 120, 255), ("Sat Max", 255, 255),
            ("Val Min", 70, 255), ("Val Max", 255, 255),
            ("Min Area", 500, 10000),
            ("Min Circ", 30, 100),
            ("Max Aspect", 200, 500),
            ("Tolerance", 10, 50)
        ]
        
        trackbars_color2 = [
            ("Hue Min", 35, 179), ("Hue Max", 85, 179),
            ("Sat Min", 50, 255), ("Sat Max", 255, 255),
            ("Val Min", 50, 255), ("Val Max", 255, 255),
            ("Min Area", 500, 10000),
            ("Min Circ", 30, 100),
            ("Max Aspect", 200, 500),
            ("Tolerance", 10, 50)
        ]
        
        for name, default, max_val in trackbars_color1:
            cv2.createTrackbar(name, "HSV Tuning - Color 1 (Red)", default, max_val, self.empty_callback)
        
        for name, default, max_val in trackbars_color2:
            cv2.createTrackbar(name, "HSV Tuning - Color 2 (Green)", default, max_val, self.empty_callback)

    def empty_callback(self, x):
        pass

    # ---------- SHAPE DETECTION ----------
    def compute_circularity(self, contour):
        area = cv2.contourArea(contour)
        perimeter = cv2.arcLength(contour, True)
        if perimeter == 0:
            return 0.0
        return (4 * np.pi * area) / (perimeter * perimeter)

    def compute_solidity(self, contour):
        area = cv2.contourArea(contour)
        hull = cv2.convexHull(contour)
        hull_area = cv2.contourArea(hull)
        if hull_area == 0:
            return 0.0
        return area / hull_area

    def compute_area_ratio(self, contour):
        area = cv2.contourArea(contour)
        if len(contour) >= 5:
            (cx, cy), radius = cv2.minEnclosingCircle(contour)
            circle_area = np.pi * radius * radius
            return area / circle_area if circle_area > 0 else 0
        return 0.0

    def compute_defects(self, contour):
        if len(contour) <= 3:
            return 0
        hull_indices = cv2.convexHull(contour, returnPoints=False)
        if len(hull_indices) <= 3:
            return 0
        defects = cv2.convexityDefects(contour, hull_indices)
        if defects is None:
            return 0
        depths_px = defects[:, 0, 3] / 256.0
        return int(np.sum(depths_px > 2.0))

    def touches_border(self, contour, margin=3):
        x, y, w, h = cv2.boundingRect(contour)
        return (x <= margin or y <= margin or
                (x + w) >= (self.frame_width - margin) or 
                (y + h) >= (self.frame_height - margin))

    def compute_texture_std(self, gray, contour):
        x, y, w, h = cv2.boundingRect(contour)
        if w <= 2 or h <= 2:
            return 0.0
        roi = gray[y:y+h, x:x+w]
        mask = np.zeros((h, w), dtype=np.uint8)
        contour_shifted = contour - np.array([x, y])
        cv2.drawContours(mask, [contour_shifted], -1, 255, -1)
        lap = cv2.Laplacian(roi, cv2.CV_64F, ksize=3)
        vals = lap[mask > 0]
        if vals.size < 10:
            return 0.0
        return float(np.std(vals))

    def is_circle_shape(self, contour, frame_area=None, gray=None):
        area = cv2.contourArea(contour)
        p = self.shape_params
        
        circularity = self.compute_circularity(contour)
        solidity = self.compute_solidity(contour)
        x, y, w, h = cv2.boundingRect(contour)
        aspect_ratio = w / h if h > 0 else 0
        area_ratio = self.compute_area_ratio(contour)
        defects = self.compute_defects(contour)
        
        # Bottom flatness (untuk setengah lingkaran)
        mask = np.zeros((h, w), dtype=np.uint8)
        contour_shifted = contour - np.array([x, y])
        cv2.drawContours(mask, [contour_shifted], -1, 255, -1)
        bottom_third = mask[int(h*0.7):h, :]
        bottom_filled = np.sum(bottom_third > 0) / bottom_third.size if bottom_third.size > 0 else 0
        
        # Anti-karpet
        frame_ratio = area / frame_area if frame_area and frame_area > 0 else 0.0
        border_touch = self.touches_border(contour, 3)
        texture_std = self.compute_texture_std(gray, contour) if gray is not None else 0.0
        
        is_circle = (
            p['min_circularity'] < circularity < p['max_circularity'] and
            p['min_solidity'] < solidity < p['max_solidity'] and
            p['min_aspect'] < aspect_ratio < p['max_aspect'] and
            bottom_filled > p['bottom_fill'] and
            p['min_area_ratio'] < area_ratio < p['max_area_ratio'] and
            defects < p['max_defects'] and
            frame_ratio < p['max_frame_ratio'] and
            texture_std < p['max_texture_std'] and
            (not p['reject_border_touch'] or not border_touch)
        )
        
        return is_circle, {
            'circularity': circularity,
            'solidity': solidity,
            'aspect_ratio': aspect_ratio,
            'area_ratio': area_ratio,
            'defects': defects,
            'bottom_filled': bottom_filled,
            'frame_ratio': frame_ratio,
            'texture_std': texture_std,
            'border_touch': border_touch
        }

    # ---------- HSV VALUES FROM TRACKBARS ----------
    def get_hsv_values_from_trackbars(self, color_window):
        hue_min = cv2.getTrackbarPos("Hue Min", color_window)
        hue_max = cv2.getTrackbarPos("Hue Max", color_window)
        sat_min = cv2.getTrackbarPos("Sat Min", color_window)
        sat_max = cv2.getTrackbarPos("Sat Max", color_window)
        val_min = cv2.getTrackbarPos("Val Min", color_window)
        val_max = cv2.getTrackbarPos("Val Max", color_window)
        min_area = cv2.getTrackbarPos("Min Area", color_window)
        min_circ = cv2.getTrackbarPos("Min Circ", color_window) / 100.0
        max_aspect = cv2.getTrackbarPos("Max Aspect", color_window) / 100.0
        tolerance = cv2.getTrackbarPos("Tolerance", color_window)
        return hue_min, hue_max, sat_min, sat_max, val_min, val_max, min_area, min_circ, max_aspect, tolerance

    def update_color_ranges_from_trackbars(self):
        # Color 1 (Red)
        h1_min, h1_max, s1_min, s1_max, v1_min, v1_max, area1_min, circ1, aspect1, tol1 = self.get_hsv_values_from_trackbars("HSV Tuning - Color 1 (Red)")
        self.color_ranges['color1']['lower'] = np.array([h1_min, s1_min, v1_min])
        self.color_ranges['color1']['upper'] = np.array([h1_max, s1_max, v1_max])
        self.color_ranges['color1']['lower2'] = np.array([170, s1_min, v1_min])
        self.color_ranges['color1']['upper2'] = np.array([180, s1_max, v1_max])
        self.color_ranges['color1']['min_area'] = area1_min
        self.color_ranges['color1']['min_circularity'] = circ1
        self.color_ranges['color1']['max_aspect'] = aspect1
        
        # Color 2 (Green)
        h2_min, h2_max, s2_min, s2_max, v2_min, v2_max, area2_min, circ2, aspect2, tol2 = self.get_hsv_values_from_trackbars("HSV Tuning - Color 2 (Green)")
        self.color_ranges['color2']['lower'] = np.array([h2_min, s2_min, v2_min])
        self.color_ranges['color2']['upper'] = np.array([h2_max, s2_max, v2_max])
        self.color_ranges['color2']['min_area'] = area2_min
        self.color_ranges['color2']['min_circularity'] = circ2
        self.color_ranges['color2']['max_aspect'] = aspect2
        
        # Update shape_params
        self.shape_params['min_circularity'] = min(circ1, circ2)
        self.shape_params['max_aspect'] = max(aspect1, aspect2)
        self.hsv_tolerance = (tol1 + tol2) // 2

    # ---------- FPS ----------
    def calculate_fps(self):
        current_time = time.time()
        elapsed = current_time - self.prev_time
        if elapsed > 0:
            self.current_fps = 1.0 / elapsed
        else:
            self.current_fps = 0
        self.prev_time = current_time
        return self.current_fps

    # ---------- DETECT SINGLE COLOR ----------
    def detect_single_color(self, hsv_frame, gray_frame, color_key):
        color_info = self.color_ranges[color_key]
        
        if color_key == 'color1':
            # Red color (two ranges karena wrap around)
            mask1 = cv2.inRange(hsv_frame, color_info['lower'], color_info['upper'])
            mask2 = cv2.inRange(hsv_frame, color_info['lower2'], color_info['upper2'])
            mask = cv2.bitwise_or(mask1, mask2)
        else:
            # Green color (single range)
            mask = cv2.inRange(hsv_frame, color_info['lower'], color_info['upper'])
        
        kernel = np.ones((3, 3), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        best_contour = None
        best_score = -1
        best_metrics = {}
        frame_area = self.frame_width * self.frame_height
        
        for contour in contours:
            area = cv2.contourArea(contour)
            min_area = color_info.get('min_area', 500)
            if area < min_area:
                continue
            
            is_circle, metrics = self.is_circle_shape(contour, frame_area, gray_frame)
            
            if is_circle:
                score = (metrics['circularity'] * 0.4 + 
                        metrics['area_ratio'] * 0.3 + 
                        metrics['solidity'] * 0.3)
                if score > best_score:
                    best_score = score
                    best_contour = contour
                    best_metrics = metrics
        
        if best_contour is not None:
            x, y, w, h = cv2.boundingRect(best_contour)
            center = (x + w//2, y + h//2)
            area = cv2.contourArea(best_contour)
            shape_type = 'circle' if best_metrics.get('area_ratio', 0) > 0.6 else 'halfcircle'
            return center, area, (x, y, w, h), mask, best_metrics['circularity'], shape_type
        
        return None, 0, None, mask, 0, 'unknown'

    # ---------- DETECT ALL ----------
    def detect_all_balls(self, frame):
        hsv_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        gray_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        if self.frame_count % self.trackbar_update_interval == 0:
            self.update_color_ranges_from_trackbars()
        
        for color_key in self.detected_balls:
            self.detected_balls[color_key] = {'center': None, 'area': 0, 'bbox': None, 'circularity': 0, 'shape_type': 'unknown'}
        
        masks = {}
        individual_results = {}
        colored_masks = {}
        
        for color_key in self.color_ranges:
            center, area, bbox, mask, circularity, shape_type = self.detect_single_color(
                hsv_frame, gray_frame, color_key)
            
            if center is not None:
                self.detected_balls[color_key] = {
                    'center': center,
                    'area': area,
                    'bbox': bbox,
                    'circularity': circularity,
                    'shape_type': shape_type
                }
            
            masks[color_key] = mask
            colored_masks[color_key] = self.create_colored_mask_display(mask, self.color_ranges[color_key]['mask_color'])
            individual_results[color_key] = self.create_individual_result_frame(frame, color_key, 
                                                                               self.detected_balls[color_key], mask)
        
        self.frame_count += 1
        return masks, colored_masks, individual_results

    def create_colored_mask_display(self, mask, color):
        colored_mask = np.zeros((mask.shape[0], mask.shape[1], 3), dtype=np.uint8)
        colored_mask[mask > 0] = color
        return colored_mask

    def create_individual_result_frame(self, frame, color_key, ball_info, mask):
        result_frame = frame.copy()
        color_info = self.color_ranges[color_key]
        
        if ball_info['center'] is not None and ball_info['bbox'] is not None:
            x, y, w, h = ball_info['bbox']
            center_x, center_y = ball_info['center']
            
            cv2.rectangle(result_frame, (x, y), (x + w, y + h), color_info['bbox_color'], 2)
            cv2.circle(result_frame, (center_x, center_y), 6, color_info['bbox_color'], -1)
            cv2.circle(result_frame, (center_x, center_y), 2, (255, 255, 255), -1)
            
            info_text = f"{color_info['name']} [{ball_info['shape_type']}]"
            cv2.putText(result_frame, info_text, (x, y - 50), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, color_info['text_color'], 2)
            
            area_text = f"Area: {ball_info['area']:.0f} Circ:{ball_info['circularity']:.2f}"
            cv2.putText(result_frame, area_text, (x, y - 30), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, color_info['text_color'], 1)
        
        title_text = f"{color_info['name']}"
        cv2.putText(result_frame, title_text, (10, 25), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, color_info['text_color'], 2)
        
        status_text = "Detected" if ball_info['center'] is not None else "Not Found"
        status_color = (0, 255, 0) if ball_info['center'] is not None else (0, 0, 255)
        cv2.putText(result_frame, status_text, (10, 50), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.6, status_color, 2)
        
        return result_frame

    # ---------- CALCULATE MIDPOINT & ANGLE ----------
    def calculate_midpoint_and_angle(self):
        centers = []
        for color_key, ball_info in self.detected_balls.items():
            if ball_info['center'] is not None:
                centers.append(ball_info['center'])
        
        if len(centers) == 2:
            midpoint_x = (centers[0][0] + centers[1][0]) // 2
            midpoint_y = (centers[0][1] + centers[1][1]) // 2
            self.midpoint_between_balls = (midpoint_x, midpoint_y)
            
            delta_x = midpoint_x - self.camera_center_x
            delta_y = self.camera_center_y - midpoint_y
            
            angle_rad = math.atan2(delta_y, delta_x)
            angle_deg = math.degrees(angle_rad)
            angle_deg = angle_deg - 90
            
            if angle_deg > 180:
                angle_deg -= 360
            elif angle_deg < -180:
                angle_deg += 360
                
            self.current_angle = angle_deg
        else:
            self.midpoint_between_balls = None
            self.current_angle = None
        
        return self.midpoint_between_balls, self.current_angle

    # ---------- DRAW MAIN ----------
    def draw_main_detection_results(self, frame):
        # Sample points
        for color_key, samples in self.sample_points.items():
            color_info = self.color_ranges[color_key]
            for x, y, h, s, v in samples:
                cv2.circle(frame, (x, y), 3, color_info['bbox_color'], -1)
                cv2.circle(frame, (x, y), 1, (255, 255, 255), -1)
        
        # Detected balls
        for color_key, ball_info in self.detected_balls.items():
            if ball_info['center'] is not None and ball_info['bbox'] is not None:
                color_info = self.color_ranges[color_key]
                x, y, w, h = ball_info['bbox']
                center_x, center_y = ball_info['center']
                
                cv2.rectangle(frame, (x, y), (x + w, y + h), color_info['bbox_color'], 2)
                cv2.circle(frame, (center_x, center_y), 6, color_info['bbox_color'], -1)
                cv2.circle(frame, (center_x, center_y), 2, (255, 255, 255), -1)
                
                label = f"{color_info['name']} [{ball_info['shape_type']}]"
                cv2.putText(frame, label, (x, y - 10), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.4, color_info['text_color'], 1)
        
        # Camera center
        cv2.circle(frame, (self.camera_center_x, self.camera_center_y), 8, (0, 0, 255), -1)
        cv2.circle(frame, (self.camera_center_x, self.camera_center_y), 3, (255, 255, 255), -1)
        
        # Lines and midpoint
        if self.midpoint_between_balls is not None:
            centers = [ball_info['center'] for ball_info in self.detected_balls.values() 
                      if ball_info['center'] is not None]
            if len(centers) == 2:
                cv2.line(frame, centers[0], centers[1], (0, 255, 255), 2)
                cv2.circle(frame, self.midpoint_between_balls, 6, (255, 0, 255), -1)
                cv2.circle(frame, self.midpoint_between_balls, 2, (255, 255, 255), -1)
                cv2.line(frame, (self.camera_center_x, self.camera_center_y), 
                        self.midpoint_between_balls, (255, 255, 255), 2)
        
        self.draw_information_panel(frame)

    def draw_information_panel(self, frame):
        # FPS
        cv2.putText(frame, f"FPS: {self.current_fps:.1f}", 
                   (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        
        # Sampling info
        sampling_color = self.color_ranges[self.current_sampling_color]['name']
        cv2.putText(frame, f"Sampling: {sampling_color}", 
                   (10, self.frame_height - 60), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        cv2.putText(frame, f"Samples: {len(self.sample_points[self.current_sampling_color])}", 
                   (10, self.frame_height - 40), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        
        # Detection status
        y_offset = 50
        for color_key, ball_info in self.detected_balls.items():
            color_info = self.color_ranges[color_key]
            status = "DETECTED" if ball_info['center'] is not None else "NOT FOUND"
            status_color = (0, 255, 0) if ball_info['center'] is not None else (0, 0, 255)
            
            status_text = f"{color_info['name']}: {status}"
            cv2.putText(frame, status_text, (10, y_offset), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, status_color, 1)
            y_offset += 20
            
            if ball_info['center'] is not None:
                info_text = f"Circ:{ball_info['circularity']:.2f} {ball_info['shape_type']}"
                cv2.putText(frame, info_text, (20, y_offset), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.4, color_info['text_color'], 1)
                y_offset += 15
        
        # Angle
        if self.current_angle is not None:
            cv2.putText(frame, f"Angle: {self.current_angle:.1f}°", (10, y_offset + 15), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

    # ---------- PROCESS FRAME ----------
    def process_frame(self):
        self.current_fps = self.calculate_fps()
        
        success, frame = self.cap.read()
        if not success:
            return False, None
        
        masks, colored_masks, individual_results = self.detect_all_balls(frame)
        midpoint, angle = self.calculate_midpoint_and_angle()
        
        main_result_frame = frame.copy()
        self.draw_main_detection_results(main_result_frame)
        
        ball_centers = [ball_info['center'] for ball_info in self.detected_balls.values() 
                       if ball_info['center'] is not None]
        
        results = (
            main_result_frame,
            colored_masks['color1'],
            colored_masks['color2'],
            individual_results['color1'],
            individual_results['color2'],
            ball_centers,
            angle,
            midpoint,
            self.current_fps
        )
        
        return True, results

    # ---------- DISPLAY ----------
    def display_results(self, main_frame, mask_color1, mask_color2, result_color1, result_color2, 
                        ball_centers, angle_deg, midpoint, current_fps):
        cv2.imshow("Main Detection - Both Colors", main_frame)
        
        if self.show_debug_windows:
            cv2.imshow("Mask - Red Ball", mask_color1)
            cv2.imshow("Mask - Green Ball", mask_color2)

    def should_exit(self):
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            return True
        elif key == ord('m'):
            self.show_debug_windows = not self.show_debug_windows
            print(f"Debug windows: {'ON' if self.show_debug_windows else 'OFF'}")
        elif key == ord('s'):
            ts = time.strftime("%Y%m%d_%H%M%S")
            cv2.imwrite(f"buoy_detection_{ts}.jpg", main_frame)
            print(f"Saved: buoy_detection_{ts}.jpg")
        return False

    def get_detection_data(self):
        ball_centers = []
        for color_key, ball_info in self.detected_balls.items():
            if ball_info['center'] is not None:
                ball_centers.append({
                    'color': color_key,
                    'name': self.color_ranges[color_key]['name'],
                    'center': ball_info['center'],
                    'area': ball_info['area'],
                    'bbox': ball_info['bbox'],
                    'circularity': ball_info['circularity'],
                    'shape_type': ball_info['shape_type']
                })
        
        return {
            'angle': self.current_angle,
            'midpoint': self.midpoint_between_balls,
            'balls_detected': ball_centers,
            'fps': self.current_fps,
            'detection_status': f"{len(ball_centers)}/2 balls detected",
            'sampling_color': self.current_sampling_color,
            'samples_count': len(self.sample_points[self.current_sampling_color])
        }

    def cleanup(self):
        self.cap.release()
        cv2.destroyAllWindows()
        print("Cleanup completed.")


# ---------- MAIN ----------
def main():
    # Configuration
    video_source = "1"  # or 0 for camera
    # video_source = 0  # Uncomment untuk webcam
    
    frame_width = 640
    frame_height = 480
    
    print("Starting Ball Tracking System (Standalone - No ROS)...")
    print("========================================")
    
    try:
        # Initialize ball detector
        detector = BallDetector(video_source, frame_width, frame_height)
        
        print("\nSystem ready. Press 'q' to quit.")
        print("Controls:")
        print("  [q] Quit")
        print("  [m] Toggle mask display")
        print("  [s] Save current frame")
        print("  L-Click: Sample HSV, M-Click: Switch color, R-Click: Clear samples")
        print("========================================\n")
        
        while True:
            success, results = detector.process_frame()
            if not success:
                print("Failed to read frame. Exiting...")
                break
            
            # Unpack results
            main_frame, mask_color1, mask_color2, result_color1, result_color2, ball_centers, angle_deg, midpoint, current_fps = results
            
            # Display results
            detector.display_results(
                main_frame, mask_color1, mask_color2, result_color1, result_color2,
                ball_centers, angle_deg, midpoint, current_fps
            )
            
            # Print angle to console
            if angle_deg is not None:
                print(f"Angle: {angle_deg:.1f}° | Balls: {len(ball_centers)}", end='\r')
            else:
                print("No balls detected   ", end='\r')
            
            # Check for exit
            if detector.should_exit():
                break
                
    except KeyboardInterrupt:
        print("\nShutting down by user request...")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if 'detector' in locals():
            detector.cleanup()
        print("Program terminated.")

if __name__ == "__main__":
    main()