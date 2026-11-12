"""
title: Two Classes
version: 0.1.0
"""


class Pipe:
    def pipe(self, body: dict) -> str:
        return "hello"


class Filter:
    def inlet(self, body: dict) -> dict:
        return body
