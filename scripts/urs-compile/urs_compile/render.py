"""Render GraphNodes to markdown for the URS PDF compile."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import jinja2

from .graph_loader import Graph, GraphNode


@dataclass(frozen=True)
class RenderConfig:
    """Per-sponsor toggles for which REQ sections appear in the rendered URS.

    Loaded from the ``urs_render:`` block of ``spec/URS-manifest/sponsor-info.yaml``
    on the consumer repo. Missing keys keep the defaults below (everything
    visible), so existing sponsors don't need to update their config to
    preserve current behaviour."""
    show_refines_satisfies: bool = True
    show_rationale: bool = True

    @classmethod
    def from_sponsor_info(cls, sponsor_info: dict) -> "RenderConfig":
        block = (sponsor_info or {}).get("urs_render") or {}
        return cls(
            show_refines_satisfies=bool(block.get("show_refines_satisfies", True)),
            show_rationale=bool(block.get("show_rationale", True)),
        )


_TABLE_AFTER_PROSE_RE = re.compile(
    r"(?<!\n)\n(\|[^\n]+\|[ \t]*\n[ \t]*\|[ \t]*[:\-| \t]+\|)"
)


def _restore_table_blank_line(text: str) -> str:
    """Insert a blank line before a markdown pipe table that sits flush against
    preceding prose. elspais's assertion parser concatenates the table into the
    assertion label with single newlines; pandoc then renders the table rows as
    literal text instead of a table. Detect the table-header + separator-row
    pattern and prepend a blank line so pandoc recognises it.
    """
    return _TABLE_AFTER_PROSE_RE.sub(r"\n\n\1", text)


_TEMPLATE_DIR = Path(__file__).parent / "templates"
_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(_TEMPLATE_DIR),
    autoescape=False,
    trim_blocks=True,
    lstrip_blocks=True,
)


def render_remainder(node: GraphNode) -> str:
    return node.content.get("text", "")


def render_requirement(node: GraphNode, graph: Graph,
                       config: RenderConfig = RenderConfig(),
                       primary_label: str | None = None) -> str:
    """Render a REQUIREMENT node to markdown.

    `primary_label` marks this REQ as a secondary member of a merged
    level-3 section (a PRD/GUI twin sharing one kebab name). Instead of
    a numbered `### Title` heading — which would add a TOC entry, a
    section number, and a page break — the REQ opens with a horizontal
    rule and, when its title differs from the group's primary title, a
    bold title paragraph.

    Walks `node.children` once in source order so each ASSERTION lands
    immediately under whichever REMAINDER subheading preceded it. This
    preserves the source author's grouping (e.g. `**Trigger**` / `**Suppression**`
    bold paragraphs inside an Assertions block keep their lettered
    assertions adjacent rather than collapsing all assertions into one
    flat list).

    Output layout (when children are interleaved):
      ### Title  {#req-id}
      **REQ ID:** `req-id`
      **Refines:** `...`
      #### Overview
      <text>
      #### Assertions
      #### Trigger
      **A.** <text>
      **B.** <text>
      #### Suppression
      **C.** <text>
      #### Rationale
      <rationale>

    If an ASSERTION appears before any "Assertions"-labelled REMAINDER,
    an implicit `#### Assertions` heading is emitted to anchor it. If no
    Rationale REMAINDER is present in the children, the REQ's
    `content.rationale` is emitted at the end as a fallback (elspais
    surfaces some rationale prose only via that field).
    """
    # Header (heading + REQ ID + Refines/Satisfies edges) — Jinja handles these.
    template = _env.get_template("req.md.j2")
    header = template.render(
        node=node, config=config, primary_label=primary_label,
    ).rstrip()

    body_parts: list[str] = [header]
    saw_rationale_remainder = False

    def _is_subgroup(child: GraphNode) -> bool:
        """Bold-paragraph subgroup heading inside the Assertions block.

        elspais parses `**Trigger**` style bold paragraphs (no markdown
        heading marker) as REMAINDERs with `heading` set, `heading_level`
        unset, and empty body text. These are subgroup labels for the
        lettered assertions that follow them.
        """
        if child.kind != "REMAINDER":
            return False
        if child.content.get("heading_level") is not None:
            return False
        if not (child.content.get("heading") or "").strip():
            return False
        if (child.content.get("text") or "").strip():
            return False
        return True

    # Pre-scan to locate where the Assertions block starts. The block
    # begins at the first ASSERTION OR the first subgroup-style REMAINDER
    # (whichever comes first). Source authors put `### Assertions` before
    # `**Trigger**` etc., but elspais flattens that heading away — emit an
    # implicit `#### Assertions` here so subgroup H5s sit under it.
    assertions_start_idx: int | None = None
    for idx, child_id in enumerate(node.children):
        if not graph.has_node(child_id):
            continue
        child = graph.get_node(child_id)
        if child.kind == "ASSERTION" or _is_subgroup(child):
            assertions_start_idx = idx
            break
    emitted_assertions_header = assertions_start_idx is None

    for idx, child_id in enumerate(node.children):
        if not graph.has_node(child_id):
            continue
        child = graph.get_node(child_id)

        if idx == assertions_start_idx and not emitted_assertions_header:
            body_parts.append("\n\n#### Assertions {.unnumbered}\n")
            emitted_assertions_header = True

        if child.kind == "REMAINDER":
            heading = (child.content.get("heading") or "").strip()
            text = (child.content.get("text") or "").strip()
            heading_level = child.content.get("heading_level")
            heading_lower = heading.lower()
            if heading_lower == "assertions":
                emitted_assertions_header = True
            if heading_lower == "rationale":
                saw_rationale_remainder = True
                if not config.show_rationale:
                    # Skip the rationale REMAINDER entirely (heading + text)
                    # when the sponsor hides rationale.
                    continue
            if heading:
                # `heading_level` set -> source `### Heading` / `## Heading`
                # (varies by repo authoring style; both surface as REQ
                # sub-sections). Render at H4 so it sits one level under
                # the REQ's H3 title.
                # `heading_level is None` -> source bold-paragraph subgroup
                # (e.g. `**Trigger**` inside an Assertions block) -> emit
                # as an italic paragraph rather than a heading. Headings
                # would pollute the outline / TOC and visually compete with
                # the `#### Assertions` parent; an italic label is a soft
                # subgroup marker.
                if heading_level is not None:
                    body_parts.append(f"\n\n#### {heading} {{.unnumbered}}\n")
                else:
                    body_parts.append(f"\n\n*{heading}*\n")
            if text:
                body_parts.append(f"\n{text}\n")

        elif child.kind == "ASSERTION":
            label = child.content.get("label") or "?"
            text = _restore_table_blank_line((child.label or "").strip())
            # Render as a pandoc alphabetic ordered-list item (`A.  text`).
            # LaTeX backend turns a sequence of these into a single
            # `\begin{enumerate}\def\labelenumi{\Alph{enumi}.}...\end{enumerate}`
            # block. enumerate's default geometry puts the label at the
            # left margin and aligns the hanging continuation indent with
            # the start of the first line of text — which is the visual
            # the user asked for. Bold/italic styling of the label is
            # controlled by the LaTeX template's `\labelenumi`
            # redefinition; see tools/urs-template.latex.
            body_parts.append(f"\n{label}.  {text}\n")

    # Fallback: emit content.rationale only when the children didn't
    # already supply a Rationale REMAINDER (avoids duplicate sections).
    if config.show_rationale and not saw_rationale_remainder:
        rationale = (node.content.get("rationale") or "").strip()
        if rationale:
            body_parts.append("\n\n#### Rationale {.unnumbered}\n")
            body_parts.append(f"\n{rationale}\n")

    return "".join(body_parts).rstrip() + "\n"


def render_node(node: GraphNode, graph: Graph | None = None,
                config: RenderConfig = RenderConfig(),
                primary_label: str | None = None) -> str:
    if node.kind == "REMAINDER":
        return render_remainder(node)
    if node.kind == "REQUIREMENT":
        if graph is None:
            raise ValueError("render_node requires a Graph for REQUIREMENT nodes")
        return render_requirement(node, graph, config, primary_label=primary_label)
    raise ValueError(f"Cannot render node kind {node.kind!r}")
