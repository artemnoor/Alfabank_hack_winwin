"""Offline experimental event resolution prototype for Framework v1."""

from .resolution import CandidateMatch, ResolutionPolicy, propose_resolution, retrieve_candidates

__all__ = [
    "CandidateMatch",
    "ResolutionPolicy",
    "propose_resolution",
    "retrieve_candidates",
]
