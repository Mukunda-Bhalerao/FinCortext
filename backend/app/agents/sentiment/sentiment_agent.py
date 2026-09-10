"""Sentiment Analyst — news sentiment scoring with standardized AgentOutput.

Consumes canonical data via repositories (never providers):
- NewsRepository: stored articles (associated with the entity) + persistence
  of per-article SentimentResults.

The sentiment model is injected (FinBERT wrapper in production, fakes in
tests) — the agent is decoupled from any specific model/provider.

Behavior:
- No stored articles            -> UNAVAILABLE (score None, explicit limitation)
- No RELEVANT articles          -> UNAVAILABLE (explicit limitation)
- Model unavailable/failed      -> UNAVAILABLE (explicit limitation; the
  backend never crashes on model problems)
- 1–2 relevant articles         -> DEGRADED (score computed, thin evidence)
- ≥ 3 relevant articles         -> OK

Relevance (see relevance.py): an article counts only with BOTH a company
identity hit (legal name / curated alias / ticker) AND financial/business
context, and never when it is about an excluded topic (brand sponsorships).
Counts (stored / relevant / rejected-by-reason) are reported in provenance
and limitations so the screening itself is auditable.

Determinism: same stored articles + same model outputs ⇒ identical output.
Aggregation is anchored to the latest article timestamp, not the wall clock.
See methodology.py for the documented formulas.
"""

from __future__ import annotations

from app.agents.base.base_agent import BaseAgent
from app.agents.sentiment.methodology import (
    FULL_COVERAGE_ARTICLES,
    MIN_ARTICLES_FOR_OK,
    aggregate,
)
from app.agents.sentiment.relevance import assess_relevance
from app.core.exceptions import ModelUnavailableError
from app.core.logging import get_logger
from app.data.universe.universe_config import get_universe_entry
from app.domain.models.agent_output import (
    AgentEvidence,
    AgentFactor,
    AgentId,
    AgentOutput,
    Signal,
    signal_from_score,
)
from app.domain.models.news import SentimentResult
from app.repositories.agent_output_repository import AgentOutputRepository
from app.repositories.news_repository import NewsRepository

logger = get_logger("agents.sentiment")

MAX_ARTICLES_ANALYZED = 100


def clean_text(*parts: str | None) -> str:
    """Whitespace-collapse and join non-empty parts (deterministic)."""
    joined = " ".join((p or "").strip() for p in parts if p and p.strip())
    return " ".join(joined.split())


