-- put user settings here
-- this module will be loaded after everything else when the application starts
-- it will be automatically reloaded when saved

local core = require "core"
local keymap = require "core.keymap"
local config = require "core.config"
local style = require "core.style"
local command = require "core.command"
local common = require "core.common"
local lspconfig = require "plugins.lsp.config"
local autocomplete = require "plugins.autocomplete"
local CommandView = require "core.commandview"
local DocView = require "core.docview"


-- local lsp = require "plugins.lsp"
-- local autocomplete = require "plugins.autocomplete"

-- Configure autocomplete behavior
config.plugins.autocomplete = {
    -- Maximum suggestions to show
    max_suggestions = 20
}

-- Configure lintplus to show dotted underlines for errors
config.lint = {
    -- Use dotted underlines for all diagnostic messages
    lens_style = "blank",

    -- Configure pretty names for message types in status bar
    kind_pretty_names = {
        info = "Info",
        hint = "Hint",
        warning = "Warning",
        error = "Error"
    }
}

-- Lint colors are defined in the theme file (colors/everforest.lua)
-- The theme sets style.lint.info, style.lint.hint, style.lint.warning, style.lint.error
-- No need to override them here unless you want different colors

-- Configure LSP to show diagnostics
config.plugins.lsp = {
    -- Enable mouse hover for diagnostics
    mouse_hover = true,
    -- Delay before showing the diagnostic popup (in milliseconds)
    mouse_hover_delay = 300,
    -- Show diagnostics (enables lintplus integration)
    show_diagnostics = true,
    -- Show diagnostics in status bar
    show_diagnostics_in_statusbar = true,
    -- Delay before updating diagnostics
    diagnostics_delay = 500,
}

-- Use system Node.js and yaml-language-server from Homebrew
lspconfig.yamlls.setup(common.merge({
    command = {
        "/opt/homebrew/bin/node",
        "/opt/homebrew/lib/node_modules/yaml-language-server/bin/yaml-language-server",
        "--stdio"
    },
}, config.plugins.lsp_yaml or {}))

-- Use system Node.js and yaml-language-server from Homebrew
lspconfig.jsonls.setup(common.merge({
    command = {
        "/opt/homebrew/bin/node",
        "/opt/homebrew/bin/vscode-json-languageserver",
        "--stdio"
    },
}, config.plugins.lsp_json or {}))

lspconfig.gopls.setup {
    command = {
        "/Users/shubham.dogra/go/bin/gopls"
    },
    env = {
        PATH = "/opt/homebrew/opt/go@1.23/bin",
        GO111MODULE = "on"
    },
    settings = {
        gopls = {
            analyses = {
                unusedparams = true,
                shadow = true,
            },
            staticcheck = true,
            usePlaceholders = true,
            completeUnimported = true,
            -- Add diagnostic delay
            diagnosticsDelay = "500ms",
            -- Complete function calls
            completeFunctionCalls = true,
        }
    },
    verbose = true
}


------------------------------ Themes ----------------------------------------

-- light theme:
-- core.reload_module("colors.summer")

--------------------------- Key bindings -------------------------------------

-- key binding:
-- keymap.add { ["ctrl+escape"] = "core:quit" }

-- pass 'true' for second parameter to overwrite an existing binding
-- keymap.add({ ["ctrl+pageup"] = "root:switch-to-previous-tab" }, true)
-- keymap.add({ ["ctrl+pagedown"] = "root:switch-to-next-tab" }, true)

------------------------------- Fonts ----------------------------------------

