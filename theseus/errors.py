"""The errors Theseus raises. Every module raises one of these, never a bare Exception."""

from __future__ import annotations


class TheseusError(Exception):
    """Base class for every error Theseus raises on purpose."""


class IngestError(TheseusError):
    """A plan, a .tf file, a workflow or service code could not be read into graph rows."""


class PatchError(TheseusError):
    """A patch op cannot apply to the resources; the candidate's verdict becomes invalid."""


class GraphError(TheseusError):
    """FalkorDB refused a query, or a graph is missing or inconsistent."""


class ModelError(TheseusError):
    """The LLM or Jev failed, returned an invalid answer, or has no recording to replay."""


class GitHubError(TheseusError):
    """A GitHub API call failed, or a request was refused for permissions or scope."""
