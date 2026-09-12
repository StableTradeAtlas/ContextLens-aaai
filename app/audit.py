from __future__ import annotations

from app.models import RetrievalResult


FINANCIAL_TERMS = [
    "stablecoin",
    "stable value",
    "crypto",
    "token",
    "payment",
    "稳定币",
    "稳定价值",
    "投资",
    "交易",
    "买入",
    "卖出",
    "收益",
    "支付部署",
    "监管建议",
    "结算系统",
    "跨境支付",
]


def audit_answer(question: str, answer: dict, evidence: list[RetrievalResult], latency_ms: int | None = None) -> dict:
    has_citations = bool(evidence) and all(r.record.source_uri for r in evidence[:3])
    asks_finance = any(term.lower() in question.lower() for term in FINANCIAL_TERMS)
    live_count = sum(1 for r in evidence if r.record.is_live_api)
    official_snapshot_count = sum(
        1 for r in evidence if r.record.lineage.get("source_mode") == "verified_official_snapshot"
    )
    verified_count = live_count + official_snapshot_count
    seed_count = sum(
        1 for r in evidence
        if "seed" in r.record.evidence_type.lower() or bool(r.record.raw.get("demo_seed"))
    )
    citation_coverage = round(sum(1 for r in evidence if r.record.source_uri) / len(evidence), 2) if evidence else 0.0
    if verified_count == 0:
        uncertainty = "needs_verified_official_data"
    elif seed_count:
        uncertainty = "mixed_live_and_seed"
    else:
        uncertainty = "normal"
    failure_mode = "none" if evidence else "no_retrieval_match"
    warnings = []
    if not has_citations:
        warnings.append("No strong citation set found. Treat answer as exploratory.")
    if asks_finance:
        warnings.append("Question touches stablecoin/payment/finance. Answer must remain educational and non-advisory.")
    if uncertainty == "needs_verified_official_data":
        warnings.append("Current evidence lacks verified official records; keep conclusions exploratory.")
    elif uncertainty == "mixed_live_and_seed":
        warnings.append("Answer combines live API records with demo seed records. Prefer all-live evidence before use.")
    return {
        "citation_check": "pass" if has_citations else "review",
        "citation_coverage": citation_coverage,
        "financial_advice_check": "guarded" if asks_finance else "pass",
        "uncertainty_level": uncertainty,
        "evidence_count": len(evidence),
        "live_records": live_count,
        "official_snapshot_records": official_snapshot_count,
        "verified_official_records": verified_count,
        "seed_records": seed_count,
        "latency_ms": latency_ms,
        "failure_mode": failure_mode,
        "warnings": warnings,
    }
