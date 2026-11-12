"""
title: Secret Default
version: 0.1.0
"""
from pydantic import BaseModel


class Filter:
    class Valves(BaseModel):
        api_key: str = "sk-live-0000-not-a-real-key"

    def inlet(self, body: dict) -> dict:
        return body
