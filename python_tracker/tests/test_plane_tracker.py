from __future__ import annotations

from types import SimpleNamespace

from plane_tracker import AIRPLANE_CLASS_ID, AIRPLANE_LABEL, extract_detections


class FakeTensor:
    def __init__(self, values):
        self.values = values

    def cpu(self):
        return self

    def int(self):
        if isinstance(self.values, list):
            return FakeTensor([int(value) for value in self.values])
        return FakeTensor(int(self.values))

    def tolist(self):
        return self.values


def test_extract_detections_returns_tracked_airplanes_only() -> None:
    boxes = SimpleNamespace(
        xyxy=FakeTensor([[10.123, 20.456, 30.789, 40.987], [1, 2, 3, 4]]),
        conf=FakeTensor([0.92345, 0.5]),
        cls=FakeTensor([AIRPLANE_CLASS_ID, 0]),
        id=FakeTensor([7, 99]),
    )
    result = SimpleNamespace(boxes=boxes)

    detections = extract_detections(result)

    assert detections == [
        {
            "track_id": 7,
            "label": AIRPLANE_LABEL,
            "bbox": [10.12, 20.46, 30.79, 40.99],
            "confidence": 0.9234,
        }
    ]


def test_extract_detections_skips_untracked_boxes() -> None:
    boxes = SimpleNamespace(
        xyxy=FakeTensor([[10, 20, 30, 40]]),
        conf=FakeTensor([0.9]),
        cls=FakeTensor([AIRPLANE_CLASS_ID]),
        id=None,
    )
    result = SimpleNamespace(boxes=boxes)

    assert extract_detections(result) == []
