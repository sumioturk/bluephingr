# Third-Party Licenses

phingr uses a number of open-source libraries. This document lists every
third-party dependency together with its license, so that commercial users
can satisfy the attribution requirements of the Apache-2.0, BSD, and MIT
licenses used by the upstream projects.

All dependencies are under **permissive licenses** (MIT, BSD, Apache-2.0,
HPND, MPL-2.0) or **dynamically-linked LGPL** (libcamera, on Raspberry Pi).
There are no copyleft obligations on phingr itself.

---

## phingr-cli (Python server + library)

| Package | Version | License | Source |
|---------|---------|---------|--------|
| `annotated-types` | 0.7.0 | MIT | https://github.com/annotated-types/annotated-types |
| `anyio` | 4.13.0 | MIT | https://github.com/agronholm/anyio |
| `certifi` | 2026.2.25 | MPL-2.0 | https://github.com/certifi/python-certifi |
| `click` | 8.3.2 | BSD-3-Clause | https://github.com/pallets/click |
| `exceptiongroup` | 1.3.1 | MIT | https://github.com/agronholm/exceptiongroup |
| `fastapi` | 0.115.6 | MIT | https://github.com/fastapi/fastapi |
| `h11` | 0.16.0 | MIT | https://github.com/python-hyper/h11 |
| `httpcore` | 1.0.9 | BSD-3-Clause | https://www.encode.io/httpcore/ |
| `httptools` | 0.7.1 | MIT | https://github.com/MagicStack/httptools |
| `httpx` | 0.28.1 | BSD-3-Clause | https://github.com/encode/httpx |
| `idna` | 3.11 | BSD-3-Clause | https://github.com/kjd/idna |
| `numpy` | 2.2.6 | BSD-3-Clause | https://numpy.org |
| `opencv-python-headless` | 4.13.0.92 | Apache-2.0 | https://github.com/opencv/opencv-python |
| `packaging` | 26.0 | Apache-2.0 OR BSD-2-Clause | https://github.com/pypa/packaging |
| `Pillow` | 12.2.0 | HPND (MIT-CMU) | https://python-pillow.github.io |
| `pydantic` | 2.10.0 | MIT | https://github.com/pydantic/pydantic |
| `pydantic-core` | 2.27.0 | MIT | https://github.com/pydantic/pydantic-core |
| `pytesseract` | 0.3.13 | Apache-2.0 | https://github.com/madmaze/pytesseract |
| `python-dotenv` | 1.2.2 | BSD-3-Clause | https://github.com/theskumar/python-dotenv |
| `python-multipart` | 0.0.22 | Apache-2.0 | https://github.com/Kludex/python-multipart |
| `PyYAML` | 6.0.3 | MIT | https://pyyaml.org/ |
| `starlette` | 0.41.3 | BSD-3-Clause | https://github.com/encode/starlette |
| `typing-extensions` | 4.15.0 | PSF-2.0 | https://github.com/python/typing_extensions |
| `uvicorn` | 0.34.0 | BSD-3-Clause | https://www.uvicorn.org/ |
| `uvloop` | 0.22.1 | MIT / Apache-2.0 | https://github.com/MagicStack/uvloop |
| `watchfiles` | 1.1.1 | MIT | https://github.com/samuelcolvin/watchfiles |
| `websockets` | 16.0 | BSD-3-Clause | https://github.com/python-websockets/websockets |

### System packages (installed by `setup.sh`)

| Package | License | Source |
|---------|---------|--------|
| **Tesseract OCR** | Apache-2.0 | https://github.com/tesseract-ocr/tesseract |

Tesseract is invoked as a subprocess via `pytesseract`; it is not linked or
bundled. Its `NOTICE` file is reproduced at
https://github.com/tesseract-ocr/tesseract/blob/main/NOTICE.

---

## phingr-device (Raspberry Pi)

### Python

| Package | License | Source |
|---------|---------|--------|
| `aiohttp` | Apache-2.0 | https://github.com/aio-libs/aiohttp |

### System packages (installed by `bootstrap.sh` from Raspberry Pi OS repos)

| Package | License | Source |
|---------|---------|--------|
| `python3-picamera2` | BSD-2-Clause | https://github.com/raspberrypi/picamera2 |
| `libcamera` | **LGPL-2.1-or-later** | https://libcamera.org |
| `python3-opencv` | Apache-2.0 | https://opencv.org |
| `git` | GPL-2.0 (tool, not linked) | https://git-scm.com |

**LGPL note for libcamera:** `picamera2` loads `libcamera` dynamically via
Python bindings. LGPL-2.1 permits dynamic linking without any copyleft
obligation on the calling code. If you redistribute a pre-built Raspberry
Pi SD-card image that bundles `libcamera`, you must include the full
LGPL-2.1 text and either ship the library's source alongside or provide a
written offer for it (see https://libcamera.org for the upstream source).
If your customers install phingr on their own Raspberry Pi OS via
`bootstrap.sh`, this obligation falls on Raspberry Pi OS, not on phingr.

---

## phingr-web (marketing site)

### Python

| Package | Version | License | Source |
|---------|---------|---------|--------|
| `fastapi` | 0.115.6 | MIT | https://github.com/fastapi/fastapi |
| `uvicorn[standard]` | 0.34.0 | BSD-3-Clause | https://www.uvicorn.org/ |
| `stripe` | 11.4.1 | MIT | https://github.com/stripe/stripe-python |

### Fonts

| Asset | License | Source |
|-------|---------|--------|
| **Roboto**, **Roboto Mono** | Apache-2.0 | https://fonts.google.com/specimen/Roboto |

Loaded at runtime from Google Fonts CDN
(`https://fonts.googleapis.com`). Google Fonts' terms of use permit
commercial use.

---

## License Texts

The full text of each license is available at:

- **MIT** — https://opensource.org/license/mit
- **BSD-2-Clause** — https://opensource.org/license/bsd-2-clause
- **BSD-3-Clause** — https://opensource.org/license/bsd-3-clause
- **Apache-2.0** — https://www.apache.org/licenses/LICENSE-2.0
- **LGPL-2.1** — https://www.gnu.org/licenses/old-licenses/lgpl-2.1.html
- **MPL-2.0** — https://www.mozilla.org/en-US/MPL/2.0/
- **HPND (Pillow)** — https://github.com/python-pillow/Pillow/blob/main/LICENSE
- **PSF-2.0** — https://docs.python.org/3/license.html

Upstream NOTICE files (required by Apache-2.0):

- **OpenCV** — https://github.com/opencv/opencv/blob/4.x/LICENSE
- **Tesseract** — https://github.com/tesseract-ocr/tesseract/blob/main/NOTICE
- **aiohttp** — https://github.com/aio-libs/aiohttp/blob/master/LICENSE.txt

---

## Attribution Statement

phingr redistributes and/or depends on the above open-source software.
Copyright belongs to the respective authors. Redistribution is permitted
under the terms of each project's license.
