-- catalog-tables.lua — docx styling for the event-catalog appendix tables.
--
-- The generated catalog (hht_diary tools/event-catalog) merges each event's
-- display name and its `entry_type` id into one cell: the name on top, then the
-- id (a code span) on the line below, e.g.
--
--   | Entry Display Name<br>`entry_type` | scope | kinds |
--   | Action Denial<br>`action_denial`   | portal | ...  |
--
-- This filter styles those cells for Word (docx only):
--   * the whole entry cell -> paragraph style "Catalog Entry" (keep-with-next
--     + keep-lines-together, so a two-line entry never splits across a page),
--   * the entry_type id run -> character style "Catalog Entry Type"
--     (10pt grey italic Consolas),
--   * the kinds values -> character style "Catalog Kind" (10pt Consolas).
-- Those styles are defined in the reference doc (build_docx_reference.py).
--
-- Catalog tables are identified by their header (a column whose header text
-- contains "Entry Display Name"); every other table in the URS is untouched.
-- The entry column may be the 1st (system/reserved tables) or 2nd (registry,
-- which leads with an aggregate column), so columns are found by header text,
-- not position.

if FORMAT ~= 'docx' then
  return {}
end

local ENTRY_STYLE = 'Catalog Entry'
local TYPE_STYLE = 'Catalog Entry Type'
local KIND_STYLE = 'Catalog Kind'

local function style_attr(name)
  return pandoc.Attr('', {}, { ['custom-style'] = name })
end

local function header_labels(tbl)
  local labels = {}
  local rows = tbl.head.rows
  if rows and rows[1] then
    local ci = 1
    for _, cell in ipairs(rows[1].cells) do
      labels[ci] = pandoc.utils.stringify(cell.contents)
      ci = ci + cell.col_span
    end
  end
  return labels
end

-- Replace the entry_type code span with a styled character run.
local function style_type_run(block)
  return pandoc.walk_block(block, {
    Code = function(c)
      return pandoc.Span({ pandoc.Str(c.text) }, style_attr(TYPE_STYLE))
    end,
  })
end

-- A pipe-table cell parses as a Plain block; pandoc's docx writer only stamps a
-- Div's custom paragraph style onto Para blocks, so promote Plain -> Para.
local function as_para(block)
  if block.t == 'Plain' then
    return pandoc.Para(block.content)
  end
  return block
end

-- Entry cell: restyle the id run; for body cells also wrap the paragraph in the
-- keep-together "Catalog Entry" style. Header cells keep their header formatting
-- (bold from the table style) and only get the id run restyled.
local function style_entry_cell(cell, is_header)
  local blocks = {}
  for _, b in ipairs(cell.contents) do
    blocks[#blocks + 1] = style_type_run(b)
  end
  if is_header then
    cell.contents = blocks
  else
    local paras = {}
    for _, b in ipairs(blocks) do
      paras[#paras + 1] = as_para(b)
    end
    cell.contents = { pandoc.Div(paras, style_attr(ENTRY_STYLE)) }
  end
end

-- Kinds cell: wrap the values in the monospace "Catalog Kind" run.
local function style_kind_cell(cell)
  for _, b in ipairs(cell.contents) do
    if b.content and #b.content > 0 then
      b.content = { pandoc.Span(b.content, style_attr(KIND_STYLE)) }
    end
  end
end

local function style_row(row, entry_col, kind_col, is_header)
  local ci = 1
  for _, cell in ipairs(row.cells) do
    if ci == entry_col then
      style_entry_cell(cell, is_header)
    elseif ci == kind_col and not is_header then
      style_kind_cell(cell)
    end
    ci = ci + cell.col_span
  end
end

function Table(tbl)
  local labels = header_labels(tbl)
  local entry_col, kind_col
  for i, label in pairs(labels) do
    if label:find('Entry Display Name', 1, true) then
      entry_col = i
    elseif label == 'kinds' then
      kind_col = i
    end
  end
  if not entry_col then
    return nil -- not a catalog table
  end
  for _, row in ipairs(tbl.head.rows) do
    style_row(row, entry_col, kind_col, true)
  end
  for _, body in ipairs(tbl.bodies) do
    for _, row in ipairs(body.body) do
      style_row(row, entry_col, kind_col, false)
    end
  end
  return tbl
end
