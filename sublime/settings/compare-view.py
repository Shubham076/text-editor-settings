import sublime
import sublime_plugin

class ToggleCompareViewCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        window = self.view.window()
        views = window.views()
        count = 0
        for view in views:
            view_name = view.name()
            print(view_name)
            if view_name is not None:
                 if '(active)' in view_name.lower() or '(other)' in view_name.lower():
                    count += 1

        # print(count)
        is_compare_open = (count == 2);
        if is_compare_open:
            print("Side By Side compare: closing compare view")
            window.run_command("close")
        else:
            print("Side By Side compare: Opening compare view")
            self.view.window().run_command('sbs_compare')
