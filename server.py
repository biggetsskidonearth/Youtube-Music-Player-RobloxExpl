--[[
    Advanced YT Player V4 - Bulletproof WebSocket Client
    No more connect/disconnect loops.
]]

local HttpService = game:GetService("HttpService")
local Players = game:GetService("Players")
local UserInputService = game:GetService("UserInputService")
local TweenService = game:GetService("TweenService")
local RunService = game:GetService("RunService")

local Player = Players.LocalPlayer
local PlayerGui = Player:WaitForChild("PlayerGui")

-- CHANGE THIS TO YOUR RAILWAY URL IF HOSTED ONLINE
-- Example: "wss://your-app-name.up.railway.app"
local WS_URL = "ws://localhost:8765" 

local Socket = nil
local WSConnected = false

local Theme = {
    BgDark = Color3.fromRGB(10, 10, 12), BgMain = Color3.fromRGB(18, 18, 22),
    BgSurface = Color3.fromRGB(26, 26, 32), BgHover = Color3.fromRGB(36, 36, 44),
    Accent = Color3.fromRGB(30, 215, 96), TextMain = Color3.fromRGB(255, 255, 255),
    TextSub = Color3.fromRGB(180, 180, 190), TextMuted = Color3.fromRGB(100, 100, 110),
    Error = Color3.fromRGB(255, 70, 70)
}

local State = { isPlaying = false, isPaused = false, title = "", artist = "", duration = 0, currentTime = 0, volume = 0.5, queue = {}, currentIndex = -1, isSearching = false }

-- UI Helpers
local function new(c, p, par) local i = Instance.new(c) for k,v in pairs(p or {}) do if k~="Parent" then i[k]=v end end if par then i.Parent=par end return i end
local function addCorner(i, r) return new("UICorner",{CornerRadius=UDim.new(0,r or 8)},i) end
local function addStroke(i, c, t) return new("UIStroke",{Color=c or Color3.fromRGB(40,40,50),Thickness=t or 1,Transparency=0.5},i) end
local function tw(i, p, d) TweenService:Create(i, TweenInfo.new(d or 0.3, Enum.EasingStyle.Quad, Enum.EasingDirection.Out), p):Play() end
local function fmt(s) if not s or s<=0 then return "0:00" end s=math.floor(s) return string.format("%d:%02d", math.floor(s/60), s%60) end

-- Main GUI
local ScreenGui = new("ScreenGui", {Name="YTPlayerV4", ResetOnSpawn=false, ZIndexBehavior=Enum.ZIndexBehavior.Sibling, DisplayOrder=999}, PlayerGui)
local BlurFrame = new("Frame", {Size=UDim2.new(0,480,0,620), Position=UDim2.new(0.5,-240,0.5,-310), BackgroundColor3=Theme.BgDark, BackgroundTransparency=0.05, BorderSizePixel=0}, ScreenGui)
addCorner(BlurFrame, 20)
local MainFrame = new("Frame", {Size=UDim2.new(1,-2,1,-2), Position=UDim2.new(0,1,0,1), BackgroundColor3=Theme.BgMain, BorderSizePixel=0, ClipsDescendants=true}, BlurFrame)
addCorner(MainFrame, 19)
local StatusBar = new("Frame", {Size=UDim2.new(1,0,0,4), BackgroundColor3=Theme.Error, BorderSizePixel=0}, MainFrame)

-- Header
local Header = new("Frame", {Size=UDim2.new(1,0,0,60), BackgroundColor3=Theme.BgMain, BorderSizePixel=0}, MainFrame)
new("TextLabel", {Text="●", Size=UDim2.new(0,20,0,20), Position=UDim2.new(0,20,0,20), BackgroundTransparency=1, TextColor3=Theme.Accent, TextSize=24, Font=Enum.Font.GothamBold}, Header)
new("TextLabel", {Text="YT Player V4", Size=UDim2.new(0,120,0,20), Position=UDim2.new(0,42,0,20), BackgroundTransparency=1, TextColor3=Theme.TextMain, TextSize=18, Font=Enum.Font.GothamBold, TextXAlignment=Enum.TextXAlignment.Left}, Header)
local WsStatus = new("TextLabel", {Text="OFFLINE", Size=UDim2.new(0,60,0,16), Position=UDim2.new(0,42,0,40), BackgroundTransparency=1, TextColor3=Theme.Error, TextSize=10, Font=Enum.Font.GothamBold, TextXAlignment=Enum.TextXAlignment.Left}, Header)

