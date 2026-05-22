-- pandoc-filters/image-normalize.lua
--
-- Per-format image normalisation:
--
-- LaTeX (PDF) — force every Image that pandoc wraps in a figure to use
-- `[H]` placement (the `float` package's "here, and only here"
-- specifier) so figures can't migrate forward to a different page,
-- stranding the introducing "Screen reference / See:" caption text
-- behind on the previous page. Width is handled by the template's
-- `\setkeys{Gin}{width=0.5\textwidth}` Gin default, not here.
--
-- docx — set a uniform image width on every Image so screenshots
-- don't render at their native pixel resolution (which often blows
-- past the printable page area). Anything already carrying a width
-- attribute is left alone so per-image overrides keep working.

local DOCX_IMAGE_WIDTH = "4in"

local function is_latex()
  return FORMAT and FORMAT:match("latex")
end

local function is_docx()
  return FORMAT and FORMAT:match("docx")
end

function Figure(elem)
  if not is_latex() then
    return elem
  end
  -- pandoc 3.x reads attr.attributes["fig-pos"] when emitting the
  -- `\begin{figure}[<pos>]` opener. Set it to H so float can't escape.
  elem.attr.attributes["fig-pos"] = "H"
  return elem
end

function Image(elem)
  if not is_docx() then
    return elem
  end
  -- Leave a hand-set width alone — per-image overrides in the source
  -- markdown should win.
  if elem.attributes["width"] == nil or elem.attributes["width"] == "" then
    elem.attributes["width"] = DOCX_IMAGE_WIDTH
  end
  return elem
end
