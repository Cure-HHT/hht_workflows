-- table-autofit-docx.lua — content-based column widths for the docx target.
--
-- pandoc emits pipe tables (no authored widths) as <w:tblW type="auto">
-- with bare gridCol hints; Word and LibreOffice then spread the columns
-- near-evenly, wrapping short identifiers ("ACT-QST-001") and narrow
-- headers ("Administrator") while wide prose columns sit half empty.
--
-- This filter assigns each auto-width table explicit fractional column
-- widths computed from its content:
--   * floor   — the column's longest unbreakable word, header words
--               included (never wrap mid-word: Action IDs, role names,
--               "Coordinator"),
--   * natural — the column's longest BODY cell text, capped at CAP
--               chars so prose columns are treated as wrappable.
--               Header text beyond its longest word does not widen the
--               column: a header like "Study Coordinator" wraps to two
--               lines in preference to squeezing body content,
--   * the table always spans the full text width; spare space goes to
--     the prose (capped) columns, or proportionally when none exist.
--
-- Width-bearing tables need care: pandoc also assigns widths to any
-- pipe table whose source line exceeds the --columns width, derived
-- from the separator-dash proportions — and elspais emits uniform
-- separators, so those come out as meaningless equal widths. The
-- filter therefore recomputes tables whose widths are absent OR all
-- equal, and leaves genuinely authored (unequal) widths — e.g. the
-- revision-history grid table — untouched. Empty columns (the
-- signature blocks) count as flex columns and soak up spare width
-- rather than collapsing. Non-docx targets pass through unchanged
-- (the PDF path has its own table-grid.lua treatment).

if FORMAT ~= 'docx' then
  return {}
end

local LINE_CHARS = 76 -- ~chars per full text-width line (11pt body font)
local CAP = 48        -- chars beyond which a column is prose and may wrap
local COL_PAD = 0.035 -- per-column fraction for cell margins / borders
local HEAD_WEIGHT = 1.15 -- header cells render bold(-italic), ~15% wider

local function cell_text(cell)
  return pandoc.utils.stringify(pandoc.Div(cell.contents))
end

-- words_only: header rows only contribute their longest word to the
-- floor (headers wrap between words rather than widening the column).
local function scan_rows(rows, ncols, nat, minw, raw, weight, words_only)
  for _, row in ipairs(rows) do
    local ci = 1
    for _, cell in ipairs(row.cells) do
      if cell.col_span == 1 and ci <= ncols then
        local text = cell_text(cell)
        if not words_only then
          local n = (utf8.len(text) or #text) * weight
          if n > raw[ci] then raw[ci] = n end
          local capped = math.min(n, CAP)
          if capped > nat[ci] then nat[ci] = capped end
        end
        for word in text:gmatch("%S+") do
          local wl = (utf8.len(word) or #word) * weight
          if wl > minw[ci] then minw[ci] = wl end
        end
      end
      ci = ci + cell.col_span
    end
  end
end

function Table(tbl)
  -- Skip only genuinely authored layouts: width sets that are not all
  -- (near-)equal. Absent widths and uniform widths get recomputed.
  local first_w = nil
  for _, spec in ipairs(tbl.colspecs) do
    local w = spec[2]
    if w then
      if first_w == nil then
        first_w = w
      elseif math.abs(w - first_w) > 0.01 then
        return nil -- authored, unequal widths — leave the table alone
      end
    end
  end
  local ncols = #tbl.colspecs
  if ncols == 0 then
    return nil
  end

  local nat, minw, raw = {}, {}, {}
  for i = 1, ncols do
    nat[i], minw[i], raw[i] = 1, 1, 0
  end
  scan_rows(tbl.head.rows, ncols, nat, minw, raw, HEAD_WEIGHT, true)
  for _, body in ipairs(tbl.bodies) do
    scan_rows(body.head, ncols, nat, minw, raw, HEAD_WEIGHT, true)
    scan_rows(body.body, ncols, nat, minw, raw, 1, false)
  end
  scan_rows(tbl.foot.rows, ncols, nat, minw, raw, 1, false)

  local function frac(chars)
    return chars / LINE_CHARS + COL_PAD
  end

  local natf, minf = {}, {}
  local nat_total, min_total = 0, 0
  for i = 1, ncols do
    -- +1 char of slack on the floor: the per-char width estimate is an
    -- average, and glyph-heavy words (M, W) otherwise wrap at the edge
    minf[i] = frac(minw[i] + 1)
    natf[i] = math.max(frac(nat[i]), minf[i])
    nat_total = nat_total + natf[i]
    min_total = min_total + minf[i]
  end

  local widths = {}
  if nat_total >= 1 then
    if min_total >= 1 then
      -- even the longest words overflow the page: scale the floors
      for i = 1, ncols do
        widths[i] = minf[i] / min_total
      end
    else
      -- floors fit: hand out the remaining width by need (nat - min)
      local spare = 1 - min_total
      local need = nat_total - min_total
      for i = 1, ncols do
        if need > 0 then
          widths[i] = minf[i] + spare * (natf[i] - minf[i]) / need
        else
          widths[i] = minf[i] + spare / ncols
        end
      end
    end
  else
    -- everything fits naturally: stretch to the full text width, the
    -- extra going to flex columns — prose (capped) columns and empty
    -- columns (signature blanks) — else proportionally
    local spare = 1 - nat_total
    local flex, flex_n = {}, 0
    for i = 1, ncols do
      if raw[i] > CAP or raw[i] < 1 then
        flex[i] = true
        flex_n = flex_n + 1
      end
    end
    for i = 1, ncols do
      if flex_n > 0 then
        widths[i] = natf[i] + (flex[i] and spare / flex_n or 0)
      else
        widths[i] = natf[i] / nat_total
      end
    end
  end

  local specs = {}
  for i = 1, ncols do
    specs[i] = { tbl.colspecs[i][1], widths[i] }
  end
  tbl.colspecs = specs
  return tbl
end
