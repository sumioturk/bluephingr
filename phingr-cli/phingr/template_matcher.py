"""Template matching for UI element detection.

User registers UI elements by cropping from device screenshots.
At runtime, templates are matched against current screenshot using
OpenCV's normalized cross-correlation for sub-pixel accuracy.
"""

import io
import json
import logging
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

logger = logging.getLogger("phingr-cli")


class TemplateMatcher:
    def __init__(self, templates_dir: Path):
        self.templates_dir = templates_dir
        self.templates_dir.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, np.ndarray] = {}

    def _load_template(self, name: str) -> np.ndarray | None:
        """Load a template image by name."""
        if name in self._cache:
            return self._cache[name]

        path = self.templates_dir / f"{name}.png"
        if not path.exists():
            path = self.templates_dir / f"{name}.jpg"
        if not path.exists():
            return None

        img = cv2.imread(str(path))
        if img is not None:
            self._cache[name] = img
        return img

    def save_template(self, name: str, image_bytes: bytes,
                      x1: float, y1: float, x2: float, y2: float,
                      tap_offset: tuple[float, float] = (0.5, 0.5),
                      threshold: float | None = None) -> dict:
        """Crop and save a template from a screenshot.

        Args:
            name: template tag name
            image_bytes: full screenshot JPEG
            x1, y1, x2, y2: crop region in normalized 0-1 coordinates
        """
        img = Image.open(io.BytesIO(image_bytes))
        w, h = img.size

        # Convert normalized coords to pixel coords
        px1 = int(x1 * w)
        py1 = int(y1 * h)
        px2 = int(x2 * w)
        py2 = int(y2 * h)

        cropped = img.crop((px1, py1, px2, py2))
        path = self.templates_dir / f"{name}.png"
        cropped.save(path)

        # Clear cache
        self._cache.pop(name, None)

        # Save metadata
        meta = self._load_meta()
        entry = {
            "crop": [x1, y1, x2, y2],
            "size": [px2 - px1, py2 - py1],
            "tap_offset": list(tap_offset),
        }
        if threshold is not None:
            entry["threshold"] = threshold
        meta[name] = entry
        self._save_meta(meta)

        logger.info(f"Template saved: {name} ({px2-px1}x{py2-py1}px)")
        return {"name": name, "size": [px2 - px1, py2 - py1]}

    def delete_template(self, name: str):
        """Delete a saved template."""
        for ext in (".png", ".jpg"):
            path = self.templates_dir / f"{name}{ext}"
            if path.exists():
                path.unlink()
        self._cache.pop(name, None)
        meta = self._load_meta()
        meta.pop(name, None)
        self._save_meta(meta)

    def list_templates(self) -> list[dict]:
        """List all saved templates."""
        meta = self._load_meta()
        templates = []
        for name, info in meta.items():
            has_file = (self.templates_dir / f"{name}.png").exists() or \
                       (self.templates_dir / f"{name}.jpg").exists()
            if has_file:
                templates.append({"name": name, **info})
        return templates

    def find(self, screenshot_bytes: bytes, name: str,
             threshold: float | None = None,
             tap_offset_override: tuple[float, float] | None = None,
             match_mode: str | None = None) -> tuple[float, float] | None:
        """Find a template in a screenshot using normalized cross-correlation.

        Uses multi-scale matching to handle slight camera distance changes.
        Lower threshold (0.55) accounts for camera lighting/angle variation.

        Tap point is offset from the top-left of the bounding box.
        Default offset is (0.5, 0.5) = center. Can be customized
        per template via save_template(..., tap_offset=(0.8, 0.5)).

        Args:
            screenshot_bytes: current screenshot JPEG
            name: template name to find
            threshold: minimum match score (0-1). Default 0.55 for camera images.

        Returns:
            (x, y) normalized 0-1 coordinates of tap point, or None if not found
        """
        import time
        t0 = time.time()

        template = self._load_template(name)
        if template is None:
            logger.warning(f'Template "{name}" not found on disk')
            return None

        # Resolve threshold: per-call > per-template > default (0.55)
        if threshold is None:
            meta = self._load_meta()
            threshold = meta.get(name, {}).get("threshold", 0.8)

        # Decode screenshot
        img_arr = np.frombuffer(screenshot_bytes, np.uint8)
        screenshot = cv2.imdecode(img_arr, cv2.IMREAD_COLOR)
        if screenshot is None:
            return None

        # Resolve match mode: per-call > per-template > default ("normal")
        # Modes: "normal" (grayscale), "edge" (Canny edges), "both" (best of both)
        if match_mode is None:
            meta = self._load_meta()
            match_mode = meta.get(name, {}).get("match_mode", "normal")

        gray_screen = cv2.cvtColor(screenshot, cv2.COLOR_BGR2GRAY)
        gray_screen = cv2.GaussianBlur(gray_screen, (3, 3), 0)
        gray_template = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
        gray_template = cv2.GaussianBlur(gray_template, (3, 3), 0)

        use_edge = match_mode in ("edge", "both")
        use_gray = match_mode in ("normal", "both")

        edge_screen = edge_template = None
        if use_edge:
            edge_screen = cv2.Canny(gray_screen, 50, 150)
            edge_template = cv2.Canny(gray_template, 50, 150)

        sh, sw = gray_screen.shape[:2]
        th, tw = gray_template.shape[:2]

        if th > sh or tw > sw:
            return None

        best_score = 0.0
        best_loc = None
        best_scale = 1.0
        all_scores = []

        for scale in [1.0, 0.97, 1.03, 0.94, 1.06, 0.9, 1.1, 0.85, 1.15, 0.8, 1.2]:
            scaled_w = int(tw * scale)
            scaled_h = int(th * scale)
            if scaled_w <= 2 or scaled_h <= 2 or scaled_w > sw or scaled_h > sh:
                continue

            max_val, max_loc = 0, (0, 0)

            if use_gray:
                scaled_g = cv2.resize(gray_template, (scaled_w, scaled_h))
                res = cv2.matchTemplate(gray_screen, scaled_g, cv2.TM_CCOEFF_NORMED)
                _, v, _, loc = cv2.minMaxLoc(res)
                if v > max_val:
                    max_val, max_loc = v, loc

            if use_edge:
                scaled_e = cv2.resize(edge_template, (scaled_w, scaled_h))
                res = cv2.matchTemplate(edge_screen, scaled_e, cv2.TM_CCOEFF_NORMED)
                _, v, _, loc = cv2.minMaxLoc(res)
                if v > max_val:
                    max_val, max_loc = v, loc

            all_scores.append((scale, max_val))

            if max_val > best_score:
                best_score = max_val
                best_loc = max_loc
                best_scale = scale

        elapsed_ms = (time.time() - t0) * 1000

        if best_score < threshold or best_loc is None:
            logger.info(
                f'Template "{name}" no match: best={best_score:.3f} '
                f'threshold={threshold} ({elapsed_ms:.0f}ms) '
                f'scores={[(s, f"{v:.3f}") for s, v in all_scores[:5]]}'
            )
            return None

        # Get tap offset: override > metadata > default center
        if tap_offset_override:
            tap_offset = list(tap_offset_override)
        else:
            meta = self._load_meta()
            tap_offset = meta.get(name, {}).get("tap_offset", [0.5, 0.5])

        # Calculate tap point in normalized coords
        scaled_tw = int(tw * best_scale)
        scaled_th = int(th * best_scale)
        cx = (best_loc[0] + scaled_tw * tap_offset[0]) / sw
        cy = (best_loc[1] + scaled_th * tap_offset[1]) / sh

        logger.info(
            f'Template "{name}" MATCH: score={best_score:.3f} '
            f'scale={best_scale:.2f} offset=({tap_offset[0]:.2f},{tap_offset[1]:.2f}) '
            f'tap=({cx:.4f}, {cy:.4f}) ({elapsed_ms:.0f}ms)'
        )

        return (cx, cy)

    def find_bbox(self, screenshot_bytes: bytes, name: str,
                  threshold: float | None = None,
                  match_mode: str | None = None) -> dict | None:
        """Find template and return bbox + tap point (all normalized 0-1).

        Returns: {x1, y1, x2, y2, cx, cy, score} or None.
        """
        template = self._load_template(name)
        if template is None:
            return None
        if threshold is None:
            meta = self._load_meta()
            threshold = meta.get(name, {}).get("threshold", 0.8)

        img_arr = np.frombuffer(screenshot_bytes, np.uint8)
        screenshot = cv2.imdecode(img_arr, cv2.IMREAD_COLOR)
        if screenshot is None:
            return None

        if match_mode is None:
            meta = self._load_meta()
            match_mode = meta.get(name, {}).get("match_mode", "normal")

        gray_screen = cv2.GaussianBlur(cv2.cvtColor(screenshot, cv2.COLOR_BGR2GRAY), (3, 3), 0)
        gray_template = cv2.GaussianBlur(cv2.cvtColor(template, cv2.COLOR_BGR2GRAY), (3, 3), 0)
        use_edge = match_mode in ("edge", "both")
        use_gray = match_mode in ("normal", "both")
        edge_screen = cv2.Canny(gray_screen, 50, 150) if use_edge else None
        edge_template = cv2.Canny(gray_template, 50, 150) if use_edge else None

        sh, sw = gray_screen.shape[:2]
        th, tw = gray_template.shape[:2]
        if th > sh or tw > sw:
            return None

        best_score, best_loc, best_scale = 0.0, None, 1.0
        for scale in [1.0, 0.97, 1.03, 0.94, 1.06, 0.9, 1.1, 0.85, 1.15, 0.8, 1.2]:
            scaled_w, scaled_h = int(tw * scale), int(th * scale)
            if scaled_w <= 2 or scaled_h <= 2 or scaled_w > sw or scaled_h > sh:
                continue
            max_val, max_loc = 0, (0, 0)
            if use_gray:
                scaled_g = cv2.resize(gray_template, (scaled_w, scaled_h))
                res = cv2.matchTemplate(gray_screen, scaled_g, cv2.TM_CCOEFF_NORMED)
                _, v, _, loc = cv2.minMaxLoc(res)
                if v > max_val:
                    max_val, max_loc = v, loc
            if use_edge:
                scaled_e = cv2.resize(edge_template, (scaled_w, scaled_h))
                res = cv2.matchTemplate(edge_screen, scaled_e, cv2.TM_CCOEFF_NORMED)
                _, v, _, loc = cv2.minMaxLoc(res)
                if v > max_val:
                    max_val, max_loc = v, loc
            if max_val > best_score:
                best_score, best_loc, best_scale = max_val, max_loc, scale

        if best_score < threshold or best_loc is None:
            return None

        scaled_tw = int(tw * best_scale)
        scaled_th = int(th * best_scale)
        x1 = best_loc[0] / sw
        y1 = best_loc[1] / sh
        x2 = (best_loc[0] + scaled_tw) / sw
        y2 = (best_loc[1] + scaled_th) / sh
        return {
            "x1": x1, "y1": y1, "x2": x2, "y2": y2,
            "cx": (x1 + x2) / 2, "cy": (y1 + y2) / 2,
            "score": round(best_score, 3),
        }

    def find_and_annotate(self, screenshot_bytes: bytes, name: str,
                          threshold: float | None = None,
                          tap_offset_override: tuple[float, float] | None = None,
                          match_mode: str | None = None) -> tuple[tuple[float, float] | None, bytes]:
        """Find template and return annotated screenshot with match rectangle.

        Returns:
            (coords_or_none, annotated_jpeg_bytes)
        """
        template = self._load_template(name)
        if template is None:
            return None, screenshot_bytes

        # Resolve threshold: per-call > per-template > default
        if threshold is None:
            meta = self._load_meta()
            threshold = meta.get(name, {}).get("threshold", 0.8)

        img_arr = np.frombuffer(screenshot_bytes, np.uint8)
        screenshot = cv2.imdecode(img_arr, cv2.IMREAD_COLOR)
        if screenshot is None:
            return None, screenshot_bytes

        if match_mode is None:
            meta_for_mode = self._load_meta()
            match_mode = meta_for_mode.get(name, {}).get("match_mode", "normal")

        gray_screen = cv2.cvtColor(screenshot, cv2.COLOR_BGR2GRAY)
        gray_screen = cv2.GaussianBlur(gray_screen, (3, 3), 0)
        gray_template = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
        gray_template = cv2.GaussianBlur(gray_template, (3, 3), 0)

        use_edge = match_mode in ("edge", "both")
        use_gray = match_mode in ("normal", "both")
        edge_screen = edge_template = None
        if use_edge:
            edge_screen = cv2.Canny(gray_screen, 50, 150)
            edge_template = cv2.Canny(gray_template, 50, 150)

        sh, sw = gray_screen.shape[:2]
        th, tw = gray_template.shape[:2]

        best_score = 0.0
        best_loc = None
        best_scale = 1.0

        for scale in [1.0, 0.97, 1.03, 0.94, 1.06, 0.9, 1.1, 0.85, 1.15, 0.8, 1.2]:
            scaled_w = int(tw * scale)
            scaled_h = int(th * scale)
            if scaled_w <= 2 or scaled_h <= 2 or scaled_w > sw or scaled_h > sh:
                continue
            max_val, max_loc = 0, (0, 0)
            if use_gray:
                scaled_g = cv2.resize(gray_template, (scaled_w, scaled_h))
                res = cv2.matchTemplate(gray_screen, scaled_g, cv2.TM_CCOEFF_NORMED)
                _, v, _, loc = cv2.minMaxLoc(res)
                if v > max_val: max_val, max_loc = v, loc
            if use_edge:
                scaled_e = cv2.resize(edge_template, (scaled_w, scaled_h))
                res = cv2.matchTemplate(edge_screen, scaled_e, cv2.TM_CCOEFF_NORMED)
                _, v, _, loc = cv2.minMaxLoc(res)
                if v > max_val: max_val, max_loc = v, loc
            if max_val > best_score:
                best_score = max_val
                best_loc = max_loc
                best_scale = scale

        # Get tap offset: override > metadata > default center
        if tap_offset_override:
            tap_offset = list(tap_offset_override)
        else:
            meta = self._load_meta()
            tap_offset = meta.get(name, {}).get("tap_offset", [0.5, 0.5])

        # Draw on screenshot
        annotated = screenshot.copy()
        if best_loc and best_score >= threshold:
            scaled_tw = int(tw * best_scale)
            scaled_th = int(th * best_scale)
            x1, y1 = best_loc
            x2, y2 = x1 + scaled_tw, y1 + scaled_th
            # Tap point using offset
            tx = int(x1 + scaled_tw * tap_offset[0])
            ty = int(y1 + scaled_th * tap_offset[1])

            # Green rect + red crosshair at tap point
            cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.drawMarker(annotated, (tx, ty), (0, 0, 255), cv2.MARKER_CROSS, 20, 2)
            cv2.putText(annotated, f'{name} ({best_score:.2f})',
                        (x1, y1 - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

            _, buf = cv2.imencode('.jpg', annotated, [cv2.IMWRITE_JPEG_QUALITY, 85])
            norm_cx = (x1 + scaled_tw * tap_offset[0]) / sw
            norm_cy = (y1 + scaled_th * tap_offset[1]) / sh
            return (norm_cx, norm_cy), buf.tobytes()
        else:
            # Red text: not found
            cv2.putText(annotated, f'{name}: NOT FOUND (best={best_score:.2f})',
                        (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
            _, buf = cv2.imencode('.jpg', annotated, [cv2.IMWRITE_JPEG_QUALITY, 85])
            return None, buf.tobytes()

    def find_text(self, screenshot_bytes: bytes, text: str) -> tuple[float, float] | None:
        """Find text on screen using OCR. Returns center coordinates (normalized 0-1).

        Runs pytesseract OCR on the screenshot and finds the bounding box
        of the text that contains the search string (case-insensitive).
        """
        try:
            import pytesseract
        except ImportError:
            raise RuntimeError(
                "pytesseract not installed. Run: rm .venv/.phingr-cli-installed && bash setup.sh"
            )

        img_arr = np.frombuffer(screenshot_bytes, np.uint8)
        screenshot = cv2.imdecode(img_arr, cv2.IMREAD_COLOR)
        if screenshot is None:
            return None

        sh, sw = screenshot.shape[:2]
        text_lower = text.lower()

        # Try multiple approaches, use the one that finds the target text
        gray = cv2.cvtColor(screenshot, cv2.COLOR_BGR2GRAY)

        # Always prepare upscaled version for small text
        g2x = cv2.resize(gray, (sw*2, sh*2), interpolation=cv2.INTER_CUBIC)
        g2x_blur = cv2.GaussianBlur(g2x, (3,3), 0)
        g2x_thresh = cv2.adaptiveThreshold(g2x_blur, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                           cv2.THRESH_BINARY, 15, 8)

        approaches = [
            (screenshot, 1, ""),              # raw color (fast, good for large text)
            (gray, 1, ""),                    # grayscale (good for dark backgrounds)
            (g2x, 2, ""),                     # 2x upscale (better for small text)
            (g2x_thresh, 2, "--psm 6"),       # 2x + threshold (last resort)
        ]

        data = None
        ocr_scale = 1
        for img, scale, config in approaches:
            try:
                kwargs = {"output_type": pytesseract.Output.DICT}
                if config:
                    kwargs["config"] = config
                d = pytesseract.image_to_data(img, **kwargs)
                words = [d["text"][j].strip() for j in range(len(d["text"])) if d["text"][j].strip()]
                logger.info(f"OCR find: scale={scale} words={words[:8]}")
                for j in range(len(d["text"])):
                    w = d["text"][j].strip()
                    if w and (text_lower in w.lower() or w.lower() in text_lower):
                        data = d
                        ocr_scale = scale
                        logger.info(f'OCR find: MATCH "{w}" in scale={scale}')
                        break
                if data:
                    break
                if not data:
                    data = d
                    ocr_scale = scale
            except Exception as e:
                logger.warning(f"OCR approach failed: {e}")
                continue

        if data is None:
            logger.warning("All OCR approaches failed")
            return None

        # Find matching text with dynamic confidence threshold
        # Larger text (taller bbox) → higher confidence expected
        # Smaller text → lower threshold to avoid rejecting valid matches
        best_match = None
        best_score = -1  # combined score: conf adjusted by size

        for i in range(len(data["text"])):
            word = data["text"][i].strip()
            conf = int(data["conf"][i]) if str(data["conf"][i]) != "-1" else -1
            if not word:
                continue

            h_px = data["height"][i] // ocr_scale
            # Dynamic threshold: large text (>30px) needs conf>=50
            # Small text (<15px) accepts conf>=10
            min_conf = max(10, min(50, h_px * 1.5))
            if conf < min_conf:
                continue

            if text_lower in word.lower() or word.lower() in text_lower:
                # Score combines confidence with text match quality
                score = conf
                if conf > best_score:
                    best_score = conf
                    best_match = {
                        "x": data["left"][i] // ocr_scale,
                        "y": data["top"][i] // ocr_scale,
                        "w": data["width"][i] // ocr_scale,
                        "h": data["height"][i] // ocr_scale,
                        "text": word,
                        "conf": conf,
                    }

        # Also try multi-word matching by combining consecutive words
        if not best_match:
            full_text = " ".join(w.strip() for w in data["text"] if w.strip())
            if text_lower in full_text.lower():
                # Find the position by scanning word positions
                running = ""
                start_idx = None
                for i in range(len(data["text"])):
                    word = data["text"][i].strip()
                    if not word:
                        running = ""
                        start_idx = None
                        continue
                    if start_idx is None:
                        start_idx = i
                    running = (running + " " + word).strip()
                    if text_lower in running.lower():
                        # Compute bounding box spanning start_idx to i (scale back)
                        x1 = min(data["left"][j] for j in range(start_idx, i + 1) if data["text"][j].strip()) // ocr_scale
                        y1 = min(data["top"][j] for j in range(start_idx, i + 1) if data["text"][j].strip()) // ocr_scale
                        x2 = max(data["left"][j] + data["width"][j] for j in range(start_idx, i + 1) if data["text"][j].strip()) // ocr_scale
                        y2 = max(data["top"][j] + data["height"][j] for j in range(start_idx, i + 1) if data["text"][j].strip()) // ocr_scale
                        best_match = {"x": x1, "y": y1, "w": x2 - x1, "h": y2 - y1, "text": running, "conf": 50}
                        break

        if not best_match:
            logger.info(f'OCR: "{text}" not found in screen text')
            return None

        cx = (best_match["x"] + best_match["w"] / 2.0) / sw
        cy = (best_match["y"] + best_match["h"] / 2.0) / sh
        # Stash bbox for find_text_bbox callers
        self._last_text_bbox = {
            "x1": best_match["x"] / sw,
            "y1": best_match["y"] / sh,
            "x2": (best_match["x"] + best_match["w"]) / sw,
            "y2": (best_match["y"] + best_match["h"]) / sh,
            "cx": cx,
            "cy": cy,
            "text": best_match["text"],
            "conf": best_match["conf"],
        }

        logger.info(f'OCR found "{best_match["text"]}" (conf={best_match["conf"]}, '
                    f'h={best_match["h"]}px) at ({cx:.4f}, {cy:.4f})')
        return (cx, cy)

    def find_text_bbox(self, screenshot_bytes: bytes, text: str) -> dict | None:
        """Like find_text but returns full bbox dict instead of just center point.

        Returns: {x1, y1, x2, y2, cx, cy, text, conf} or None.
        """
        self._last_text_bbox = None
        coords = self.find_text(screenshot_bytes, text)
        if coords is None:
            return None
        return self._last_text_bbox

    def find_all_text_bbox(self, screenshot_bytes: bytes, text: str) -> list[dict]:
        """Find ALL OCR matches for the given text. Returns list sorted by conf desc.

        Each entry: {x1, y1, x2, y2, cx, cy, text, conf}.
        """
        try:
            import pytesseract
        except ImportError:
            raise RuntimeError(
                "pytesseract not installed. Run: rm .venv/.phingr-cli-installed && bash setup.sh"
            )

        img_arr = np.frombuffer(screenshot_bytes, np.uint8)
        screenshot = cv2.imdecode(img_arr, cv2.IMREAD_COLOR)
        if screenshot is None:
            return []

        sh, sw = screenshot.shape[:2]
        text_lower = text.lower()
        gray = cv2.cvtColor(screenshot, cv2.COLOR_BGR2GRAY)
        g2x = cv2.resize(gray, (sw*2, sh*2), interpolation=cv2.INTER_CUBIC)
        g2x_blur = cv2.GaussianBlur(g2x, (3,3), 0)
        g2x_thresh = cv2.adaptiveThreshold(g2x_blur, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                            cv2.THRESH_BINARY, 15, 8)

        approaches = [
            (screenshot, 1, ""),
            (gray, 1, ""),
            (g2x, 2, ""),
            (g2x_thresh, 2, "--psm 6"),
        ]

        matches: list[dict] = []
        seen: set[tuple] = set()  # dedupe overlapping boxes from different approaches

        for img, scale, config in approaches:
            try:
                kwargs = {"output_type": pytesseract.Output.DICT}
                if config:
                    kwargs["config"] = config
                data = pytesseract.image_to_data(img, **kwargs)
            except Exception:
                continue

            for i in range(len(data["text"])):
                word = data["text"][i].strip()
                if not word:
                    continue
                conf = int(data["conf"][i]) if str(data["conf"][i]) != "-1" else -1
                h_px = data["height"][i] // scale
                min_conf = max(10, min(50, h_px * 1.5))
                if conf < min_conf:
                    continue
                if not (text_lower in word.lower() or word.lower() in text_lower):
                    continue

                x = data["left"][i] // scale
                y = data["top"][i] // scale
                w = data["width"][i] // scale
                h = data["height"][i] // scale
                # dedupe by rounded top-left
                key = (round(x / sw, 2), round(y / sh, 2))
                if key in seen:
                    continue
                seen.add(key)

                matches.append({
                    "x1": x / sw,
                    "y1": y / sh,
                    "x2": (x + w) / sw,
                    "y2": (y + h) / sh,
                    "cx": (x + w / 2) / sw,
                    "cy": (y + h / 2) / sh,
                    "text": word,
                    "conf": conf,
                })

        matches.sort(key=lambda m: m["conf"], reverse=True)
        logger.info(f'find_all_text "{text}": {len(matches)} matches')
        return matches

    def find_text_and_annotate(self, screenshot_bytes: bytes, text: str
                              ) -> tuple[tuple[float, float] | None, bytes]:
        """Find text via OCR and return annotated screenshot.

        Draws all detected OCR words in cyan, matching text in green
        with red crosshair at center.
        """
        try:
            import pytesseract
        except ImportError:
            raise RuntimeError(
                "pytesseract not installed. Run: rm .venv/.phingr-cli-installed && bash setup.sh"
            )

        img_arr = np.frombuffer(screenshot_bytes, np.uint8)
        screenshot = cv2.imdecode(img_arr, cv2.IMREAD_COLOR)
        if screenshot is None:
            return None, screenshot_bytes

        sh, sw = screenshot.shape[:2]
        text_lower = text.lower()

        # Try multiple approaches to find the target text
        gray = cv2.cvtColor(screenshot, cv2.COLOR_BGR2GRAY)
        g2x = cv2.resize(gray, (sw*2, sh*2), interpolation=cv2.INTER_CUBIC)
        g2x_blur = cv2.GaussianBlur(g2x, (3,3), 0)
        g2x_thresh = cv2.adaptiveThreshold(g2x_blur, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                           cv2.THRESH_BINARY, 15, 8)
        approaches = [
            (screenshot, 1, ""),
            (gray, 1, ""),
            (g2x, 2, ""),
            (g2x_thresh, 2, "--psm 6"),
        ]

        data = None
        ocr_scale = 1
        for img, scale, cfg in approaches:
            try:
                kwargs = {"output_type": pytesseract.Output.DICT}
                if cfg:
                    kwargs["config"] = cfg
                d = pytesseract.image_to_data(img, **kwargs)
                words = [d["text"][j].strip() for j in range(len(d["text"])) if d["text"][j].strip()]
                logger.info(f"OCR annotate: scale={scale} words={words[:8]}")
                for j in range(len(d["text"])):
                    w = d["text"][j].strip()
                    if w and (text_lower in w.lower() or w.lower() in text_lower):
                        data = d
                        ocr_scale = scale
                        logger.info(f'OCR annotate: MATCH "{w}" in scale={scale}')
                        break
                if data:
                    break
                if not data:
                    data = d
                    ocr_scale = scale
            except Exception as e:
                logger.warning(f"OCR annotate approach failed: {e}")
                continue

        if data is None:
            return None, screenshot_bytes

        annotated = screenshot.copy()
        found_coords = None

        # Draw all OCR words with dynamic threshold
        for i in range(len(data["text"])):
            word = data["text"][i].strip()
            conf = int(data["conf"][i]) if str(data["conf"][i]) != "-1" else -1
            if not word:
                continue
            h_px = data["height"][i] // ocr_scale
            min_conf = max(10, min(50, h_px * 1.5))
            if conf < min_conf:
                continue

            x = data["left"][i] // ocr_scale
            y = data["top"][i] // ocr_scale
            w = data["width"][i] // ocr_scale
            h = data["height"][i] // ocr_scale

            is_match = text_lower in word.lower() or word.lower() in text_lower

            if is_match and found_coords is None:
                # Green box + red crosshair for match
                cv2.rectangle(annotated, (x, y), (x + w, y + h), (0, 255, 0), 2)
                cx_px = x + w // 2
                cy_px = y + h // 2
                cv2.drawMarker(annotated, (cx_px, cy_px), (0, 0, 255), cv2.MARKER_CROSS, 20, 2)
                cv2.putText(annotated, f'OCR:"{word}" ({conf}%)',
                            (x, y - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
                found_coords = ((x + w / 2.0) / sw, (y + h / 2.0) / sh)
            else:
                # Cyan box for other OCR text
                cv2.rectangle(annotated, (x, y), (x + w, y + h), (255, 255, 0), 1)
                cv2.putText(annotated, word, (x, y - 3),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.3, (255, 255, 0), 1)

        if not found_coords:
            cv2.putText(annotated, f'OCR: "{text}" NOT FOUND',
                        (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

        _, buf = cv2.imencode('.jpg', annotated, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return found_coords, buf.tobytes()

    def _load_meta(self) -> dict:
        meta_path = self.templates_dir / "templates.json"
        if meta_path.exists():
            return json.loads(meta_path.read_text())
        return {}

    def _save_meta(self, meta: dict):
        meta_path = self.templates_dir / "templates.json"
        meta_path.write_text(json.dumps(meta, indent=2))
