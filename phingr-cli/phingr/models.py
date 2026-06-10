"""Pydantic data models for phingr-cli."""

from pydantic import BaseModel


class FlowInfo(BaseModel):
    filename: str
    name: str
    device_url: str
    command_count: int


class FlowRunStatus(BaseModel):
    flow_name: str
    current_command: int
    total_commands: int
    status: str  # "running", "success", "failed"
    log: list[str] = []
