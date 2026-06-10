#!/bin/bash
# test-ocr.sh — Test OCR text detection with visual output
#
# Usage:
#   bash util/test-ocr.sh http://phingr-device:8080 "Bluetooth"
#   bash util/test-ocr.sh http://phingr-device:8080

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV_PYTHON="$SCRIPT_DIR/.venv/bin/python3"

if [ ! -f "$VENV_PYTHON" ]; then
    echo "ERROR: venv not found. Run 'bash setup.sh' first."
    exit 1
fi

DEVICE_URL="${1:-http://localhost:8080}"
SEARCH_TEXT="${2:-}"

echo "Device:  $DEVICE_URL"
echo "Search:  ${SEARCH_TEXT:-<all text>}"
echo ""

cd "$SCRIPT_DIR"
"$VENV_PYTHON" - "$DEVICE_URL" "$SEARCH_TEXT" <<'PYEOF'
import sys, time, cv2, numpy as np

device_url = sys.argv[1]
search_text = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] else None

# 1. Get screenshot
import asyncio
from app.phingr_client import FkiosClient

async def get_screenshot():
    client = FkiosClient(base_url=device_url)
    img = await client.screenshot(crop=False)
    await client.close()
    return img

img_bytes = asyncio.run(get_screenshot())
img_arr = np.frombuffer(img_bytes, np.uint8)
screenshot = cv2.imdecode(img_arr, cv2.IMREAD_COLOR)
sh, sw = screenshot.shape[:2]
print(f"Screenshot: {sw}x{sh}")

# 2. Check tesseract
try:
    import pytesseract
    ver = pytesseract.get_tesseract_version()
    print(f"Tesseract version: {ver}")
except ImportError:
    print("ERROR: pytesseract not installed")
    sys.exit(1)
except Exception as e:
    print(f"ERROR: Tesseract not found: {e}")
    print("Install: brew install tesseract (macOS) or apt install tesseract-ocr (Linux)")
    sys.exit(1)

# 3. Try multiple approaches
approaches = [
    ("raw", screenshot, "--psm 3"),
    ("raw-psm6", screenshot, "--psm 6"),
    ("gray", cv2.cvtColor(screenshot, cv2.COLOR_BGR2GRAY), "--psm 6"),
    ("gray+blur", cv2.GaussianBlur(cv2.cvtColor(screenshot, cv2.COLOR_BGR2GRAY), (3,3), 0), "--psm 6"),
    ("2x+threshold", None, "--psm 6"),  # special handling below
]

# Build 2x+threshold image
gray = cv2.cvtColor(screenshot, cv2.COLOR_BGR2GRAY)
gray2x = cv2.resize(gray, (sw*2, sh*2), interpolation=cv2.INTER_CUBIC)
gray2x = cv2.GaussianBlur(gray2x, (3,3), 0)
thresh = cv2.adaptiveThreshold(gray2x, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 15, 8)
approaches[4] = ("2x+threshold", thresh, "--psm 6")

best_approach = None
best_words = 0

for name, img, config in approaches:
    t0 = time.time()
    try:
        data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT, config=config)
    except Exception as e:
        print(f"  [{name}] ERROR: {e}")
        continue

    words = [(data["text"][i].strip(), int(data["conf"][i]) if str(data["conf"][i]) != "-1" else -1)
             for i in range(len(data["text"]))
             if data["text"][i].strip() and (int(data["conf"][i]) if str(data["conf"][i]) != "-1" else -1) >= 20]

    elapsed = time.time() - t0
    print(f"  [{name}] {len(words)} words ({elapsed:.2f}s): {[w[0] for w in words[:10]]}")

    if len(words) > best_words:
        best_words = len(words)
        best_approach = name

    # Check for search text
    if search_text:
        for w, c in words:
            if search_text.lower() in w.lower():
                idx = next(i for i in range(len(data["text"])) if data["text"][i].strip() == w)
                x, y = data["left"][idx], data["top"][idx]
                w2, h2 = data["width"][idx], data["height"][idx]
                scale = 2 if "2x" in name else 1
                print(f"    FOUND: '{w}' conf={c} bbox=[{x//scale},{y//scale},{w2//scale},{h2//scale}]")

print(f"\nBest approach: {best_approach} ({best_words} words)")

# 4. Save annotated with best approach
if best_words > 0:
    # Re-run best approach for annotation
    for name, img, config in approaches:
        if name == best_approach:
            data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT, config=config)
            scale = 2 if "2x" in name else 1
            annotated = screenshot.copy()
            for i in range(len(data["text"])):
                word = data["text"][i].strip()
                conf = int(data["conf"][i]) if str(data["conf"][i]) != "-1" else -1
                if not word or conf < 20:
                    continue
                x = data["left"][i] // scale
                y = data["top"][i] // scale
                w = data["width"][i] // scale
                h = data["height"][i] // scale
                color = (0, 255, 0) if search_text and search_text.lower() in word.lower() else (255, 180, 0)
                cv2.rectangle(annotated, (x, y), (x+w, y+h), color, 1)
                cv2.putText(annotated, f'{word}({conf})', (x, y-4), cv2.FONT_HERSHEY_SIMPLEX, 0.35, color, 1)
            cv2.imwrite("/tmp/phingr-ocr-debug.jpg", annotated)
            print(f"Annotated image: /tmp/phingr-ocr-debug.jpg")
            break
else:
    cv2.imwrite("/tmp/phingr-ocr-debug.jpg", screenshot)
    print(f"Raw screenshot (no OCR results): /tmp/phingr-ocr-debug.jpg")
PYEOF
