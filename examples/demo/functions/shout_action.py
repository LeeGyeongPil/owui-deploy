"""
title: Shout
version: 0.1.0
"""
from pydantic import BaseModel


class Action:
    class Valves(BaseModel):
        suffix: str = "!"

    def __init__(self):
        self.valves = self.Valves()

    async def action(self, body: dict, __event_emitter__=None) -> None:
        last = body["messages"][-1]["content"]
        if __event_emitter__:
            await __event_emitter__({"type": "message", "data": {"content": last.upper() + self.valves.suffix}})
