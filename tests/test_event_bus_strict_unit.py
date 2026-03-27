import unittest

from sage.orchestrator.event_bus import EventBus
from sage.protocol.schemas import Event


class TestEventBusStrictOrder(unittest.TestCase):
    def test_fifo_order_on_emit_sync(self):
        bus = EventBus()
        seen: list[str] = []

        def h1(ev: Event) -> None:
            seen.append(ev.payload.get("id", ""))

        bus.subscribe("TEST", h1)

        bus.emit_sync(Event(type="TEST", task_id="t", payload={"id": "1"}, timestamp=""))
        bus.emit_sync(Event(type="TEST", task_id="t", payload={"id": "2"}, timestamp=""))

        self.assertEqual(seen, ["1", "2"])

    def test_reentrant_emit_sync_from_handler(self):
        """Handler emits second event; must not deadlock (inline path)."""
        bus = EventBus()
        calls: list[str] = []

        def inner(_ev: Event) -> None:
            calls.append("inner")

        def outer(ev: Event) -> None:
            calls.append("outer")
            bus.emit_sync(
                Event(type="INNER", task_id="t", payload={}, timestamp=""),
            )

        bus.subscribe("OUTER", outer)
        bus.subscribe("INNER", inner)

        bus.emit_sync(Event(type="OUTER", task_id="t", payload={}, timestamp=""))

        self.assertEqual(calls, ["outer", "inner"])


if __name__ == "__main__":
    unittest.main()
