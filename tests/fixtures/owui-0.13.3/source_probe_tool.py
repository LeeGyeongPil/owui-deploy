"""
title: Probe Clock
author: probe
version: 0.1.0
requirements:
"""
from pydantic import BaseModel, Field


class Tools:
    class Valves(BaseModel):
        tz: str = Field(default="UTC", description="Time zone")

    def __init__(self):
        self.valves = self.Valves()

    def now(self) -> str:
        """Return a fixed string for the probe."""
        return "12:00 " + self.valves.tz
