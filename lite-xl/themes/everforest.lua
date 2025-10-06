local style = require "core.style"
local common = require "core.common"

style.background = { common.color "#282d30" }
style.background2 = { common.color "#282d30" }
style.background3 = { common.color "#374145" } -- Lighter background for popups/tooltips
style.text = { common.color "#D3C6AA" }
style.caret = { common.color "#A7C080" }
style.accent = { common.color "#A7C080" }
style.nagbar = { common.color "#df787a" }

style.dim = { common.color "#859289" }
style.divider = { common.color "#272E33" }
style.selection = { common.color "#573e4c" }
style.line_number = { common.color "#c6b99e" }
style.line_number2 = { common.color "#c6b99e" }
style.line_highlight = { common.color "#374145" }
style.scrollbar = { common.color "#4F5B58" }
style.scrollbar2 = { common.color "#4F5B58" }
style.scrollbar_track = { common.color "#272E33" }

style.syntax["normal"] = { common.color "#D3C6AA" }
style.syntax["symbol"] = { common.color "#D3C6AA" }
style.syntax["comment"] = { common.color "#4F5B58" }
style.syntax["keyword"] = { common.color "#E67E80" }
style.syntax["keyword2"] = { common.color "#E67E80" }
style.syntax["number"] = { common.color "#D699B6" }
style.syntax["literal"] = { common.color "#7FBBB3" }
style.syntax["string"] = { common.color "#83C092" }
style.syntax["operator"] = { common.color "#DBBC7F" }
style.syntax["function"] = { common.color "#A7C080" }

-- Lint+ diagnostic colors (referencing theme syntax colors)
style.lint = style.lint or {}
style.lint.info = style.syntax["literal"]     -- Aqua/Cyan
style.lint.hint = style.syntax["function"]    -- Green
style.lint.warning = style.syntax["operator"] -- Yellow
style.lint.error = style.syntax["keyword"]    -- Red
