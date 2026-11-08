"""USD cost estimates from persisted usage + config/llm_pricing.json."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

from .store import UsageRecord

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PRICING_PATH = REPO_ROOT / "config" / "llm_pricing.json"


def model_rate_key(provider: str, model: str) -> str:
    """Stable lookup key used in llm_pricing.json."""
    return f"{provider}:{model}"


@dataclass(frozen=True)
class ModelRate:
    input_per_1m: float
    output_per_1m: float


@dataclass(frozen=True)
class PricingTable:
    currency: str
    unit: str
    label: str
    as_of: str
    source: str
    mock_policy: str
    models: dict[str, ModelRate]

    def rate_for(self, provider: str, model: str) -> Optional[ModelRate]:
        return self.models.get(model_rate_key(provider, model))


@dataclass(frozen=True)
class CostLine:
    purpose: str
    provider: str
    model: str
    mock: bool
    calls: int
    tokens_in: int
    tokens_out: int
    estimated_usd: float | None
    status: str  # priced | mock_zero | unpriced

    def to_dict(self) -> dict[str, Any]:
        return {
            "purpose": self.purpose,
            "provider": self.provider,
            "model": self.model,
            "mock": self.mock,
            "calls": self.calls,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "estimated_usd": self.estimated_usd,
            "status": self.status,
        }


@dataclass(frozen=True)
class CostSummary:
    case_id: str
    currency: str
    label: str
    pricing_as_of: str
    pricing_source: str
    llm_calls: int
    tokens_in: int
    tokens_out: int
    estimated_usd: float
    unpriced_calls: int
    mock_calls: int
    lines: tuple[CostLine, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "currency": self.currency,
            "label": self.label,
            "pricing_as_of": self.pricing_as_of,
            "pricing_source": self.pricing_source,
            "llm_calls": self.llm_calls,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "estimated_usd": round(self.estimated_usd, 8),
            "unpriced_calls": self.unpriced_calls,
            "mock_calls": self.mock_calls,
            "lines": [line.to_dict() for line in self.lines],
        }


def load_pricing(path: Path | str | None = None) -> PricingTable:
    """Load the offline USD pricing snapshot. Never invents missing model rates."""
    target = Path(path) if path is not None else DEFAULT_PRICING_PATH
    if not target.is_file():
        raise FileNotFoundError(f"LLM pricing file not found: {target}")
    raw = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"LLM pricing must be a JSON object: {target}")
    currency = str(raw.get("currency") or "")
    if currency != "USD":
        raise ValueError(f"Only USD pricing is supported (human decision 2026-11-08); got {currency!r}")
    models_raw = raw.get("models")
    if not isinstance(models_raw, dict) or not models_raw:
        raise ValueError("LLM pricing.models must be a non-empty object")
    models: dict[str, ModelRate] = {}
    for key, value in models_raw.items():
        if not isinstance(value, dict):
            raise ValueError(f"pricing model {key!r} must be an object")
        models[str(key)] = ModelRate(
            input_per_1m=float(value["input_per_1m"]),
            output_per_1m=float(value["output_per_1m"]),
        )
    return PricingTable(
        currency=currency,
        unit=str(raw.get("unit") or "per_1m_tokens"),
        label=str(raw.get("label") or "estimate"),
        as_of=str(raw.get("as_of") or ""),
        source=str(raw.get("source") or ""),
        mock_policy=str(raw.get("mock_policy") or "zero_cost"),
        models=models,
    )


def _line_cost(tokens_in: int, tokens_out: int, rate: ModelRate) -> float:
    return (tokens_in / 1_000_000.0) * rate.input_per_1m + (tokens_out / 1_000_000.0) * rate.output_per_1m


def estimate_case_cost(
    case_id: str,
    records: Iterable[UsageRecord],
    pricing: PricingTable | None = None,
) -> CostSummary:
    """Pure estimate: sum tokens and USD from usage rows + pricing table."""
    table = pricing if pricing is not None else load_pricing()
    buckets: dict[tuple[str, str, str, bool], dict[str, Any]] = {}
    rows = list(records)
    for row in rows:
        key = (row.purpose, row.provider, row.model, row.mock)
        bucket = buckets.setdefault(
            key,
            {
                "calls": 0,
                "tokens_in": 0,
                "tokens_out": 0,
            },
        )
        bucket["calls"] += 1
        bucket["tokens_in"] += int(row.tokens_in)
        bucket["tokens_out"] += int(row.tokens_out)

    lines: list[CostLine] = []
    total_usd = 0.0
    unpriced = 0
    mock_calls = 0
    for (purpose, provider, model, mock), bucket in sorted(buckets.items()):
        calls = int(bucket["calls"])
        tin = int(bucket["tokens_in"])
        tout = int(bucket["tokens_out"])
        if mock and table.mock_policy == "zero_cost":
            mock_calls += calls
            lines.append(
                CostLine(
                    purpose=purpose,
                    provider=provider,
                    model=model,
                    mock=True,
                    calls=calls,
                    tokens_in=tin,
                    tokens_out=tout,
                    estimated_usd=0.0,
                    status="mock_zero",
                )
            )
            continue
        rate = table.rate_for(provider, model)
        if rate is None:
            unpriced += calls
            lines.append(
                CostLine(
                    purpose=purpose,
                    provider=provider,
                    model=model,
                    mock=mock,
                    calls=calls,
                    tokens_in=tin,
                    tokens_out=tout,
                    estimated_usd=None,
                    status="unpriced",
                )
            )
            continue
        usd = _line_cost(tin, tout, rate)
        total_usd += usd
        lines.append(
            CostLine(
                purpose=purpose,
                provider=provider,
                model=model,
                mock=mock,
                calls=calls,
                tokens_in=tin,
                tokens_out=tout,
                estimated_usd=round(usd, 8),
                status="priced",
            )
        )

    return CostSummary(
        case_id=case_id,
        currency=table.currency,
        label=table.label,
        pricing_as_of=table.as_of,
        pricing_source=table.source,
        llm_calls=len(rows),
        tokens_in=sum(r.tokens_in for r in rows),
        tokens_out=sum(r.tokens_out for r in rows),
        estimated_usd=total_usd,
        unpriced_calls=unpriced,
        mock_calls=mock_calls,
        lines=tuple(lines),
    )
