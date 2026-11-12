"""
title: Bad Valves
version: 0.1.0
"""


class Filter:
    class Valves:
        priority: int = 0

    def inlet(self, body: dict) -> dict:
        return body
