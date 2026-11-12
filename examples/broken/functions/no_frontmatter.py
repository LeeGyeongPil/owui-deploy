from pydantic import BaseModel


class Filter:
    class Valves(BaseModel):
        priority: int = 0

    def inlet(self, body: dict) -> dict:
        return body
