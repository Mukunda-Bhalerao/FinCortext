"""Curated official macro datasets (RBI / MoSPI releases, transcribed).

Reads the versioned CSVs under data/macro/. Each value was verified against
the cited official publication; every row carries its own source URL and
release date (blank where the release date was not individually verified —
then available_at falls back to ingestion time, honestly).

This is NOT scraped data and NOT a live feed: re-ingesting the same file is
idempotent (deterministic observation ids), and updates arrive by committing
a new verified CSV version.
"""

from __future__ import annotations

import csv
import hashlib

from app.core.exceptions import ProviderError
from app.data.macro.indicators import curated_dir, get_indicator
from app.domain.contracts.providers import MacroDataProvider


class CuratedMacroProvider(MacroDataProvider):
    """Official macro history from versioned curated CSVs."""

    name = "curated_official"

    # indicator_id -> (csv filename, period column kind)
    _FILES = {
        "gdp_real_yoy": ("gdp_real_yoy.csv", "quarter"),
        "cpi_yoy": ("cpi_yoy.csv", "month"),
        "repo_rate": ("rbi_repo_rate.csv", "decision"),
    }

    def fetch_indicator(self, indicator_id: str) -> dict:
        meta = get_indicator(indicator_id)  # raises NotFoundError if unknown
        if indicator_id not in self._FILES:
            raise ProviderError(
                f"No curated dataset for indicator '{indicator_id}'.",
                details={"provider": self.name},
            )
        filename, kind = self._FILES[indicator_id]
        path = curated_dir() / filename
        if not path.is_file():
            raise ProviderError(
                f"Curated dataset missing: {filename}.",
                details={"provider": self.name},
            )
        try:
            text = path.read_text(encoding="utf-8-sig")
        except OSError as exc:
            raise ProviderError(
                f"Cannot read curated dataset {filename}: {exc}",
                details={"provider": self.name},
            ) from exc
        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        points, warnings = self._parse_rows(text, kind, filename)
        return {
            "indicator_id": indicator_id,
            "unit": meta["unit"],
            "source_name": meta["source_name"],
            "points": points,
            "warnings": warnings,
            "content_hash": content_hash,
        }

    def _parse_rows(self, text: str, kind: str, filename: str) -> tuple[list[dict], list[str]]:
        points: list[dict] = []
        warnings: list[str] = []
        lines = [line for line in text.splitlines() if line.strip() and not line.startswith("#")]
        if not lines:
            raise ProviderError(
                f"Curated dataset {filename} has no data rows.",
                details={"provider": self.name},
            )
        reader = csv.DictReader(lines)
        expected = (
            {"effective_date", "rate_pct"}
            if kind == "decision"
            else {"yoy_pct", "base_year"} | ({"month"} if kind == "month" else {"period_end"})
        )
        actual = set(reader.fieldnames or [])
        if not expected <= actual:
            raise ProviderError(
                f"Curated dataset {filename} has an unexpected header: "
                f"missing {sorted(expected - actual)}.",
                details={"provider": self.name},
            )
        required = {"rate_pct", "yoy_pct"} if kind == "decision" else {"yoy_pct"}
        for lineno, row in enumerate(reader, start=2):
            try:
                if kind == "decision":
                    value = float(row["rate_pct"])
                    period = (row.get("effective_date") or "").strip()
                    point = {
                        "period_start": None,
                        "period_end": period or None,
                        "value": value,
                        "published_at": period or None,
                        "source_url": (row.get("source_url") or "").strip() or None,
                        "notes": self._note(row, ("stance", "notes")),
                    }
                else:
                    value = float(row["yoy_pct"])
                    period = self._period_end(row, kind)
                    point = {
                        "period_start": None,
                        "period_end": period,
                        "value": value,
                        "published_at": (row.get("release_date") or "").strip() or None,
                        "source_url": (row.get("source_url") or "").strip() or None,
                        "notes": self._note(
                            row,
                            ("base_year", "quarter_label")
                            if kind == "quarter"
                            else ("base_year",),
                        ),
                    }
            except (KeyError, TypeError, ValueError) as exc:
                warnings.append(f"{filename}:{lineno}: unparseable row skipped ({exc}).")
                continue
            points.append(point)
        if not points and not warnings:
            warnings.append(f"{filename}: no data rows found.")
        return points, warnings

    @staticmethod
    def _period_end(row: dict, kind: str) -> str | None:
        if kind == "quarter":
            return (row.get("period_end") or "").strip() or None
        month = (row.get("month") or "").strip()  # YYYY-MM
        if len(month) == 7 and month[4] == "-":
            year, mon = int(month[:4]), int(month[5:7])
            import calendar

            last = calendar.monthrange(year, mon)[1]
            return f"{month}-{last:02d}"
        return None

    @staticmethod
    def _note(row: dict, keys: tuple[str, ...]) -> str | None:
        parts = [f"{k}={row[k].strip()}" for k in keys if (row.get(k) or "").strip()]
        return "; ".join(parts) or None