-- Reconnect Button (Prevents auto-loop crashes)
local ReconnectBtn = new("TextButton", {Text="Reconnect", Size=UDim2.new(0,80,0,24), Position=UDim2.new(1,-180,0,18), BackgroundColor3=Theme.BgSurface, TextColor3=Theme.TextSub, TextSize=10, Font=Enum.Font.GothamBold, BorderSizePixel=0}, Header)
addCorner(ReconnectBtn, 6)
ReconnectBtn.MouseButton1Click:Connect(function()
    if not WSConnected then ConnectWS() end
end)

-- Window Controls
local function makeWinBtn(t, x, c, cb) local b=new("TextButton",{Text=t,Size=UDim2.new(0,14,0,14),Position=UDim2.new(1,x,0,23),BackgroundColor3=c,TextColor3=Color3.new(1,1,1),TextSize=8,Font=Enum.Font.GothamBold,BorderSizePixel=0},Header) addCorner(b,7) b.MouseButton1Click:Connect(cb) end
makeWinBtn("_", -50, Color3.fromRGB(255,200,50), function() local m=MainFrame.Size.Y.Offset<100 tw(MainFrame, m and {Size=UDim2.new(1,-2,1,-2)} or {Size=UDim2.new(1,-2,0,60)}, 0.4, Enum.EasingStyle.Back) end)
makeWinBtn("x", -30, Theme.Error, function() tw(BlurFrame, {Size=UDim2.new(0,480,0,0)}, 0.3) delay(0.3, function() ScreenGui:Destroy() end) end)

-- Drag
local drag={a=false,i=nil,s=Vector3.new(0,0,0),p=UDim2.new()}
Header.InputBegan:Connect(function(i) if i.UserInputType==Enum.UserInputType.MouseButton1 then drag.a=true drag.i=i drag.s=i.Position drag.p=BlurFrame.Position end end)
Header.InputEnded:Connect(function(i) if i==drag.i then drag.a=false end end)
UserInputService.InputChanged:Connect(function(i) if drag.a and i.UserInputType==Enum.UserInputType.MouseMovement then BlurFrame.Position=UDim2.new(drag.p.X.Scale,drag.p.X.Offset+(i.Position-drag.s).X,drag.p.Y.Scale,drag.p.Y.Offset+(i.Position-drag.s).Y) end end)

-- Search
local SearchPanel = new("Frame", {Size=UDim2.new(1,-40,0,44), Position=UDim2.new(0,20,0,72), BackgroundColor3=Theme.BgSurface, BorderSizePixel=0}, MainFrame)
addCorner(SearchPanel, 12) addStroke(SearchPanel)
new("TextLabel", {Text="⌕", Size=UDim2.new(0,40,1,0), BackgroundTransparency=1, TextColor3=Theme.TextMuted, TextSize=22, Font=Enum.Font.GothamBold}, SearchPanel)
local SearchBox = new("TextBox", {PlaceholderText="Search YouTube Music...", Text="", Size=UDim2.new(1,-90,1,0), Position=UDim2.new(0,40,0,0), BackgroundTransparency=1, TextColor3=Theme.TextMain, PlaceholderColor3=Theme.TextMuted, TextSize=14, Font=Enum.Font.Gotham, TextXAlignment=Enum.TextXAlignment.Left, ClearTextOnFocus=false}, SearchPanel)
local SearchBtn = new("TextButton", {Text="→", Size=UDim2.new(0,44,0,32), Position=UDim2.new(1,-48,0.5,-16), BackgroundColor3=Theme.Accent, TextColor3=Color3.new(1,1,1), TextSize=16, Font=Enum.Font.GothamBold, BorderSizePixel=0}, SearchPanel)
addCorner(SearchBtn, 8)

-- Results
local ResultsScroll = new("ScrollingFrame", {Size=UDim2.new(1,-40,0,280), Position=UDim2.new(0,20,0,124), BackgroundTransparency=1, ScrollBarThickness=3, ScrollBarImageColor3=Theme.BgHover, BorderSizePixel=0, CanvasSize=UDim2.new(0,0,0,0), AutomaticCanvasSize=Enum.AutomaticSize.Y}, MainFrame)
new("UIListLayout", {SortOrder=Enum.SortOrder.LayoutOrder, Padding=UDim.new(0,6)}, ResultsScroll)

