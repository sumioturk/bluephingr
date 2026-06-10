"""DSL execution engine — runs Flow commands sequentially."""

import asyncio
import json
import logging

from . import config
from .dsl import Flow, Command, CommandError, ExecutionContext
from .phingr_client import FkiosClient, DeviceError
from .template_matcher import TemplateMatcher
from .models import FlowRunStatus

logger = logging.getLogger("phingr-cli")


class Engine:
    def __init__(self, flow: Flow, phingr: FkiosClient):
        self.flow = flow
        self.phingr = phingr

        self.running = False
        self._stop_requested = False
        self.current_command = 0
        self.status = "pending"
        self._log: list[str] = []
        self.last_annotated: bytes | None = None

    def _log_msg(self, msg: str):
        logger.info(msg)
        self._log.append(msg)

    def stop(self):
        self._stop_requested = True

    def get_status(self) -> FlowRunStatus:
        return FlowRunStatus(
            flow_name=self.flow.name,
            current_command=self.current_command,
            total_commands=len(self.flow.commands),
            status=self.status,
            log=list(self._log),
        )

    async def _execute_with_cancel(self, cmd: Command, ctx: ExecutionContext):
        task = asyncio.create_task(cmd.execute(ctx))
        while not task.done():
            if self._stop_requested:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                raise CommandError("Stopped by user")
            await asyncio.sleep(0.1)
        return task.result()

    async def run(self):
        self.running = True
        self.status = "running"
        self._log_msg(f"Starting flow: {self.flow.name} ({len(self.flow.commands)} commands)")

        self.phingr.on_api_call = self._log_msg

        # Fetch screen handles from device
        self._log_msg("Fetching calibration from device...")
        await self.phingr.fetch_calibration()
        if not self.phingr._screen_rect:
            # Fallback: load from local calibration.json (from imported bundle)
            calib_file = config.DATA_DIR / "calibration.json"
            if calib_file.exists():
                self._log_msg("Using saved calibration from bundle")
                calib = json.loads(calib_file.read_text())
                if calib.get("handles"):
                    self.phingr._screen_rect = calib["handles"]
                if calib.get("table"):
                    self.phingr._calib_table = calib["table"]
        if self.phingr._screen_rect:
            self._log_msg("Screen handles loaded")
        else:
            self._log_msg("No handles — falling back to detect_screen")
            await self.phingr.detect_screen()
        if not self.phingr._screen_rect:
            self._log_msg("WARNING: No screen rect — coordinates may be off")

        # Template matcher
        templates_dir = config.DATA_DIR / "templates"
        matcher = TemplateMatcher(templates_dir)
        template_count = len(matcher.list_templates())
        self._log_msg(f"Templates: {template_count} registered")

        ctx = ExecutionContext(
            phingr=self.phingr,
            matcher=matcher,
            log=self._log_msg,
            stop_requested=lambda: self._stop_requested,
            set_annotated=lambda img: setattr(self, 'last_annotated', img),
        )

        try:
            for i, cmd in enumerate(self.flow.commands):
                if self._stop_requested:
                    self.status = "failed"
                    self._log_msg("Stopped by user")
                    break

                self.current_command = i
                self._log_msg(f"[{i+1}/{len(self.flow.commands)}] {cmd}")

                await self._execute_with_cancel(cmd, ctx)
                await asyncio.sleep(0.3)
            else:
                self.status = "success"
                self._log_msg("Flow completed successfully")

        except CommandError as e:
            self.status = "failed"
            self._log_msg(f"FAILED: {e}")
        except DeviceError as e:
            self.status = "failed"
            self._log_msg(f"DEVICE ERROR: {e}")
        except Exception as e:
            logger.exception(f"Engine exception: {e}")
            self.status = "failed"
            self._log_msg(f"EXCEPTION: {e}")
        finally:
            self.running = False
            self.phingr.on_api_call = None
            self._log_msg(f"Flow finished: {self.status}")
