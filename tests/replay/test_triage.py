"""Jev's urgency for the compromised Action, GHSA-demo-0001 (docs/spec/02-demo-world.md,
"compromised-action"), replayed from recordings/jev/: never the network.

Record or refresh the recording with the TypeSafe key in .env:

    THESEUS_MODE=record pytest -q tests/replay/test_triage.py
"""

from __future__ import annotations

from theseus.agent.jev import Jev
from theseus.agent.llm import Llm
from theseus.config import get_settings

# The advisory's own words: untrusted text.
FINDING = (
    "GHSA-demo-0001: the GitHub Action demo-thirdparty/file-diff was compromised. Versions v1, v2 and v3 run"
    " code that prints the workflow's secrets and tokens to the build log. Modeled on the tj-actions"
    " compromise (CVE-2025-30066)."
)
# What the graph engine found: trusted.
BLAST = (
    "Matched workflows: docs-site/preview.yml (staging, id-token: write) and website/lint.yml, both on v3."
    " Assuming preview.yml is compromised, it reaches s3://demo-company-files/invoices/ (confidential),"
    " secret:prod-db-credentials (regulated) and db:customer-db (regulated). The database is five hops away:"
    " the Action, preview.yml, role github-deploy, role prod-support, the secret, the database."
    " website/lint.yml reaches nothing."
)


def test_the_urgency_of_the_advisory_is_a_calibrated_probability() -> None:
    settings = get_settings()
    answer = Jev(settings, llm=Llm(settings)).urgency(FINDING, BLAST)
    assert answer.type == "noul" and answer.noul is not None and 0.0 <= answer.noul <= 1.0
    assert (answer.source, answer.calibrated) == ("jev", True)
    assert answer.noul >= 0.5, (
        f"a path from a compromised Action to the customer database rated {answer.noul}"
    )
