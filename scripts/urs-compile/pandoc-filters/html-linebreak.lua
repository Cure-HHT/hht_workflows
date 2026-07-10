-- html-linebreak.lua — turn a raw HTML `<br>` into a real line break.
--
-- GFM pipe-table cells are single-line, so authored markdown that needs a
-- line break inside a cell (e.g. the event catalog's "entry_type then its
-- display name below" cell) writes `<br>`. Pandoc reads `<br>` as a raw
-- inline HTML element, which BOTH the docx and the LaTeX writers drop — so
-- the break silently vanishes from the URS PDF and .docx while still
-- rendering on GitHub. Rewriting it to a pandoc LineBreak makes the break
-- render in every target (LineBreak is format-agnostic).
--
-- Applies to all targets: LineBreak is portable, and a markdown/gfm writer
-- would just reproduce a hard break. Handles `<br>`, `<br/>`, `<br />`
-- (any spacing/casing).

function RawInline(el)
  if el.format == 'html' then
    local s = el.text:gsub('%s', ''):lower()
    if s == '<br>' or s == '<br/>' then
      return pandoc.LineBreak()
    end
  end
  return nil
end
