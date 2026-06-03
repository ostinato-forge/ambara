"""Public Ambara provider API."""

from ambara.core.pr_signals import CoordinationSignal, PRSignal
from ambara.git.config import PRSignalsConfig
from ambara.providers.errors import SignalProviderError
from ambara.providers.github_prs import fetch_all_signals as fetch_github_signals
from ambara.providers.jira_issues import fetch_all_signals as fetch_jira_signals
from ambara.providers.protocol import SignalProvider
from ambara.providers.signals import fetch_all_signals

__all__ = [
    "CoordinationSignal",
    "PRSignal",
    "PRSignalsConfig",
    "SignalProvider",
    "SignalProviderError",
    "fetch_all_signals",
    "fetch_github_signals",
    "fetch_jira_signals",
]
