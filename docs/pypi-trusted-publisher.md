# PyPI Trusted Publisher Setup

Ambara publishes to PyPI from GitHub Actions using PyPI trusted publishing.
That means the GitHub workflow is only half of the setup. PyPI must also be
configured to trust this repository, workflow file, and environment.

## Exact Publisher Values

Configure PyPI to trust these claims:

- project/name: `ambara`
- owner: `ostinato-forge`
- repository: `ambara`
- workflow filename: `release.yml`
- GitHub environment: `pypi`

Those values must match the release workflow in
`.github/workflows/release.yml`.

## If The `ambara` Project Already Exists On PyPI

Add an ordinary trusted publisher on the PyPI project:

1. Open the `ambara` project on PyPI.
2. Go to `Manage` -> `Publishing`.
3. Add a new trusted publisher for GitHub Actions.
4. Enter the exact values above.

## If The `ambara` Project Does Not Exist On PyPI Yet

Add a pending trusted publisher:

1. Open `https://pypi.org/manage/account/publishing/`.
2. Add a new pending publisher for GitHub Actions.
3. Enter the same exact values above, including the project name `ambara`.

The first successful trusted publish will create the project.

## After The Publisher Is Configured

You do not need to retag the release.

Either rerun the failed tag workflow from GitHub, or dispatch the release
workflow manually against the tag:

```bash
gh workflow run release.yml \
  --repo ostinato-forge/ambara \
  --ref main \
  -f ref=refs/tags/v0.8.0
```

After publish succeeds, verify from a clean environment:

```bash
python3.12 -m venv /tmp/ambara-pypi-smoke
/tmp/ambara-pypi-smoke/bin/python -m pip install --upgrade pip
/tmp/ambara-pypi-smoke/bin/python -m pip install ambara==0.8.0
/tmp/ambara-pypi-smoke/bin/ambara --version
```

## Failure Signature

If PyPI is not configured correctly yet, the publish job fails with an
`invalid-publisher` error and shows the rendered GitHub claims. Compare those
claims to the values above and fix the mismatch on PyPI before rerunning.
