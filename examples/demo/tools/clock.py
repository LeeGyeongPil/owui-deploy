"""
title: Clock
author: demo
version: 0.2.0
description: Tell the model the current time
"""
from datetime import datetime, timezone

from pydantic import BaseModel, Field


class Tools:
    class Valves(BaseModel):
        use_utc: bool = Field(default=True, description="Report UTC instead of local time")

    def __init__(self):
        self.valves = self.Valves()

    def now(self) -> str:
        """Return the current date and time as an ISO 8601 string."""
        moment = datetime.now(timezone.utc) if self.valves.use_utc else datetime.now()
        return moment.isoformat()
