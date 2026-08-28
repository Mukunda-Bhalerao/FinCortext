# FinCortext — Agent Contracts

## AgentOutput — the standardized contract

Every FinCortext agent emits exactly one output type:
`app/domain/models/agent_output.py::AgentOutput`.

```python
AgentOutput:
    agent_id: AgentId            # firm_analyst | industry_analyst | sentiment_analyst
                                 # (macro_analyst / portfolio_agent reserved, not emitted)
    entity_id: str               # internal symbol, e.g. "RELIANCE"

    score: float | None          # bounded 0–100; None only when status=UNAVAILABLE
    signal: Signal               # strong_buy | buy | neutral | sell | strong_sell | unavailable
    confidence: float            # 0–1, derived from data completeness/quality — never random

    factors: list[AgentFactor]   # named contributions with value/weight/contribution/detail
    rationale: str               # deterministic human-readable explanation
    evidence: list[AgentEvidence]# references to underlying data rows/documents
    data_limitations: list[str]  # explicit missing-data / quality statements

    generated_at: datetime
    data_version: str
    provenance: dict             # source names, content hashes, row counts
    status: str                  # OK | DEGRADED | UNAVAILABLE
```

### AgentFactor

| field | meaning |
|---|---|
| name | stable factor key, e.g. `profitability` |
| description | what the factor measures |
| value | raw computed value (None when data missing) |
| weight | configured weight (documented, not magic) |
| contribution | weighted points added to the score |
| available | False when the factor could not be computed |
| detail | human-readable computation explanation |

### Score → Signal mapping (all agents)

| score | signal |
|---|---|
| ≥ 70 | strong_buy |
| 55–70 | buy |
| 45–55 | neutral |
| 30–45 | sell |
| < 30 | strong_sell |

Implemented in `signal_from_score()`; identical for every agent.

## Agent rules

1. **Deterministic only.** Same inputs → same output. No randomness, no LLM
   generation of conclusions.
2. **Source-agnostic.** Agents read canonical data via repositories; they never
   call yfinance/NewsAPI/other providers directly.
3. **Honest missing data.** Unavailable metrics are never fabricated. Missing
   factors reduce the evidence base and lower confidence; limitations are listed.
4. **Confidence is earned.** Confidence reflects data completeness, recency,
   volume, and consistency — documented per agent.
5. **Persistence.** Every run is stored in `agent_outputs` (via
   `AgentOutputRepository`) for history and future Portfolio Agent consumption.

## Per-agent methodology

- **Firm Analyst** — see `backend/app/agents/firm/methodology.py` (weights,
  formulas, confidence rules documented in code and in the module docstring).
- **Industry Analyst** — peer/sector relative methodology documented in
  `backend/app/agents/industry/`.
- **Sentiment Analyst** — FinBERT probabilities + deterministic time-aware
  aggregation documented in `backend/app/agents/sentiment/`.

## Future Portfolio Agent integration

The Portfolio Agent (not implemented) will:

1. Read the latest `AgentOutput` per (agent, entity).
2. Weight scores by confidence and status.
3. Apply the future risk/constraint engine and optimizer.

No agent-to-agent calls exist; the contract is the only coupling.