-- Now Playing
local NPPanel = new("Frame", {Size=UDim2.new(1,0,0,200), Position=UDim2.new(0,0,1,-200), BackgroundColor3=Theme.BgDark, BorderSizePixel=0}, MainFrame)
local ProgressBack = new("Frame", {Size=UDim2.new(1,0,0,6), Position=UDim2.new(0,0,0,0), BackgroundColor3=Theme.BgHover, BorderSizePixel=0}, NPPanel)
local ProgressFill = new("Frame", {Size=UDim2.new(0,0,1,0), BackgroundColor3=Theme.Accent, BorderSizePixel=0}, ProgressBack)
addCorner(ProgressFill, 3)
local TimeL = new("TextLabel", {Text="0:00", Size=UDim2.new(0,40,0,16), Position=UDim2.new(0,20,0,10), BackgroundTransparency=1, TextColor3=Theme.TextMuted, TextSize=11, Font=Enum.Font.GothamMedium, TextXAlignment=Enum.TextXAlignment.Left}, NPPanel)
local TimeR = new("TextLabel", {Text="0:00", Size=UDim2.new(0,40,0,16), Position=UDim2.new(1,-60,0,10), BackgroundTransparency=1, TextColor3=Theme.TextMuted, TextSize=11, Font=Enum.Font.GothamMedium, TextXAlignment=Enum.TextXAlignment.Right}, NPPanel)
local TrackTitle = new("TextLabel", {Text="Nothing Playing", Size=UDim2.new(0.6,0,0,22), Position=UDim2.new(0,20,0,30), BackgroundTransparency=1, TextColor3=Theme.TextMain, TextSize=16, Font=Enum.Font.GothamBold, TextXAlignment=Enum.TextXAlignment.Left, TextTruncate=Enum.TextTruncate.AtEnd}, NPPanel)
local TrackArtist = new("TextLabel", {Text="Press Reconnect to start", Size=UDim2.new(0.6,0,0,16), Position=UDim2.new(0,20,0,52), BackgroundTransparency=1, TextColor3=Theme.TextSub, TextSize=12, Font=Enum.Font.Gotham, TextXAlignment=Enum.TextXAlignment.Left, TextTruncate=Enum.TextTruncate.AtEnd}, NPPanel)

-- Controls
local Controls = new("Frame", {Size=UDim2.new(1,0,0,50), Position=UDim2.new(0,0,1,-80), BackgroundTransparency=1}, NPPanel)
local function makeCtrl(t, x, s, cb) local b=new("TextButton",{Text=t,Size=UDim2.new(0,s or 40,0,40),Position=UDim2.new(0.5,x,0.5,-20),BackgroundTransparency=1,TextColor3=Theme.TextSub,TextSize=(s or 40)>40 and 14 or 18,Font=Enum.Font.GothamBold},Controls) b.MouseEnter:Connect(function() tw(b,{TextColor3=Theme.TextMain}) end) b.MouseLeave:Connect(function() tw(b,{TextColor3=Theme.TextSub}) end) b.MouseButton1Click:Connect(cb) return b end
makeCtrl("⏮",-90,40,function() wsSend({action="prev"}) end)
local BtnPlay = makeCtrl("▶",-40,50,function() if State.isPlaying then wsSend({action="pause"}) else wsSend({action="resume"}) end end)
makeCtrl("⏭",10,40,function() wsSend({action="next"}) end)
makeCtrl("🗑",60,30,function() wsSend({action="clear_queue"}) end)

-- Volume
local VolCont = new("Frame", {Size=UDim2.new(0,120,0,40), Position=UDim2.new(1,-140,1,-80), BackgroundTransparency=1}, NPPanel)
local VolIcon = new("TextLabel", {Text="🔊", Size=UDim2.new(0,24,0,24), Position=UDim2.new(0,0,0.5,-12), BackgroundTransparency=1, TextSize=16}, VolCont)
local VolBg = new("Frame", {Size=UDim2.new(0,80,0,4), Position=UDim2.new(0,30,0.5,-2), BackgroundColor3=Theme.BgHover, BorderSizePixel=0}, VolCont)
addCorner(VolBg, 2)
local VolFill = new("Frame", {Size=UDim2.new(State.volume,0,1,0), BackgroundColor3=Theme.TextMain, BorderSizePixel=0}, VolBg)
addCorner(VolFill, 2)
local volDrag = false
VolBg.InputBegan:Connect(function(i) if i.UserInputType==Enum.UserInputType.MouseButton1 then volDrag=true updateVol(i) end end)
VolBg.InputEnded:Connect(function(i) if i.UserInputType==Enum.UserInputType.MouseButton1 then volDrag=false end end)
UserInputService.InputChanged:Connect(function(i) if volDrag and i.UserInputType==Enum.UserInputType.MouseMovement then updateVol(i) end end)
function updateVol(i) local r=math.clamp((i.Position.X-VolBg.AbsolutePosition.X)/VolBg.AbsoluteSize.X,0,1) State.volume=r VolFill.Size=UDim2.new(r,0,1,0) VolIcon.Text=r==0 and "🔇" or (r<0.5 and "🔉" or "🔊") wsSend({action="volume",data={volume=r}}) end

