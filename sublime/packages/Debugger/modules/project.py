from __future__ import annotations
from pathlib import Path
from typing import Any, cast
from . import core
from . import dap

from .inputs import SelectProcess, PromptInput
from . import input_prompts

from .dap import Configuration, ConfigurationCompound, Task
from .settings import Settings

import sublime
import os

import contextlib


# where a project file is looked for in a folder of the window: the folder itself, then `.sublime`
PROJECT_FILE_FOLDERS = ('', '.sublime')
PROJECT_FILE_EXTENSION = '.sublime-project'


def find_project_file(window: sublime.Window) -> str | None:
	'''The `.sublime-project` file the debugger reads, whether or not the window was opened as that project

	A window that has a project open reads that one. A window that has only folders open reads the
	project file that is in one of them, so a folder opened without its project has its configurations.
	Of several in one folder the one named after the folder is taken, else the first by name.
	'''
	if project_name := window.project_file_name():
		return project_name

	for folder in window.folders():
		for sub in PROJECT_FILE_FOLDERS:
			directory = os.path.join(folder, sub) if sub else folder
			try:
				names = sorted(name for name in os.listdir(directory) if name.endswith(PROJECT_FILE_EXTENSION))
			except OSError:
				continue

			named_after_folder = os.path.basename(folder.rstrip(os.sep)) + PROJECT_FILE_EXTENSION
			if named_after_folder in names:
				return os.path.join(directory, named_after_folder)
			if names:
				return os.path.join(directory, names[0])

	return None


def read_project_data(window: sublime.Window) -> dict[str, Any] | None:
	'''What the project file says: from the window when it has the project open, else from the file'''
	if window.project_file_name():
		return cast(Any, window.project_data())

	location = find_project_file(window)
	if not location:
		return cast(Any, window.project_data())

	try:
		with open(location, 'r', encoding='utf-8') as file:
			data: Any = sublime.decode_value(file.read())
	except (OSError, ValueError) as error:
		core.info(f'Unable to read {location}: {error}')
		return cast(Any, window.project_data())

	return data if isinstance(data, dict) else {}


