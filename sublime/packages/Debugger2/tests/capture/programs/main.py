from agentic_plugin_installer.policy import PluginOverride

# short repr, but the values are big nested structures
short_keys_big_values = {"a": {"x": 1, "y": {"deep": [1, 2, 3], "more": {"z": 9}}},
                         "b": {"p": 2, "q": {"deep": [4, 5, 6], "more": {"z": 8}}}}
# short repr, one nested object
short_key_one_obj = {"k": PluginOverride(plugin_id="claude-code", auto_install="disabled")}
# short repr, value is a long string
short_key_long_str = {"url": "https://downloads.prompt.security/releases/latest/agentic-plugins/installer-darwin-arm64.tar.gz"}
# genuinely flat and short
flat_scalars = {"a": 1, "b": 2}
flat_list = [1, 2, 3]
flat_strs = ["ok", "yes"]
# short list holding nested lists
list_of_lists = [[1, 2], [3, 4]]
list_of_objs = [PluginOverride(plugin_id="a"), PluginOverride(plugin_id="b")]
empty_d, empty_l = {}, []
mixed = {"n": 1, "sub": {"deep": 1}}
print(short_keys_big_values, short_key_one_obj, short_key_long_str, flat_scalars,
      flat_list, flat_strs, list_of_lists, list_of_objs, empty_d, empty_l, mixed)  # BREAK