-- Seek
local seekDrag = false
ProgressBack.InputBegan:Connect(function(i) if i.UserInputType==Enum.UserInputType.MouseButton1 then seekDrag=true doSeek(i) end end)
ProgressBack.InputEnded:Connect(function(i) if i.UserInputType==Enum.UserInputType.MouseButton1 then seekDrag=false end end)
function doSeek(i) local r=math.clamp((i.Position.X-ProgressBack.AbsolutePosition.X)/ProgressBack.AbsoluteSize.X,0,1) ProgressFill.Size=UDim2.new(r,0,1,0) wsSend({action="seek",data={time=r*State.duration}}) end

-- Core WebSocket Logic
function wsSend(data)
    if not WSConnected or not Socket then return false end
    local success, err = pcall(function() Socket:Send(HttpService:JSONEncode(data)) end)
    if not success then WSConnected = false UpdateUIOffline() end
    return success
end

function UpdateUIOffline()
    WSConnected = false
    StatusBar.BackgroundColor3 = Theme.Error
    WsStatus.Text = "OFFLINE"
    WsStatus.TextColor3 = Theme.Error
end

function ConnectWS()
    if WSConnected then return end
    TrackArtist.Text = "Connecting to server..."
    local success, err = pcall(function()
        Socket = WebSocket.connect(WS_URL)
        WSConnected = true
        StatusBar.BackgroundColor3 = Theme.Accent
        WsStatus.Text = "ONLINE"
        WsStatus.TextColor3 = Theme.Accent
        TrackArtist.Text = "Connected! Search to begin."
        
        -- Single listener thread, no loops, no auto-reconnect spam
        spawn(function()
            while WSConnected do
                local recvOk, msg = pcall(function() return Socket:Receive() end)
                if not recvOk or not msg then
                    UpdateUIOffline()
                    break -- Clean break, stops the thread entirely
                end
                
                local decodeOk, data = pcall(function() return HttpService:JSONDecode(msg) end)
                if decodeOk and data then
                    -- TRUE REAL-TIME SYNC: Server pushes exact time
                    if data.type == "sync" then
                        local d = data.data
                        State.isPlaying = d.is_playing
                        State.isPaused = d.is_paused
                        State.title = d.title or ""
                        State.artist = d.artist or ""
                        State.duration = d.duration or 0
                        State.currentTime = d.current_time or 0
                        State.queue = d.queue or {}
                        State.currentIndex = d.current_index or -1
                        
                        TrackTitle.Text = State.title ~= "" and State.title or "Nothing Playing"
                        TrackArtist.Text = State.artist ~= "" and State.artist or ""
                        BtnPlay.Text = State.isPlaying and "⏸" or "▶"
                        TimeR.Text = fmt(State.duration)
                        TimeL.Text = fmt(State.currentTime)
                        
                        if State.duration > 0 and not seekDrag then
                            ProgressFill.Size = UDim2.new(math.clamp(State.currentTime / State.duration, 0, 1), 0, 1, 0)
                        end
                    elseif data.type == "event" then
                        if data.event == "loading" then
                            TrackTitle.Text = data.data.title or "Loading..."
                            TrackArtist.Text = "Extracting audio via Python..."
                            BtnPlay.Text = "⏳"
                        elseif data.event == "ended" then
                            BtnPlay.Text = "▶"
                        elseif data.event == "error" then
                            TrackArtist.Text = "ERROR: " .. (data.data.message or "Unknown")
                            BtnPlay.Text = "▶"
                        end
                    elseif data.type == "search_results" then
                        populateResults(data.data)
                        State.isSearching = false
                    end
                end
            end
        end)
    end)
    
    if not success then
        warn("[YT Player] Connection failed: ", err)
        UpdateUIOffline()
        TrackArtist.Text = "Failed to connect. Check Python server."
    end
