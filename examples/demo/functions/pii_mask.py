"""
title: PII Mask
version: 0.1.0
description: Mask e-mail addresses before the model sees them
"""
import re

from pydantic import BaseModel
from utils.misc import get_last_user_message


class Filter:
    class Valves(BaseModel):
        api_key: str = ""
        priority: int = 0

    def __init__(self):
        self.valves = self.Valves()

    def inlet(self, body: dict, __user__: dict | None = None) -> dict:
        message = get_last_user_message(body["messages"])
        if message:
            body["messages"][-1]["content"] = re.sub(r"[\w.]+@[\w.]+", "[email]", message)
        return body
