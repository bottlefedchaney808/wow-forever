-- WfPos — position bridge for the offline WoW Forever map.
-- Classic 1.13-compatible. Reads player world position + zone via the standard
-- public Lua API and prints it to chat. The built-in `/chatlog` command then
-- writes those chat lines to <WoW>\Logs\WoWChatLog.txt on disk, where the
-- external bridge (watch_pos.py) reads them. No file writing, no sockets, no
-- memory access, no automation -- only the same public API that Questie /
-- Leatrix / Coordinates use.
--
-- Install: put the whole WfPos folder into  <WoW Forever>\Interface\AddOns\
-- Enable in-game: System > AddOns > WfPos.  Then type:  /chatlog
--
-- Emitted line format (one per zone-change or >5 world-yards of movement):
--   [WFP] <zone>|<subzone>|<worldX>|<worldY>|<worldZ>|<mapXfrac>|<mapYfrac>

local TAG    = "[WFP]"
local MOV_GATE = 5      -- world yards of movement before re-emitting
local TICK   = 0.5      -- sample interval (seconds)

local frame = CreateFrame("Frame")
local acc   = 0
local lastZone, lastSub = nil, nil
local lastX, lastY      = nil, nil

local function emit()
  local x, y, z = UnitPosition("player")
  if not x or not y then return end
  local zone = GetZoneText()
  local sub  = GetSubZoneText() or ""

  -- zone-map fraction (0..1 within the current zone) as a fallback position
  local mx, my = 0, 0
  if GetPlayerMapPosition then
    local ok, a, b = pcall(GetPlayerMapPosition, "player")
    if ok then mx, my = a or 0, b or 0 end
  end

  local moved = (lastX == nil)
    or (math.abs(x - lastX) + math.abs(y - lastY) > MOV_GATE)
  local zoneChanged = (zone ~= lastZone or sub ~= lastSub)
  if not (moved or zoneChanged) then return end

  lastZone, lastSub = zone, sub
  lastX, lastY = x, y

  DEFAULT_CHAT_FRAME:AddMessage(string.format(
    "%s %s|%s|%d|%d|%d|%.3f|%.3f",
    TAG, zone, sub,
    math.floor(x), math.floor(y), math.floor(z or 0), mx, my))
end

frame:SetScript("OnUpdate", function(self, elapsed)
  acc = acc + elapsed
  if acc >= TICK then
    acc = 0
    emit()
  end
end)