-- customize fonts:
-- style.font = renderer.font.load(DATADIR .. "/fonts/FiraSans-Regular.ttf", 14 * SCALE)
-- style.code_font = renderer.font.load(DATADIR .. "/fonts/JetBrainsMono-Regular.ttf", 14 * SCALE)
--
-- DATADIR is the location of the installed Lite XL Lua code, default color
-- schemes and fonts.
-- USERDIR is the location of the Lite XL configuration directory.
--
-- font names used by lite:
-- style.font          : user interface
-- style.big_font      : big text in welcome screen
-- style.icon_font     : icons
-- style.icon_big_font : toolbar icons
-- style.code_font     : code
--
-- the function to load the font accept a 3rd optional argument like:
--
-- {antialiasing="grayscale", hinting="full", bold=true, italic=true, underline=true, smoothing=true, strikethrough=true}
--
-- possible values are:
-- antialiasing: grayscale, subpixel
-- hinting: none, slight, full
-- bold: true, false
-- italic: true, false
-- underline: true, false
-- smoothing: true, false
-- strikethrough: true, false

------------------------------ Plugins ----------------------------------------

-- disable plugin loading setting config entries:

-- disable plugin detectindent, otherwise it is enabled by default:
-- config.plugins.detectindent = false

-- Disable terminal plugin to avoid errors (missing native library)
config.plugins.terminal = false

---------------------------- Miscellaneous -------------------------------------

-- modify list of files to ignore when indexing the project:
config.ignore_files = {
    -- folders
    "^%.svn/", "^%.git/", "^%.hg/", "^CVS/", "^%.Trash/", "^%.Trash%-.*/",
    "^node_modules/", "^%.cache/", "^__pycache__/",
    -- files
    "%.pyc$", "%.pyo$", "%.exe$", "%.dll$", "%.obj$", "%.o$",
    "%.a$", "%.lib$", "%.so$", "%.dylib$", "%.ncb$", "%.sdf$",
    "%.suo$", "%.pdb$", "%.idb$", "%.class$", "%.psd$", "%.db$",
    "^desktop%.ini$", "^%.DS_Store$", "^%.directory$",
}


keymap.add_direct {
    -- Delete lines
    ["shift+cmd+k"] = "doc:delete-lines",
    ["cmd+backspace"] = "doc:delete-lines",

    ["cmd+up"] = "doc:move-lines-up",
    ["cmd+down"] = "doc:move-lines-down",

    -- Indentation
    -- ["tab"] = "doc:indent",  -- Commented out to allow autocomplete to use tab
    ["ctrl+]"] = "doc:indent",
    ["shift+tab"] = "doc:unindent",
    ["ctrl+["] = "doc:unindent",

    -- Line navigation
    ["end"] = "doc:move-to-end-of-line",
    ["option+right"] = "doc:move-to-end-of-line",
    ["home"] = "doc:move-to-start-of-indentation",
    ["option+left"] = "doc:move-to-start-of-line",

    -- Selection
    ["shift+cmd+right"] = "doc:select-to-end-of-line",
    ["shift+end"] = "doc:select-to-end-of-line",
    ["cmd+right"] = "doc:select-to-end-of-line",
    ["cmd+left"] = "doc:select-to-start-of-line",

    -- find replace only active when find/replace dialog is open

    ["ctrl+return"] = "find-replace:select-next",
    ["shift+return"] = "find-replace:select-previous",
    ["option+return"] = "find-replace:select-add-all",
    ["cmd+return"] = "find-replace:select-add-all",

    -- LSP
    ["alt+d"] = "lsp:goto-definition",
    ["cmd+i"] = "lsp:goto-definition",
}

-- Add conditional bindings for autocomplete
keymap.add {
    -- Tab key: use for autocomplete when available, otherwise indent
    ["tab"] = function()
        if autocomplete.is_open() then
            command.perform("autocomplete:complete")
        else
            command.perform("doc:indent")
        end
    end,

    ["return"] = function()
        -- Check for autocomplete first
        if autocomplete.is_open() then
            command.perform("autocomplete:complete")
            return true
        end

        -- Check if we're in the find/replace command view
        --         local view = core.active_view
        --         if view:is(CommandView) then
        --             -- Check if this is the find text dialog
        --             if view.label and view.label:find("Find") then
        --                 -- Perform find next when pressing return in find dialog
        --                 command.perform("find-replace:select-next")
        --                 return true
        --             end
        --         end

        -- Return false to let the default return key behavior handle it
        -- This allows return to work in dialogs, command palette, etc.
        return false
    end
}
