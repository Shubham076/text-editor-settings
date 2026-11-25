from __future__ import annotations


class ViewSettings:
	def __init__(self, view, values):
		self.view = view
		self.values = dict(values)
		settings = view.settings()
		self.previous = {key: (settings.has(key), settings.get(key)) for key in values}
		for key, value in values.items():
			settings.set(key, value)

	def dispose(self):
		if not self.view.is_valid():
			return
		settings = self.view.settings()
		for key, (present, value) in self.previous.items():
			if present:
				settings.set(key, value)
			else:
				settings.erase(key)
		self.previous.clear()
