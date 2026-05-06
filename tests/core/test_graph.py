from __future__ import annotations

from jurati.core.graph import build_entry_graph, parse_wiki_links, validate_entry_links
from jurati.core.index import Index
from jurati.core.schema import Sensitivity

from .conftest import make_entry


def test_parse_wiki_links_supports_labels_and_fragments() -> None:
    links = parse_wiki_links(
        "See [[target-entry]], [[workflow-entry|the workflow]], "
        "[[decision-entry#notes]], and ![[embedded-image]]."
    )

    assert [(link.target, link.label) for link in links] == [
        ("target-entry", None),
        ("workflow-entry", "the workflow"),
        ("decision-entry", None),
    ]


def test_parse_wiki_links_ignores_code_examples() -> None:
    links = parse_wiki_links(
        "Use [[real-target]], not `[[inline-example]]`.\n\n"
        "```text\n[[fenced-example]]\n```\n\n"
        "Then read [[next-target]]."
    )

    assert [link.target for link in links] == ["real-target", "next-target"]


def test_build_entry_graph_reports_outgoing_and_backlinks() -> None:
    source = make_entry(
        entry_id="source-entry",
        body="Use [[target-entry]] and [[target-entry|again]].",
    )
    target = make_entry(entry_id="target-entry")
    index = Index(entries={entry.frontmatter.id: entry for entry in [source, target]})

    graph = build_entry_graph(index)

    assert graph.outgoing["source-entry"] == ("target-entry",)
    assert graph.backlinks["target-entry"] == ("source-entry",)
    assert graph.links_for("target-entry") == {
        "outgoing": [],
        "backlinks": ["source-entry"],
        "broken": [],
    }
    assert graph.restricted_entry_ids == frozenset()


def test_build_entry_graph_tracks_restricted_entry_ids() -> None:
    restricted = make_entry(entry_id="restricted-entry", sensitivity=Sensitivity.RESTRICTED)
    index = Index(entries={restricted.frontmatter.id: restricted})

    graph = build_entry_graph(index)

    assert graph.restricted_entry_ids == frozenset({"restricted-entry"})


def test_validate_entry_links_reports_unresolved_and_invalid_targets() -> None:
    source = make_entry(
        entry_id="source-entry",
        body="See [[missing-entry]] and [[Bad Target]].",
    )
    index = Index(entries={source.frontmatter.id: source})

    errors = validate_entry_links(index)

    assert "projects/source-entry.md: unresolved wiki link to 'missing-entry'" in errors
    assert (
        "projects/source-entry.md: wiki link target 'Bad Target' is not a valid entry id" in errors
    )
