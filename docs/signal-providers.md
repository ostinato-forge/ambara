# Writing A Signal Provider

Ambara ships built-in GitHub and GitLab review providers, plus Jira issue
signals. Additional providers can be packaged separately and registered through
Python entry points.

## Entry Point

Expose a callable or object with `fetch_signals(config, token=None)`, then add
it to the `ambara.signal_providers` entry-point group:

```toml
[project.entry-points."ambara.signal_providers"]
linear = "ambara_linear:provider"
```

The entry-point name is the provider id used by `AMBARA_SIGNAL_PROVIDER`.
Provider ids are normalized to lowercase and hyphens.

## Return Shape

Return a sequence of `ambara.core.pr_signals.CoordinationSignal` objects. Keep
provider output sanitized before returning it:

- Do not return raw secrets, credentials, or private body text.
- Prefer short excerpts over full descriptions.
- Populate `subject_refs` or `subject_areas` when the signal touches known
  files or subsystems.
- Use stable `signal_id` values so Ambara can reason about repeated signals.

## Minimal Provider

```python
from ambara.core.pr_signals import CoordinationSignal


class LinearProvider:
    provider_id = "linear"
    display_name = "Linear"

    def fetch_signals(self, config, token=None) -> list[CoordinationSignal]:
        return []


provider = LinearProvider()
```

## Local Verification

After installing your provider package in the same environment as Ambara:

```bash
AMBARA_SIGNAL_PROVIDER=linear \
AMBARA_PR_SIGNAL_REPOS=team/backend \
ambara startup --goal "continue backend handoff"
```

Unknown providers fail clearly instead of falling back to GitHub, so a typo in
`AMBARA_SIGNAL_PROVIDER` should be visible immediately.
