from functools import lru_cache

import pandas as pd

from .settings import DEMO_DATA_PATH


class DemoData:
    def __init__(self) -> None:
        if not DEMO_DATA_PATH.exists():
            raise FileNotFoundError(f"시연 데이터가 없습니다: {DEMO_DATA_PATH}")
        frame = pd.read_csv(DEMO_DATA_PATH, low_memory=False)
        self.records = frame.where(pd.notna(frame), None).to_dict(orient="records")

    def __len__(self) -> int:
        return len(self.records)

    def at(self, index: int) -> dict:
        if not self.records:
            raise ValueError("시연 데이터가 비어 있습니다.")
        return self.records[index % len(self.records)]


@lru_cache(maxsize=1)
def get_demo_data() -> DemoData:
    return DemoData()

