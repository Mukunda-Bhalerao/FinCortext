"""Repository for news articles and sentiment results."""

from __future__ import annotations

from datetime import datetime

from app.data.storage.duckdb_storage import DuckDBStorage
from app.domain.models.news import NewsArticle, SentimentLabel, SentimentResult


class NewsRepository:
    def __init__(self, storage: DuckDBStorage):
        self.storage = storage

    def save_articles(self, articles: list[NewsArticle]) -> int:
        """Insert articles, skipping duplicates by article_id. Returns saved count."""
        saved = 0
        for a in articles:
            exists = self.storage.fetch_all(
                "SELECT article_id FROM news_articles WHERE article_id = ? LIMIT 1",
                [a.article_id],
            )
            if exists:
                continue
            self.storage.execute(
                """
                INSERT INTO news_articles
                (article_id, entity_id, title, description, content, source,
                 source_url, published_at, collected_at, language, content_hash,
                 source_type, source_name)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    a.article_id,
                    a.entity_id,
                    a.title,
                    a.description,
                    a.content,
                    a.source,
                    a.source_url,
                    a.published_at,
                    a.collected_at,
                    a.language,
                    a.content_hash,
                    a.source_type.value,
                    a.source_name,
                ],
            )
            saved += 1
        return saved

    def get_articles(
        self,
        entity_id: str,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 200,
    ) -> list[NewsArticle]:
        sql = "SELECT * FROM news_articles WHERE entity_id = ?"
        params: list = [entity_id.upper()]
        if start is not None:
            sql += " AND published_at >= ?"
            params.append(start)
        if end is not None:
            sql += " AND published_at <= ?"
            params.append(end)
        sql += " ORDER BY published_at DESC LIMIT ?"
        params.append(limit)
        rows = self.storage.fetch_all(sql, params)
        return [
            NewsArticle(
                article_id=r["article_id"],
                title=r["title"],
                description=r["description"],
                content=r["content"],
                source=r["source"],
                source_url=r["source_url"],
                published_at=r["published_at"],
                collected_at=r["collected_at"],
                language=r["language"],
                entity_id=r["entity_id"],
                content_hash=r["content_hash"],
                source_type=r["source_type"],
                source_name=r["source_name"],
            )
            for r in rows
        ]

    def count(self, entity_id: str | None = None) -> int:
        if entity_id:
            rows = self.storage.fetch_all(
                "SELECT COUNT(*) AS n FROM news_articles WHERE entity_id = ?",
                [entity_id.upper()],
            )
        else:
            rows = self.storage.fetch_all("SELECT COUNT(*) AS n FROM news_articles")
        return int(rows[0]["n"]) if rows else 0

    # -- sentiment results ------------------------------------------------------

    def save_sentiment_results(self, results: list[SentimentResult]) -> int:
        if not results:
            return 0
        rows = [
            (
                s.article_id,
                s.entity_id,
                s.label.value,
                s.positive_probability,
                s.neutral_probability,
                s.negative_probability,
                s.model_id,
                s.model_confidence,
                s.scored_at,
            )
            for s in results
        ]
        self.storage.connect().executemany(
            """
            INSERT OR REPLACE INTO sentiment_results
            (article_id, entity_id, label, positive_probability,
             neutral_probability, negative_probability, model_id,
             model_confidence, scored_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        return len(rows)

    def get_sentiment_results(
        self,
        entity_id: str,
        start: datetime | None = None,
    ) -> list[SentimentResult]:
        sql = "SELECT * FROM sentiment_results WHERE entity_id = ?"
        params: list = [entity_id.upper()]
        if start is not None:
            sql += " AND scored_at >= ?"
            params.append(start)
        rows = self.storage.fetch_all(sql, params)
        return [
            SentimentResult(
                article_id=r["article_id"],
                entity_id=r["entity_id"],
                label=SentimentLabel(r["label"]),
                positive_probability=r["positive_probability"],
                neutral_probability=r["neutral_probability"],
                negative_probability=r["negative_probability"],
                model_id=r["model_id"],
                model_confidence=r["model_confidence"],
                scored_at=r["scored_at"],
            )
            for r in rows
        ]