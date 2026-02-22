-- Balatro AI Mod: TCP socket interface for AI agent
-- Injected at the end of main.lua, hooks into game update loop

local socket = require("socket")

-- Load turbo mode if TURBO_MODE env var is set (before anything else)
local TURBO = nil
if os.getenv("TURBO_MODE") == "1" then
    -- Try multiple paths: game dir, mods dir, CWD
    local paths = {
        "/opt/balatro-game/turbo-mod.lua",
        "turbo-mod.lua",
    }
    -- Also try relative to this script's location
    local info = debug.getinfo(1, "S")
    if info and info.source and info.source:sub(1,1) == "@" then
        local dir = info.source:sub(2):match("(.*/)")
        if dir then table.insert(paths, 1, dir .. "turbo-mod.lua") end
    end
    for _, p in ipairs(paths) do
        local f = io.open(p, "r")
        if f then
            f:close()
            TURBO = dofile(p)
            TURBO.install()
            break
        end
    end
    if not TURBO then
        print("[turbo] WARNING: turbo-mod.lua not found!")
    end
end

local AI = {
    server = nil,
    client = nil,
    port = tonumber(os.getenv("BALATRO_PORT")) or 12345,
    buffer = "",
    _cached_blind_chips = 0,
    last_state = "",
    frame_count = 0,
}

function AI.init()
    AI.server = socket.tcp()
    AI.server:setoption("reuseaddr", true)
    AI.server:bind("0.0.0.0", AI.port)
    AI.server:listen(1)
    AI.server:settimeout(0)
    print("[AI] Listening on port " .. AI.port)

    -- Set language to Chinese and skip tutorial on next update
    AI.pending_lang = "zh_CN"
    AI.pending_skip_tutorial = true
end

function AI.get_hand_cards()
    local cards = {}
    if G and G.hand and G.hand.cards then
        for i, card in ipairs(G.hand.cards) do
            table.insert(cards, {
                id = card.base.id,
                suit = card.base.suit,
                value = card.base.value,
                rank = card.base.nominal,
                highlighted = card.highlighted and true or false,
                edition = card.edition and card.edition.type or nil,
                seal = card.seal or nil,
                enhancement = card.ability and card.ability.name or nil,
            })
        end
    end
    return cards
end

function AI.get_jokers()
    local jokers = {}
    if G and G.jokers and G.jokers.cards then
        for i, card in ipairs(G.jokers.cards) do
            -- Export ability.extra as joker runtime state
            local extra = card.ability and card.ability.extra or nil
            local extra_out = nil
            if type(extra) == "table" then
                extra_out = {}
                for k, v in pairs(extra) do
                    if type(v) == "number" or type(v) == "string" or type(v) == "boolean" then
                        extra_out[k] = v
                    end
                end
            elseif type(extra) == "number" then
                extra_out = extra
            end
            table.insert(jokers, {
                name = card.ability.name,
                id = card.config.center.key,
                order = card.ability.order,
                edition = card.edition and card.edition.type or "",
                rarity = card.config.center.rarity or 1,
                sell_value = card.sell_cost or 0,
                extra = extra_out,
                mult = card.ability.mult or 0,
                t_mult = card.ability.t_mult or 0,
                t_chips = card.ability.t_chips or 0,
                x_mult = card.ability.x_mult or 0,
            })
        end
    end
    return jokers
end

function AI.get_shop_items()
    local items = {}
    -- Joker slots
    if G and G.shop_jokers and G.shop_jokers.cards then
        for _, card in ipairs(G.shop_jokers.cards) do
            table.insert(items, {
                name = card.ability and card.ability.name or "unknown",
                cost = card.cost or 0,
                type = card.ability and card.ability.set or "Joker",
            })
        end
    end
    -- Voucher slot
    if G and G.shop_vouchers and G.shop_vouchers.cards then
        for _, card in ipairs(G.shop_vouchers.cards) do
            table.insert(items, {
                name = card.ability and card.ability.name or "unknown",
                cost = card.cost or 0,
                type = "Voucher",
            })
        end
    end
    -- Booster packs
    if G and G.shop_booster and G.shop_booster.cards then
        for _, card in ipairs(G.shop_booster.cards) do
            table.insert(items, {
                name = card.ability and card.ability.name or "unknown",
                cost = card.cost or 0,
                type = card.ability and card.ability.set or "Booster",
            })
        end
    end
    return items
