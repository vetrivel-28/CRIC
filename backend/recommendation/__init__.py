"""
Recommendation module export shim for backward compatibility.
"""

from backend.recommendation_engine import (
    CandidateScore,
    DatasetPaths,
    RecommendationEngine,
    RecommendationRequest,
    RecommendationResult,
)

__all__ = [
    "CandidateScore",
    "DatasetPaths",
    "RecommendationEngine",
    "RecommendationRequest",
    "RecommendationResult",
]
