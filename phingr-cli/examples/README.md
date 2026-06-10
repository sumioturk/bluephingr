# phingr-cli examples

## Python scripts

| Script | What it does |
|--------|--------------|
| `setup_bundle.py` | Import the example bundle (templates + flow + calibration) into a running server. Run this first. |
| `bt_toggle_stress.py` | 100-iteration BT toggle stress test using `PhingrSession`. Dynamic Python version of the Watch flow. |
| `dynamic_session.py` | Simple `PhingrSession` example — navigate to Settings and toggle Bluetooth once. |
| `lifecycle_test.py` | Full backup/restore cycle test: export → wipe → import → run. |

## Running the BT stress test

```bash
# 1. Start the phingr-cli server
cd phingr-cli && bash setup.sh run

# 2. Import the example bundle (one-time — loads 13 templates + Watch flow + calibration)
python examples/setup_bundle.py --server http://localhost:8800

# 3. Run the stress test
python examples/bt_toggle_stress.py --iterations 100
```

## What's in `bundle/watch-example.zip`

- **1 flow** — `watch.yaml` (reference, also usable from the web UI)
- **13 templates** — all the UI elements the stress test needs to find:
  `photo_widget`, `settings_icon`, `fit_icon`, `bt_header`,
  `bt_toggle_on`, `bt_toggle_off`, `bt_menu`, `watch_face_icon`,
  `info_icon`, `back_button_tl`, `back_tl`, `wallpaper_icon`,
  `settings_app_top`
- **Calibration** — screen handles + acceleration correction table

The templates were captured from a real device. If your phone renders
Settings differently (theme, language, model), you may need to re-capture
them via the web UI.

## YAML flows

| File | Description |
|------|-------------|
| `open-bluetooth.yaml` | Open Bluetooth Settings |
| `toggle-bluetooth.yaml` | Toggle the Bluetooth switch |
| `reset-home.yaml` | Return to home screen |