end

function AI.get_blind_choices()
    local choices = {}
    if G and G.GAME and G.GAME.blind then
        choices.current = {
            name = G.GAME.blind.name or "unknown",
            chips = G.GAME.blind.chips or 0,
            debuff = G.GAME.blind.debuff and G.GAME.blind.debuff.type or nil,
        }
    end
    if G and G.GAME and G.GAME.round_resets then
        choices.ante = G.GAME.round_resets.ante or 0
    end
    return choices
end

function AI.get_game_state()
    if not G or not G.GAME then return nil end

    local state_name = "UNKNOWN"
    if G.STATES then
        for name, val in pairs(G.STATES) do
            if val == G.STATE then
                state_name = name
                break
            end
        end
    end

    local stage_name = "UNKNOWN"
    if G.STAGES then
        for name, val in pairs(G.STAGES) do
            if val == G.STAGE then
                stage_name = name
                break
            end
        end
    end

    local state = {
        stage = stage_name,
        state = state_name,
        state_complete = G.STATE_COMPLETE or false,
        ante = G.GAME.round_resets and G.GAME.round_resets.ante or 0,
        round = G.GAME.round or 0,
        dollars = G.GAME.dollars or 0,
        hands_left = G.GAME.current_round and G.GAME.current_round.hands_left or 0,
        discards_left = G.GAME.current_round and G.GAME.current_round.discards_left or 0,
        chips = G.GAME.chips or 0,
        blind_chips = 0,  -- filled below
        blind_on_deck = G.GAME.blind_on_deck or "unknown",
        seed = G.GAME.pseudorandom and G.GAME.pseudorandom.seed or "unknown",
        hand_cards = AI.get_hand_cards(),
        jokers = AI.get_jokers(),
        joker_space = (G.jokers and (G.jokers.config.card_limit - #G.jokers.cards) or 0),
        joker_slots = (G.jokers and G.jokers.config.card_limit or 5),
        consumable_space = (G.consumeables and (G.consumeables.config.card_limit - #G.consumeables.cards) or 0),
        consumable_slots = (G.consumeables and G.consumeables.config.card_limit or 2),
        hand_levels = {},
        consumables = {},
    }

    -- Cache blind_chips: use live value when available, fall back to cache
    local live_blind = G.GAME.blind and G.GAME.blind.chips or 0
    if live_blind > 0 then
        AI._cached_blind_chips = live_blind
    end
    state.blind_chips = live_blind > 0 and live_blind or (AI._cached_blind_chips or 0)

    -- Boss blind name (e.g. "The Plant", "The Head") — needed for debuff-aware scoring
    if G.GAME.blind and G.GAME.blind.name then
        state.boss_blind = G.GAME.blind.name
    else
        state.boss_blind = ""
    end

    -- Vouchers owned (affects game mechanics)
    state.vouchers = {}
    if G.GAME.used_vouchers then
        for k, v in pairs(G.GAME.used_vouchers) do
            if v then table.insert(state.vouchers, k) end
        end
    end

    -- Deck stats: total cards, enhanced count by type
    state.deck_size = G.GAME.starting_params and G.GAME.starting_params.deck_size or 52
    state.current_deck_size = G.playing_cards and #G.playing_cards or state.deck_size
    if G.deck and G.deck.cards then
        state.deck_remaining = #G.deck.cards
    end

    -- Skip tags (what you get for skipping Small/Big blind)
    state.skip_tags = {}
    if G.GAME.round_resets and G.GAME.round_resets.blind_tags then
        for blind_type, tag_key in pairs(G.GAME.round_resets.blind_tags) do
            state.skip_tags[blind_type] = tag_key or ""
        end
    end

    -- Hand levels (poker hand types and their levels)
    if G.GAME.hands then
        for name, data in pairs(G.GAME.hands) do
            if data.visible then
                state.hand_levels[name] = {
                    level = data.level or 1,
                    chips = data.chips or 0,
                    mult = data.mult or 0,
                    played = data.played or 0,
                }
            end
        end
    end

    -- Consumables
    if G.consumeables and G.consumeables.cards then
        for _, card in ipairs(G.consumeables.cards) do
            table.insert(state.consumables, {
                name = card.ability and card.ability.name or "unknown",
                type = card.ability and card.ability.set or "unknown",
            })
        end
    end

    -- Shop state
    if state_name == "SHOP" then
        state.shop_items = AI.get_shop_items()
    end

    -- Blind select state
    if state_name == "BLIND_SELECT" then
        state.blind_choices = AI.get_blind_choices()
    end

    return state
end

-- Simple JSON encoder (no external deps)
function AI.to_json(val, indent)
    indent = indent or ""
    local t = type(val)
    if t == "nil" then return "null"
    elseif t == "boolean" then return val and "true" or "false"
    elseif t == "number" then return tostring(val)
    elseif t == "string" then
        return '"' .. val:gsub('\\','\\\\'):gsub('"','\\"'):gsub('\n','\\n') .. '"'
    elseif t == "table" then
        -- Check if array
        local is_array = (#val > 0)
        if is_array then
            local parts = {}
            for _, v in ipairs(val) do
                table.insert(parts, AI.to_json(v, indent))
            end
            return "[" .. table.concat(parts, ",") .. "]"
        else
            local parts = {}
            for k, v in pairs(val) do
                if type(k) == "string" then
                    table.insert(parts, '"' .. k .. '":' .. AI.to_json(v, indent))
                end
            end
            if #parts == 0 then return "{}" end
            return "{" .. table.concat(parts, ",") .. "}"
        end
    end
    return "null"
end

function AI.execute_command(cmd)
    if not cmd or cmd == "" then return '{"ok":false,"error":"empty command"}' end

    local parts = {}
    for word in cmd:gmatch("%S+") do
        table.insert(parts, word)
    end

    local action = parts[1]

    if action == "state" then
        local s = AI.get_game_state()
        if s then return AI.to_json(s) else return '{"ok":false,"error":"no game state"}' end

    elseif action == "select" then
        -- select <card_indices...> : highlight cards in hand
        if G.STATE ~= G.STATES.SELECTING_HAND then
            return '{"ok":false,"error":"not in SELECTING_HAND state"}'
        end
        -- Unhighlight all first using proper CardArea API
        if G.hand then
            G.hand:unhighlight_all()
            -- Highlight specified indices (1-based) using proper CardArea API
            local selected = 0
            for i = 2, #parts do
                local idx = tonumber(parts[i])
                if idx and G.hand.cards[idx] then
                    G.hand:add_to_highlighted(G.hand.cards[idx], true)
                    selected = selected + 1
                end
            end
            return '{"ok":true,"action":"select","selected":' .. selected .. '}'
        end
        return '{"ok":false,"error":"no hand"}'

    elseif action == "play" then
        -- Play the currently highlighted hand
        if G.STATE ~= G.STATES.SELECTING_HAND then
            return '{"ok":false,"error":"not in SELECTING_HAND state"}'
        end
        local count = G.hand and #G.hand.highlighted or 0
        if count == 0 then
            return '{"ok":false,"error":"no cards selected"}'
        end
        G.FUNCS.play_cards_from_highlighted({config = {ref_table = G.play}})
        return '{"ok":true,"action":"play","cards_played":' .. count .. '}'

    elseif action == "discard" then
        -- Discard the currently highlighted cards
        if G.STATE ~= G.STATES.SELECTING_HAND then
            return '{"ok":false,"error":"not in SELECTING_HAND state"}'
        end
        if G.GAME.current_round.discards_left <= 0 then
            return '{"ok":false,"error":"no discards left"}'
        end
        local count = G.hand and #G.hand.highlighted or 0
        if count == 0 then
            return '{"ok":false,"error":"no cards selected"}'
        end
        G.FUNCS.discard_cards_from_highlighted({config = {ref_table = G.play}})
        return '{"ok":true,"action":"discard","cards_discarded":' .. count .. '}'

    elseif action == "select_blind" then
        -- select_blind small|big|boss
        local blind_type = parts[2] or "small"
        if G.STATE ~= G.STATES.BLIND_SELECT then
            return '{"ok":false,"error":"not in BLIND_SELECT state"}'
        end
        -- Click the appropriate blind button
        if blind_type == "skip" then
            G.FUNCS.skip_blind({config = {ref_table = {}}})
        else
            -- Pass the correct blind config so chips/mult are set properly
            local deck_type = G.GAME.blind_on_deck or "Small"
            local blind_key = G.GAME.round_resets and G.GAME.round_resets.blind_choices
                              and G.GAME.round_resets.blind_choices[deck_type]
            local blind_config = blind_key and G.P_BLINDS and G.P_BLINDS[blind_key] or {}
            G.FUNCS.select_blind({config = {ref_table = blind_config}})
        end
        return '{"ok":true,"action":"select_blind","blind":"' .. blind_type .. '"}'

    elseif action == "buy" or action == "select_shop" then
        -- buy <shop_index> : buy item from shop (0-based index from Python)
        local idx = tonumber(parts[2])
        if G.STATE ~= G.STATES.SHOP then
            return '{"ok":false,"error":"not in SHOP state"}'
        end
        if not idx then
            return '{"ok":false,"error":"missing index"}'
        end

        -- Collect all shop cards into a flat list (matching get_shop_items order)
        local all_cards = {}
        if G.shop_jokers and G.shop_jokers.cards then
            for _, card in ipairs(G.shop_jokers.cards) do
                table.insert(all_cards, card)
            end
        end
        if G.shop_vouchers and G.shop_vouchers.cards then
            for _, card in ipairs(G.shop_vouchers.cards) do
                table.insert(all_cards, card)
            end
        end
        if G.shop_booster and G.shop_booster.cards then
            for _, card in ipairs(G.shop_booster.cards) do
                table.insert(all_cards, card)
            end
        end

        -- Convert 0-based to 1-based
        local lua_idx = idx + 1
        if lua_idx < 1 or lua_idx > #all_cards then
            return '{"ok":false,"error":"index out of range, have ' .. #all_cards .. ' items"}'
        end

        local card = all_cards[lua_idx]
        local cost = card.cost or 0
        local dollars = G.GAME.dollars or 0
        if cost > dollars then
            return '{"ok":false,"error":"not enough money, need $' .. cost .. ' have $' .. dollars .. '"}'
        end

        -- Check if there's space (for jokers)
        if card.ability and card.ability.set == 'Joker' then
            if G.jokers and #G.jokers.cards >= G.jokers.config.card_limit then
                return '{"ok":false,"error":"joker slots full"}'
            end
        end

        -- Check if there's space (for consumables: Tarot, Planet, Spectral)
        if card.ability and (card.ability.set == 'Tarot' or card.ability.set == 'Planet' or card.ability.set == 'Spectral') then
            if G.consumeables and #G.consumeables.cards >= G.consumeables.config.card_limit then
                return '{"ok":false,"error":"consumable slots full"}'
            end
        end

        -- Simulate the buy button click
        G.FUNCS.buy_from_shop({config = {ref_table = card}})
        local name = card.ability and card.ability.name or "unknown"
        return '{"ok":true,"action":"buy","name":"' .. name:gsub('"', '\\"') .. '","cost":' .. cost .. '}'

    elseif action == "deck_info" then
        -- Return draw pile and discard pile card composition
        local draw = {}
        local discard = {}
        if G.deck and G.deck.cards then
            for _, card in ipairs(G.deck.cards) do
                table.insert(draw, {
                    value = card.base and card.base.value or "?",
                    suit = card.base and card.base.suit or "?",
                    enhancement = card.ability and card.ability.name or "",
                    edition = card.edition and (card.edition.holo and "Holographic" or card.edition.foil and "Foil" or card.edition.polychrome and "Polychrome" or "") or "",
                    seal = card.seal or "",
                })
            end
        end
        if G.discard and G.discard.cards then
            for _, card in ipairs(G.discard.cards) do
                table.insert(discard, {
                    value = card.base and card.base.value or "?",
                    suit = card.base and card.base.suit or "?",
                })
            end
        end
        local hand_size = G.hand and #G.hand.cards or 0
        return AI.to_json({ok=true, draw_pile=draw, draw_count=#draw, discard_pile=discard, discard_count=#discard, hand_size=hand_size})

    elseif action == "cash_out" then
        -- Cash out after round evaluation
        if G.STATE ~= G.STATES.ROUND_EVAL then
            return '{"ok":false,"error":"not in ROUND_EVAL state"}'
        end
        -- Find and click the cash_out button
        if G.round_eval then
            -- Simulate the cash_out button press
            G.FUNCS.cash_out({config = {}})
            return '{"ok":true,"action":"cash_out"}'
        end
        return '{"ok":false,"error":"no round_eval UI"}'

    elseif action == "fast_cash_out" then
        -- Instant cash out: skip all animations, directly manipulate game state
        if G.STATE ~= G.STATES.ROUND_EVAL then
            return '{"ok":false,"error":"not in ROUND_EVAL state"}'
        end
        -- Clear ALL pending events
        G.E_MANAGER:clear_queue('base')
        
        -- Do what cash_out does, but immediately (no event queue)
        if G.round_eval then
            G.round_eval:remove()
            G.round_eval = nil
        end
        
        -- Award round dollars
        local earned = G.GAME.current_round.dollars or 0
        G.GAME.dollars = G.GAME.dollars + earned
        G.GAME.previous_round.dollars = G.GAME.dollars
        
        -- Reset round state
        G.GAME.current_round.jokers_purchased = 0
        G.GAME.current_round.discards_left = math.max(0, G.GAME.round_resets.discards + G.GAME.round_bonus.discards)
        G.GAME.current_round.hands_left = math.max(1, G.GAME.round_resets.hands + G.GAME.round_bonus.next_hands)
        G.GAME.shop_free = nil
        G.GAME.shop_d6ed = nil
        
        -- Handle ante progression (Boss defeated)
        if G.GAME.round_resets.blind_states.Boss == 'Defeated' then
            G.GAME.round_resets.blind_ante = G.GAME.round_resets.ante
            G.GAME.round_resets.blind_tags.Small = get_next_tag_key()
            G.GAME.round_resets.blind_tags.Big = get_next_tag_key()
        end
        reset_blinds()
        
        -- Reset chips display
        G.GAME.chips = 0
        
        -- Set state to SHOP
        G.STATE = G.STATES.SHOP
        G.STATE_COMPLETE = false
        
        return '{"ok":true,"action":"fast_cash_out","earned":' .. earned .. '}'

    elseif action == "end_shop" then
        if G.STATE ~= G.STATES.SHOP then
            return '{"ok":false,"error":"not in SHOP state"}'
        end
        G.FUNCS.toggle_shop({})
        return '{"ok":true,"action":"end_shop"}'

    elseif action == "fast_end_shop" then
        if G.STATE ~= G.STATES.SHOP then
            return '{"ok":false,"error":"not in SHOP state"}'
        end
        -- Clear base event queue only
        G.E_MANAGER:clear_queue('base')
        -- Run joker end-of-shop calculations
        for i = 1, #G.jokers.cards do
            G.jokers.cards[i]:calculate_joker({ending_shop = true})
        end
        -- Remove shop UI directly
        if G.shop then
            G.shop:remove()
            G.shop = nil
        end
        if G.SHOP_SIGN then
            G.SHOP_SIGN:remove()
            G.SHOP_SIGN = nil
        end
        G.CONTROLLER.locks.toggle_shop = nil
        G.STATE_COMPLETE = false
        G.STATE = G.STATES.BLIND_SELECT
        return '{"ok":true,"action":"fast_end_shop"}'

    elseif action == "start_run" then
        -- Start a new run from main menu, optionally with a seed
        if G.STAGE ~= G.STAGES.MAIN_MENU then
            return '{"ok":false,"error":"not in main menu"}'
        end
        local seed = parts[2] or nil  -- "start_run MYSEED123"
        G.FUNCS.start_run(nil, {stake = 1, seed = seed})
        -- Set max game speed for AI play (16x)
        G.SETTINGS.GAMESPEED = 16
        -- Disable animations for faster play
        G.SETTINGS.reduced_motion = true
        return '{"ok":true,"action":"start_run"}'

    elseif action == "speed" then
        -- speed <N> : set game speed (1-500)
        local spd = tonumber(parts[2]) or 10
        G.SETTINGS.GAMESPEED = math.max(1, spd)
        return '{"ok":true,"action":"speed","speed":' .. G.SETTINGS.GAMESPEED .. '}'

    elseif action == "turbo" then
        -- turbo: fast mode for batch runs
        -- Override delay() to use near-zero delays
        if not AI._orig_delay then
            AI._orig_delay = delay
        end
        delay = function(t, queue)
            return AI._orig_delay(0.001, queue)
        end
        -- Patch attention_text to minimize hold time
        if not AI._orig_attention_text then
            AI._orig_attention_text = attention_text
        end
        attention_text = function(args)
            if args then args.hold = 0 end
            return AI._orig_attention_text(args)
        end
        -- Patch play_sound to no-op (saves CPU)
        if not AI._orig_play_sound then
            AI._orig_play_sound = play_sound
        end
        play_sound = function() end
        -- Speed up event processing: override E_MANAGER update to drain events faster
        if G.E_MANAGER and not AI._orig_em_update then
            AI._orig_em_update = G.E_MANAGER.update
            G.E_MANAGER.update = function(self, dt, force)
                -- Process events with a large dt to speed through animations
                return AI._orig_em_update(self, math.max(dt, 0.5), force)
            end
        end
        G.SETTINGS.GAMESPEED = 16
        G.SETTINGS.reduced_motion = true
        G.SETTINGS.screenshake = 0
        return '{"ok":true,"action":"turbo"}'

    elseif action == "quit_run" then
        -- Quit current run and return to main menu
        if G.STAGE == G.STAGES.RUN then
            G.FUNCS.go_to_menu()
            return '{"ok":true,"action":"quit_run"}'
        else
            return '{"ok":false,"error":"not in a run"}'
        end

    elseif action == "speed_mult" then
        -- speed_mult <N> : set dt multiplier (1-16)
        local mult = tonumber(parts[2]) or 4
        AI.speed_mult = math.max(1, math.min(mult, 16))
        return '{"ok":true,"action":"speed_mult","mult":' .. AI.speed_mult .. '}'

    elseif action == "use" then
        -- use <consumable_index> : use a consumable card (0-based)
        local idx = tonumber(parts[2])
        if not idx then
            return '{"ok":false,"error":"use requires index"}'
        end
        if not G.consumeables or not G.consumeables.cards then
            return '{"ok":false,"error":"no consumables area"}'
        end
        local card = G.consumeables.cards[idx + 1]  -- Lua is 1-based
        if not card then
            return '{"ok":false,"error":"invalid consumable index ' .. tostring(idx) .. ', have ' .. #G.consumeables.cards .. '"}'
        end
        local card_name = card.ability and card.ability.name or "unknown"
        local card_type = card.ability and card.ability.set or "unknown"

        -- For Planet cards: just use directly (no card selection needed)
        -- For Tarot cards: may need selected hand cards, but we'll handle simple use
        if card_type == "Planet" then
            -- Planet cards can be used directly
            G.FUNCS.use_card({config = {ref_table = card}})
            return '{"ok":true,"action":"use","name":"' .. card_name .. '","type":"' .. card_type .. '"}'
        elseif card_type == "Tarot" or card_type == "Spectral" then
            -- Tarot/Spectral: try to use (some need selected cards)
            -- For now, attempt direct use
            local can_use = card:can_use_consumeable(nil, true)
            if can_use then
                G.FUNCS.use_card({config = {ref_table = card}})
                return '{"ok":true,"action":"use","name":"' .. card_name .. '","type":"' .. card_type .. '"}'
            else
                return '{"ok":false,"error":"cannot use ' .. card_name .. ' right now (may need selected cards)"}'
            end
        else
            return '{"ok":false,"error":"unknown consumable type: ' .. card_type .. '"}'
        end

    elseif action == "ping" then
        return '{"ok":true,"action":"pong"}'

    elseif action == "screenshot" then
        -- Take screenshot using LÖVE's built-in API (captures OpenGL framebuffer)
        local fname = parts[2] or ("screenshot_" .. os.time() .. ".png")
        local save_path = fname
        love.graphics.captureScreenshot(save_path)
        -- LÖVE saves to its save directory
        local save_dir = love.filesystem.getSaveDirectory()
        return '{"ok":true,"action":"screenshot","file":"' .. save_dir .. '/' .. save_path .. '"}'

    elseif action == "reroll" then
        -- reroll: reroll shop items for $5
        if G.STATE ~= G.STATES.SHOP then
            return '{"ok":false,"error":"not in SHOP state"}'
        end
        local cost = G.GAME.current_round.reroll_cost or 5
        if (G.GAME.dollars or 0) < cost then
            return '{"ok":false,"error":"not enough money for reroll ($' .. cost .. ')"}'
        end
        G.FUNCS.reroll_shop({})
        return '{"ok":true,"action":"reroll","cost":' .. cost .. '}'

    else
        return '{"ok":false,"error":"unknown command: ' .. (action or "nil") .. '"}'
    end
end

function AI.update()
    AI.frame_count = AI.frame_count + 1

    -- Apply pending language change
    if AI.pending_lang and G and G.SETTINGS and G.LANGUAGES then
        G.SETTINGS.language = AI.pending_lang
        if G.set_language then
            G:set_language()
            print("[AI] Language set to " .. AI.pending_lang)
        end
        AI.pending_lang = nil
    end

    -- Skip tutorial
    if AI.pending_skip_tutorial and G then
        G.F_SKIP_TUTORIAL = true
        if G.SETTINGS then
            G.SETTINGS.tutorial_complete = true
            G.SETTINGS.tutorial_progress = nil
        end
        AI.pending_skip_tutorial = nil
        print("[AI] Tutorial skipped")
    end

    -- Accept new connections
    if AI.server then
        local client = AI.server:accept()
        if client then
            if AI.client then AI.client:close() end
            AI.client = client
            AI.client:settimeout(0)
            print("[AI] Client connected")
        end
    end

    -- Read commands from client
    if AI.client then
        local data, err, partial = AI.client:receive("*l")
        local line = data or partial
        if line and line ~= "" then
            local ok, result = pcall(AI.execute_command, line)
            if ok then
                AI.client:send(result .. "\n")
            else
                AI.client:send('{"ok":false,"error":"lua error: ' .. tostring(result):gsub('"', '\\"') .. '"}\n')
            end
        end
        if err == "closed" then
            print("[AI] Client disconnected")
            AI.client = nil
        end
    end
end

-- Speed multiplier for AI play (applied on top of GAMESPEED)
-- Carl approved: 2x dt multiplier (tested safe, >4 crashes)
AI.speed_mult = 2

-- Hook into LÖVE update
local _original_update = love.update
love.update = function(dt)
    -- Apply turbo settings once G is ready
    if TURBO and TURBO._pending_settings and G and G.SETTINGS then
        TURBO.apply_settings()
    end
    -- Multiply dt to speed up all animations/timers
    local fast_dt = dt * (AI.speed_mult or 1)
    if _original_update then _original_update(fast_dt) end
    AI.update()
end

-- Kill all animation delays: make events complete instantly
local _original_add_event = nil
if G and G.E_MANAGER then
    _original_add_event = G.E_MANAGER.add_event
end

-- Hook Event:init to zero out delays
local _original_event_init = Event.init
Event.init = function(self, config)
    if config then
        config.delay = 0
        if config.ease then
            config.delay = 0
        end
    end
    _original_event_init(self, config)
end

-- Initialize on load
local _original_load = love.load
love.load = function(args)
    if _original_load then _original_load(args) end
    AI.init()
end