end

-- Results UI
local resultBtns = {}
function populateResults(results)
    for _, b in ipairs(resultBtns) do if b.Parent then b:Destroy() end end
    resultBtns = {}
    if not results or #results == 0 then
        table.insert(resultBtns, new("TextLabel", {Text="No results.", Size=UDim2.new(1,0,0,40), BackgroundTransparency=1, TextColor3=Theme.TextMuted, TextSize=14, Font=Enum.Font.GothamMedium, LayoutOrder=999}, ResultsScroll))
        return
    end
    for i, item in ipairs(results) do
        local btn = new("TextButton", {Size=UDim2.new(1,0,0,64), BackgroundColor3=Theme.BgSurface, Text="", AutoButtonColor=false, BorderSizePixel=0, LayoutOrder=i}, ResultsScroll)
        addCorner(btn, 10)
        btn.MouseEnter:Connect(function() tw(btn, {BackgroundColor3=Theme.BgHover}) end)
        btn.MouseLeave:Connect(function() tw(btn, {BackgroundColor3=Theme.BgSurface}) end)
        
        local thumb = new("Frame", {Size=UDim2.new(0,48,0,48), Position=UDim2.new(0,8,0.5,-24), BackgroundColor3=Theme.BgHover, BorderSizePixel=0}, btn)
        addCorner(thumb, 8)
        new("TextLabel", {Text="♪", Size=UDim2.new(1,0,1,0), BackgroundTransparency=1, TextColor3=Theme.TextMuted, TextSize=20, Font=Enum.Font.GothamBold}, thumb)
        
        if item.duration and item.duration > 0 then
            local badge = new("Frame", {Size=UDim2.new(0,34,0,16), Position=UDim2.new(0,22,1,-18), BackgroundColor3=Color3.fromRGB(0,0,0), BackgroundTransparency=0.3, BorderSizePixel=0}, thumb)
            addCorner(badge, 4)
            new("TextLabel", {Text=fmt(item.duration), Size=UDim2.new(1,0,1,0), BackgroundTransparency=1, TextColor3=Color3.new(1,1,1), TextSize=9, Font=Enum.Font.GothamBold}, badge)
        end
        new("TextLabel", {Text=item.title or "Unknown", Size=UDim2.new(1,-72,0,28), Position=UDim2.new(0,64,0,8), BackgroundTransparency=1, TextColor3=Theme.TextMain, TextSize=13, Font=Enum.Font.GothamBold, TextXAlignment=Enum.TextXAlignment.Left, TextTruncate=Enum.TextTruncate.AtEnd}, btn)
        new("TextLabel", {Text=item.artist or "Unknown", Size=UDim2.new(1,-72,0,18), Position=UDim2.new(0,64,0,36), BackgroundTransparency=1, TextColor3=Theme.TextSub, TextSize=11, Font=Enum.Font.Gotham, TextXAlignment=Enum.TextXAlignment.Left, TextTruncate=Enum.TextTruncate.AtEnd}, btn)
        
        btn.MouseButton1Click:Connect(function()
            wsSend({action="play", data={id=item.id, title=item.title, artist=item.artist, duration=item.duration}})
        end)
        table.insert(resultBtns, btn)
    end
end

local function doSearch()
    local q = SearchBox.Text
    if #q == 0 or State.isSearching or not WSConnected then return end
    State.isSearching = true
    for _, b in ipairs(resultBtns) do if b.Parent then b:Destroy() end end
    resultBtns = {}
    table.insert(resultBtns, new("TextLabel", {Text="Searching...", Size=UDim2.new(1,0,0,40), BackgroundTransparency=1, TextColor3=Theme.TextMuted, TextSize=14, Font=Enum.Font.GothamMedium, LayoutOrder=999}, ResultsScroll))
    wsSend({action="search", data={query=q}})
end

SearchBtn.MouseButton1Click:Connect(doSearch)
SearchBox.FocusLost:Connect(function(enter) if enter then doSearch() end end)
UserInputService.InputBegan:Connect(function(i, gp) if not gp and i.KeyCode==Enum.KeyCode.RightControl then ScreenGui.Enabled=not ScreenGui.Enabled end end)

-- Initial Connection Attempt
spawn(function() ConnectWS() end)
