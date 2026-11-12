"""
title: Probe Filter
version: 0.1.0
"""
from pydantic import BaseModel
from utils.misc import get_last_user_message


class Filter:
    class Valves(BaseModel):
        api_key: str = ""
        priority: int = 0

    class UserValves(BaseModel):
        enabled: bool = True

    def __init__(self):
        self.valves = self.Valves()

    def inlet(self, body: dict, __user__: dict | None = None) -> dict:
        return body
