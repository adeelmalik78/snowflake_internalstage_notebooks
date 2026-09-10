"""Deduplication engine: identifies and removes duplicate records from a dataset."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Iterable, Iterator


@dataclass(frozen=True)
class Record:
    id: str
    fields: dict


class DeduplicationEngine:
    """Detects duplicate records using a configurable set of fields as the dedup key."""

    def __init__(self, key_fields: Iterable[str]):
        self.key_fields = tuple(key_fields)
        self._seen_hashes: set[str] = set()

    def _hash_key(self, record: Record) -> str:
        key_values = "|".join(
            str(record.fields.get(field, "")).strip().lower() for field in self.key_fields
        )
        return hashlib.sha256(key_values.encode("utf-8")).hexdigest()

    def dedupe(self, records: Iterable[Record]) -> Iterator[Record]:
        """Yield only the first occurrence of each unique record, by key_fields."""
        for record in records:
            record_hash = self._hash_key(record)
            if record_hash not in self._seen_hashes:
                self._seen_hashes.add(record_hash)
                yield record

    def reset(self) -> None:
        """Clear dedup state so the engine can be reused on a new dataset."""
        self._seen_hashes.clear()


if __name__ == "__main__":
    sample_records = [
        Record(id="1", fields={"email": "alice@example.com", "name": "Alice"}),
        Record(id="2", fields={"email": "Alice@Example.com", "name": "Alice A."}),
        Record(id="3", fields={"email": "bob@example.com", "name": "Bob"}),
    ]

    engine = DeduplicationEngine(key_fields=["email"])
    unique_records = list(engine.dedupe(sample_records))

    print(f"Input: {len(sample_records)} records -> Output: {len(unique_records)} unique records")
    for record in unique_records:
        print(f"  {record.id}: {record.fields}")