class SentimentAgent(BaseAgent):
    agent_id = AgentId.SENTIMENT_ANALYST

    def __init__(
        self,
        news_repo: NewsRepository,
        output_repo: AgentOutputRepository | None = None,
        model=None,
    ):
        super().__init__(output_repo)
        self.news_repo = news_repo
        self.model = model  # FinBERTSentimentModel or equivalent (injectable)

    # ------------------------------------------------------------------

    def analyze(self, symbol: str) -> AgentOutput:
        entry = get_universe_entry(symbol)
        entity = entry.symbol

        articles = self.news_repo.get_articles(entity, limit=MAX_ARTICLES_ANALYZED)
        if not articles:
            return self._unavailable_output(
                entity,
                "No stored news articles for this company yet. Use Fetch news "
                "on the Sentiment Analyst page (needs a configured news "
                "provider), then re-run — nothing is scored until real "
                "articles exist.",
                provenance={"methodology": "sentiment_analyst_v1", "articles_stored": 0},
            )

        relevant = []
        rejected_by_reason: dict[str, int] = {
            "no_identity": 0,
            "no_financial_context": 0,
            "excluded_topic": 0,
        }
        rejected_examples: list[str] = []
        for a in articles:
            verdict = assess_relevance(a.title, a.description, a.content, entry)
            if verdict.relevant:
                relevant.append(a)
            else:
                rejected_by_reason[verdict.reason] = (
                    rejected_by_reason.get(verdict.reason, 0) + 1
                )
                if len(rejected_examples) < 2:
                    rejected_examples.append((a.title or "")[:80])
        articles_rejected = len(articles) - len(relevant)
        relevance_note = (
            f"{len(relevant)} relevant of {len(articles)} stored "
            f"({articles_rejected} excluded: "
            f"{rejected_by_reason.get('no_identity', 0)} no company mention, "
            f"{rejected_by_reason.get('no_financial_context', 0)} no "
            f"financial/business context, "
            f"{rejected_by_reason.get('excluded_topic', 0)} excluded topic)"
        )
        if not relevant:
            if rejected_by_reason.get("no_identity", 0) == len(articles):
                limitation = (
                    f"{len(articles)} stored article(s) contain no mention of "
                    f"{entry.name} / {entity} — no relevant evidence to score "
                    "(nothing fabricated)."
                )
            else:
                examples = "; ".join(f"'{t}'" for t in rejected_examples if t)
                limitation = (
                    f"No analyzable evidence for {entity}: {relevance_note}."
                    + (f" Excluded examples — e.g. {examples}." if examples else "")
                    + " Nothing fabricated."
                )
            return self._unavailable_output(
                entity,
                limitation,
                provenance={
                    "methodology": "sentiment_analyst_v1",
                    "articles_stored": len(articles),
                    "articles_relevant": 0,
                    "articles_rejected": articles_rejected,
                    "rejected_no_identity": rejected_by_reason.get("no_identity", 0),
                    "rejected_no_financial_context": rejected_by_reason.get(
                        "no_financial_context", 0
                    ),
                    "rejected_excluded_topic": rejected_by_reason.get(
                        "excluded_topic", 0
                    ),
                },
            )

        texts = [clean_text(a.title, a.description) for a in relevant]
        try:
            model_results = self.model.analyze(texts)
        except ModelUnavailableError as exc:
            return self._unavailable_output(
                entity,
                f"Sentiment model unavailable: {exc.message}",
                provenance={
                    "methodology": "sentiment_analyst_v1",
                    "articles_stored": len(articles),
                    "articles_relevant": len(relevant),
                    "model_id": getattr(self.model, "model_id", "unknown"),
                },
            )

        # Build per-article scored records + persist SentimentResults.
        scored: list[dict] = []
        results: list[SentimentResult] = []
        for article, mr in zip(relevant, model_results):
            scored.append(
                {
                    "article_id": article.article_id,
                    "published_at": article.published_at,
                    "label": mr["label"],
                    "positive": mr["positive"],
                    "neutral": mr["neutral"],
                    "negative": mr["negative"],
                    "model_confidence": mr["confidence"],
                }
            )
            results.append(
                SentimentResult(
                    article_id=article.article_id,
                    entity_id=entity,
                    label=mr["label"],  # type: ignore[arg-type]
                    positive_probability=mr["positive"],
                    neutral_probability=mr["neutral"],
                    negative_probability=mr["negative"],
                    model_id=getattr(self.model, "model_id", "unknown"),
                    model_confidence=mr["confidence"],
                )
            )
        self.news_repo.save_sentiment_results(results)

        agg = aggregate(scored)
        score = agg["score"]
        confidence = agg["confidence"]
        distribution = agg["distribution"]
        components = agg["confidence_components"]

        status = "OK" if len(relevant) >= MIN_ARTICLES_FOR_OK else "DEGRADED"
        limitations = self._build_limitations(
            articles, relevant, agg, relevance_note, rejected_examples
        )

        factors = [
            AgentFactor(
                name="news_volume",
                description="Number of relevant articles analyzed (coverage)",
                value=float(len(relevant)),
                weight=None,
                contribution=round(components["coverage"] * 100, 1),
                available=True,
                detail=f"{relevance_note} "
                f"(full coverage at {FULL_COVERAGE_ARTICLES} articles) "
                f"→ coverage {components['coverage']:.0%}",
            ),
            AgentFactor(
                name="model_confidence",
                description="Mean predicted-label probability of the sentiment model",
                value=components["model_confidence"],
                weight=None,
                contribution=round(components["model_confidence"] * 100, 1),
                available=True,
                detail=f"mean model confidence {components['model_confidence']:.0%}",
            ),
            AgentFactor(
                name="sentiment_consistency",
                description="Agreement between article polarities (1 − std-dev)",
                value=components["consistency"],
                weight=None,
                contribution=round(components["consistency"] * 100, 1),
                available=True,
                detail=f"polarity dispersion across {len(relevant)} articles "
                f"→ consistency {components['consistency']:.0%}",
            ),
            AgentFactor(
                name="recency",
                description="Weight share of articles within one half-life (7d)",
                value=components["recency"],
                weight=None,
                contribution=round(components["recency"] * 100, 1),
                available=True,
                detail=f"fresh weight share {components['recency']:.0%} "
                "(recency-weighted aggregation, 7-day half-life)",
            ),
        ]

        evidence = [
            AgentEvidence(
                data_type="news_article",
                reference=f"{a.article_id}",
                source_name=a.source or a.source_name,
                source_type=a.source_type.value,
                timestamp=a.published_at,
                note=f"{a.title[:120]}{'…' if len(a.title) > 120 else ''}"
                + (f" ({a.source_url})" if a.source_url else ""),
            )
            for a in relevant[:5]
        ]

        rationale = self._build_rationale(entry.name, score, confidence, distribution, len(relevant))

        return AgentOutput(
            agent_id=self.agent_id,
            entity_id=entity,
            score=score,
            signal=signal_from_score(score),
            confidence=confidence,
            factors=factors,
            rationale=rationale,
            evidence=evidence,
            data_limitations=limitations,
            provenance={
                "methodology": "sentiment_analyst_v1",
                "model_id": getattr(self.model, "model_id", "unknown"),
                "articles_stored": len(articles),
                "articles_relevant": len(relevant),
                "articles_rejected": articles_rejected,
                "rejected_no_identity": rejected_by_reason.get("no_identity", 0),
                "rejected_no_financial_context": rejected_by_reason.get(
                    "no_financial_context", 0
                ),
                "rejected_excluded_topic": rejected_by_reason.get(
                    "excluded_topic", 0
                ),
                "reference_ts": agg["reference_ts"].isoformat(),
                "latest_article_date": agg["reference_ts"].date().isoformat(),
                "weighted_mean_polarity": agg["weighted_mean_polarity"],
                "confidence_components": agg["confidence_components"],
            },
            status=status,
        )

    # -- helpers ---------------------------------------------------------------

    def _unavailable_output(self, entity: str, limitation: str, provenance: dict) -> AgentOutput:
        return AgentOutput(
            agent_id=self.agent_id,
            entity_id=entity,
            score=None,
            signal=Signal.UNAVAILABLE,
            confidence=0.0,
            factors=[],
            rationale=f"Sentiment analysis for {entity} is unavailable: {limitation}",
            evidence=[],
            data_limitations=[limitation],
            provenance=provenance,
            status="UNAVAILABLE",
        )

    @staticmethod
    def _build_limitations(articles, relevant, agg, relevance_note, rejected_examples) -> list[str]:
        limitations: list[str] = [relevance_note + "."]
        examples = [t for t in rejected_examples if t]
        if examples:
            limitations.append(
                "Excluded as non-financial/off-topic — e.g. "
                + "; ".join(f"'{t}'" for t in examples)
                + ". Only company-specific financial/business news is scored."
            )
        if len(relevant) < FULL_COVERAGE_ARTICLES:
            limitations.append(
                f"Only {len(relevant)} relevant article(s) analyzed — coverage "
                f"is partial (full coverage at {FULL_COVERAGE_ARTICLES})."
            )
        if any(a.published_at is None for a in relevant):
            limitations.append(
                "Some articles lack publication timestamps and received full "
                "recency weight."
            )
        if len(relevant) < MIN_ARTICLES_FOR_OK:
            limitations.append(
                "Thin evidence: fewer than 3 relevant articles — treat the "
                "score as indicative only."
            )
        limitations.append(
            "Sentiment reflects news tone only; it is not investment advice "
            "and excludes fundamentals, price action, and macro factors."
        )
        limitations.append(
            "FinBERT is trained on English financial text; non-English or "
            "heavily garbled article text may score unreliably."
        )
        return limitations

    @staticmethod
    def _build_rationale(name, score, confidence, distribution, n_relevant) -> str:
        dominant = max(distribution, key=distribution.get)
        return (
            f"News sentiment for {name}: score {score:.0f}/100 (confidence "
            f"{confidence:.0%}) from {n_relevant} relevant article(s). "
            f"Weighted distribution — positive {distribution['positive']:.0%}, "
            f"neutral {distribution['neutral']:.0%}, negative "
            f"{distribution['negative']:.0%}; dominant: {dominant}. "
            "Aggregation is recency-weighted (7-day half-life) and deterministic."
        )