class Project:
	def __init__(self, window: sublime.Window):
		self.window = window
		self.on_updated = core.Event[None]()

		self.tasks: list[Task] = []
		self.compounds: list[ConfigurationCompound] = []
		self.configurations: list[Configuration] = []

		self.configuration_or_compound: Configuration | ConfigurationCompound | None = None

		# what `debugger_inputs` defines, and what each was last answered with
		self.inputs: list[input_prompts.InputDefinition] = []
		self.input_answers: dict[str, str] = {}

		# configurations that are in no file: generated to debug a test and listed beside the projects
		# own for as long as they are of use, so everything that works by configuration works for them
		self.transient: list[Configuration] = []
		# the last selection that was not one of those, which is the one worth remembering
		self.listed_selection: Configuration | ConfigurationCompound | None = None

	def dispose(self): ...

	@property
	def location(self) -> str | None:
		return find_project_file(self.window)

	@property
	def project_file_name(self) -> str | None:
		if project_name := self.location:
			return Path(project_name).name
		return ''


	@property
	def name(self) -> str:
		if self.configuration_or_compound:
			return self.configuration_or_compound.name

		return 'Add Configuration'

	def into_json(self) -> dict[str, Any]:
		# a generated configuration is gone the next time the project is opened, so what is saved is
		# the selection it took the place of
		selection = self.listed_selection if self.is_transient(self.configuration_or_compound) else self.configuration_or_compound

		return {
			'configuration_name': selection and selection.name,
			'configuration_id_ish': selection and selection.id_ish,
		}

	def is_transient(self, item: Configuration | ConfigurationCompound | None) -> bool:
		return any(item is configuration for configuration in self.transient)

	def add_transient(self, configuration: Configuration, keep: set[str] = set()) -> None:
		'''Lists a generated configuration, in place of one of the same name

		Each test that is debugged adds one, so the ones that are of no more use are dropped here: all
		but those named in `keep`, which is what is running, and the selected one.
		'''
		def stays(other: Configuration) -> bool:
			return other.name != configuration.name and (other.name in keep or other is self.configuration_or_compound)

		dropped = [other for other in self.transient if not stays(other)]
		self.transient = [other for other in self.transient if stays(other)] + [configuration]
		self.configurations = [other for other in self.configurations if not any(other is item for item in dropped)] + [configuration]
		self.on_updated()

	def load_from_json(self, json: dict[str, Any]) -> Configuration | ConfigurationCompound | None:
		configuration_name: str | None = json.get('configuration_name')
		configuration_id_ish: str | None = json.get('configuration_id_ish')

		if configuration_name and configuration_id_ish:
			self.load_configuration(configuration_name, configuration_id_ish)

	def load_configuration(self, configuration_name: str, configuration_id_ish: str = '', skip_update: bool = False):
		def find_matching_configuration():
			for compound in self.compounds:
				if compound.id_ish == configuration_id_ish:
					return compound
			for configuration in self.configurations:
				if configuration.id_ish == configuration_id_ish:
					return configuration

			for compound in self.compounds:
				if compound.name == configuration_name:
					return compound
			for configuration in self.configurations:
				if configuration.name == configuration_name:
					return configuration
			return None

		previous_configuration_or_compound = self.configuration_or_compound
		self.configuration_or_compound = find_matching_configuration()

		if self.configuration_or_compound is not None and not self.is_transient(self.configuration_or_compound):
			self.listed_selection = self.configuration_or_compound

		if previous_configuration_or_compound != self.configuration_or_compound:
			if not skip_update:
				self.on_updated()

			return True

		return False

	def get_task(self, name: str) -> Task:
		for task in self.tasks:
			if task.name == name:
				return task
		raise dap.Error(f'Unable to find task with name "{name}"')

	def active_configurations(self) -> list[Configuration]:
		if isinstance(self.configuration_or_compound, ConfigurationCompound):
			configurations: list[Configuration] = []
			for configuration_name in self.configuration_or_compound.configurations:
				configuration = None
				for c in self.configurations:
					if c.name == configuration_name:
						configuration = c
						break

				if configuration:
					configurations.append(configuration)
				else:
					raise dap.Error(f'Unable to find configuration with name "{configuration_name}" while evaluating compound "{self.configuration_or_compound.name}"')

			return configurations

		if isinstance(self.configuration_or_compound, Configuration):
			return [self.configuration_or_compound]

		return []

	@core.run
	async def open_project_configurations_file(self):
		project_name = self.location
		if not project_name:
			self.window.run_command('edit_settings', {'base_file': '${packages}/Debugger/Debugger.sublime-settings'})
			return None, None

		view = await core.sublime_open_file_async(self.window, project_name)
		region = view.find(r""""\s*debugger_configurations\s*"\s*:\s*\[""", 0)
		if region:
			view.show_at_center(region)

		return view, region

	@core.run
	async def insert_snippet(project: Project, snippet: str):
		try:
			view, region = await project.open_project_configurations_file()
			if not region or not view:
				raise dap.Error('Unable to find debugger_configurations')

			view.sel().clear()
			view.sel().add(sublime.Region(region.b, region.b))
			view.run_command('insert', {'characters': '\n'})
			view.run_command('insert_snippet', {'contents': snippet + ','})

		except dap.Error:
			core.exception()
			sublime.set_clipboard(snippet)
			core.display('Unable to insert configuration into sublime-project file: Copied to clipboard instead')

	def reload(self, console: dap.Console):
		core.info('ProjectConfiguration.reload')
		self._load_configurations(console)
		self.on_updated()

	def _extract_from_project_data(self, project_data: Any, key: str) -> list[tuple[Any, dap.SourceLocation]]:
		configurations: list[tuple[Any, dap.SourceLocation]] = []

		if location := self.location:
			source = dap.SourceLocation.from_path(location, line_regex=key)
			for configuration_or_file in project_data.get(key, []):
				configurations.append((configuration_or_file, source))

		if global_configurations := getattr(Settings, f'global_{key}'):
			# under `global` in the settings they are `configurations`, `tasks`, ... without the `debugger_`
			source = dap.SourceLocation.from_path('Debugger.sublime-settings', line_regex='"{}"'.format(key.replace('debugger_', '', 1)))
			configurations += map(lambda i: (i, source), global_configurations)

		# This is basically only for developing the Debugger package so we can have all the example configurations accessible
		debugger_include_examples = project_data.get('debugger_include_examples') == True
		if debugger_include_examples:
			from .commands.commands_configurations import ExampleProjects

			for example_project in ExampleProjects.example_projects:
				if not os.path.isabs(example_project):
					example_project = os.path.join(self.window.extract_variables()['folder'], example_project)

				with open(example_project, 'r') as file:
					contents = file.read()

				project_json: Any = sublime.decode_value(contents) or {}
				json: list[Any] = project_json.get(key, [])
				for configuration in json:
					configuration['$'] = {'project_path': os.path.dirname(example_project), 'folder': os.path.dirname(example_project)}

				source = dap.SourceLocation.from_path(example_project, line_regex=key)
				configurations.extend(map(lambda i: (i, source), json))

		return configurations

	def project_data(self)-> dict[str, Any]:
		return cast(Any, read_project_data(self.window))

	def _load_configurations(self, console: dap.Console):
		data = self.project_data()
		if data is None:
			core.info('No project associated with window')
			data = {}

		# add the empty debugger_configurations if needed
		# only into a project the window has open: a file that was found in a folder is the users to edit
		elif not 'debugger_configurations' in data and self.window.project_file_name():
			core.info('Adding `debugger_configurations` to sublime-project data')
			data['debugger_configurations'] = []
			self.window.set_project_data(data)

		tasks: list[Task] = []
		configurations: list[Configuration] = []
		compounds: list[ConfigurationCompound] = []

		@contextlib.contextmanager
		def report_issues(name: str, json: Any, source: dap.SourceLocation):
			try:
				yield
			except KeyError as e:
				console.log('warn', f'{source.name}: {name} requires {e} field', source)
				console.info(core.json_encode(json, pretty=True))

		for json, source in self._extract_from_project_data(data, 'debugger_configurations'):
			with report_issues('Configuration', json, source):
				configurations.append(Configuration.from_json(json, len(configurations), source))

		for json, source in self._extract_from_project_data(data, 'debugger_compounds'):
			with report_issues('Configuration Compound', json, source):
				compounds.append(ConfigurationCompound.from_json(json, len(compounds), source))

		for json, source in self._extract_from_project_data(data, 'debugger_tasks'):
			with report_issues('Task', json, source):
				tasks.append(Task.from_json(json, source))

		entries = [json for json, _ in self._extract_from_project_data(data, 'debugger_inputs')]
		self.inputs, problems = input_prompts.definitions(entries)
		for problem in problems:
			console.log('warn', f'debugger_inputs: {problem}')

		# the generated ones are not in the data that was just read, and may be running
		self.configurations = configurations + self.transient
		self.compounds = compounds
		self.tasks = tasks

		# reselect the old configuration
		if self.configuration_or_compound:
			self.load_configuration(self.configuration_or_compound.name, self.configuration_or_compound.id_ish, skip_update=True)

	def is_source_file(self, view: sublime.View) -> bool:
		return bool(self.source_file(view))

	def source_file(self, view: sublime.View) -> str | None:
		if view.window() != self.window:
			return None

		if view.settings().get('debugger.view.source') is False:
			return None

		return view.file_name()

	def variables(self) -> dict[str, str]:
		'''The variables of the window, with those of the project file when the window has none open'''
		variables: dict[str, str] = dict(self.window.extract_variables())

		if 'project' not in variables and (location := self.location):
			name = os.path.basename(location)
			base, extension = os.path.splitext(name)
			variables['project'] = location
			variables['project_path'] = os.path.dirname(location)
			variables['project_name'] = name
			variables['project_base_name'] = base
			variables['project_extension'] = extension.lstrip('.')

		return variables

	def extract_variables(self):
		variables = self.variables()

		# patch in some vscode variables
		if folder := variables.get('folder'):
			variables['workspaceFolder'] = folder
			variables['workspaceRoot'] = folder

		variables['packages'] = sublime.packages_path()

		inputs: dict[str, dap.Input] = {
			'select_process': SelectProcess(),
		}

		# new for every start, so each start asks, and the same for everything started together,
		# so they are asked once
		for definition in self.inputs:
			inputs[definition.variable] = PromptInput(definition, self.input_answers, Settings.inputs_ask)

		for key, value in variables.items():
			inputs[key] = dap.InputLiteral(value)

		return inputs

	def current_file_line_column(self) -> tuple[str, int, int]:
		view = self.window.active_view()
		if not view:
			raise dap.Error('No open view')

		file = self.source_file(view)
		if not file:
			raise dap.Error('No source file selected or file is not saved')

		r, c = view.rowcol(view.sel()[0].begin())
		return file, r + 1, c + 1

	def current_file_line(self) -> tuple[str, int]:
		line, col, _ = self.current_file_line_column()
		return line, col
