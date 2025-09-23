import sublime
import sublime_plugin

class ToggleStatusViewCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        is_open = False
        window = self.view.window()
        views = window.views()
        for view in views:
            view_name = view.name()
            if view_name is not None and 'STATUS:' in view_name.upper():
                print("Status view found. Closing it.")
                window.focus_view(view)
                window.run_command("close_file")
                is_open = True
                break

        if not is_open:
            print("GitSavvy: Opening status view")
            self.view.window().run_command('gs_show_status')
