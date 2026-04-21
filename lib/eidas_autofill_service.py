"""Service that provides sequential eIDAS test data from CSV."""

import csv
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import TypedDict


class EidasRow(TypedDict):
    rnokpp: str
    family_name: str
    given_name: str
    birthday: str


class EidasAutofillPayload(TypedDict):
    first_name: str
    last_name: str
    date_of_birth: str
    identifier: str
    level_of_assurance: str


class EidasAutofillService:
    """Loads eIDAS records from CSV and returns next record on each call."""

    def __init__(self, csv_path: Path):
        self._csv_path = csv_path
        self._records = self._load_records(csv_path)
        self._index = 0
        self._lock = Lock()

    def _load_records(self, csv_path: Path) -> list[EidasRow]:
        if not csv_path.exists():
            raise ValueError(f"CSV file not found: {csv_path}")

        records: list[EidasRow] = []
        with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            required = {"RNOKPP", "FamilyName", "GivenName", "Birthday"}
            if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
                raise ValueError("CSV has invalid headers for eIDAS autofill")

            for row in reader:
                rnokpp = str(row.get("RNOKPP") or "").strip()
                family_name = str(row.get("FamilyName") or "").strip()
                given_name = str(row.get("GivenName") or "").strip()
                birthday = str(row.get("Birthday") or "").strip()

                if not (rnokpp and family_name and given_name and birthday):
                    continue

                records.append(
                    {
                        "rnokpp": rnokpp,
                        "family_name": family_name,
                        "given_name": given_name,
                        "birthday": birthday,
                    }
                )

        if not records:
            raise ValueError("CSV does not contain valid eIDAS records")

        return records

    def _normalize_date(self, value: str) -> str:
        value = value.strip()
        for date_format in ("%d.%m.%Y", "%Y-%m-%d"):
            try:
                parsed = datetime.strptime(value, date_format)
                return parsed.strftime("%Y-%m-%d")
            except ValueError:
                continue
        return value

    def get_next_payload(self) -> EidasAutofillPayload:
        """Returns next record and moves index forward (cyclic)."""
        with self._lock:
            row = self._records[self._index]
            self._index = (self._index + 1) % len(self._records)

        return {
            "first_name": row["given_name"],
            "last_name": row["family_name"],
            "date_of_birth": self._normalize_date(row["birthday"]),
            "identifier": f"UA/UA/{row['rnokpp'].zfill(10)}",
            "level_of_assurance": "High",
        }

