from __future__ import annotations
from typing import TYPE_CHECKING, Any, Dict, cast
import re

from . import Error
from .. import core

if TYPE_CHECKING:
	from .variable import SourceLocation


class Input:
	def __await__(self):
		return self.resolve().__await__()

	async def resolve(self) -> str: ...


class InputLiteral(Input):
	def __init__(self, value: str) -> None:
		super().__init__()
		self.value = value

	async def resolve(self) -> str:
		return self.value


ConfigurationVariables = Dict[str, Input]


class Configuration(Dict[str, Any]):
	def __init__(self, name: str, index: int, type: str, request: str, all: dict[str, Any], source: SourceLocation | None = None):
		super().__init__(all)

		self.name = name
		self.id_ish = f'configuration_{name}_{index}'
		self.type = type
		self.request = request
		self.source = source

	@staticmethod
	def from_json(json: dict[str, Any], index: int, source: SourceLocation | None = None) -> Configuration:
		return Configuration(json['name'], index, json['type'], json['request'], json, source)

	async def Expanded(self, tasks: list[Task], variables: ConfigurationVariables):
		variables, json = await async_expand_variables_and_platform(self, variables)
		return ConfigurationExpanded(self, variables, json)


class ConfigurationExpanded(Configuration):
	def __init__(self, configuration: Configuration, variables: ConfigurationVariables, json: dict[str, Any]):
		super().__init__(configuration.name, -1, configuration.type, configuration.request, json, configuration.source)
		self.id_ish = configuration.id_ish

		# as it was written in the project, before the variables were filled in: what tells a
		# configuration that was edited since from one that was not (`configurations.restart`)
		self.written: dict[str, Any] = dict(configuration)
		self.variables = variables
		# the tasks named by `pre_debug_task` and `post_debug_task`, in the order they are run
		self.pre_debug_tasks: list[TaskExpanded] = []
		self.post_debug_tasks: list[TaskExpanded] = []


def task_names(value: Any, key: str = 'pre_debug_task') -> list[str]:
	'''The tasks `pre_debug_task` or `post_debug_task` names: one name, or a list of them run in order'''
	if not value:
		return []
	if isinstance(value, str):
		return [value]
	if isinstance(value, list) and all(isinstance(name, str) and name for name in value):
		return list(value)

	raise Error(f'`{key}` has to be the name of a task or a list of names')


class ConfigurationCompound:
	def __init__(self, name: str, index: int, configurations: list[str], source: SourceLocation | None = None) -> None:
		self.name = name
		self.id_ish = f'compound_{name}_{index}'
		self.configurations = configurations
		self.source = source

	@staticmethod
	def from_json(json: dict[str, Any], index: int, source: SourceLocation | None = None) -> ConfigurationCompound:
		return ConfigurationCompound(json['name'], index, json['configurations'], source)


class Task(Dict[str, Any]):
	def __init__(self, arguments: dict[str, Any], source: SourceLocation | None = None) -> None:
		super().__init__(arguments)
		self.name = arguments['name']
		self.source = source

	@staticmethod
	def from_json(json: dict[str, Any], source: SourceLocation | None = None):
		return Task(json, source)

	async def Expanded(self, variables: ConfigurationVariables, allow_cmd: bool = False):
		variables, json = await async_expand_variables_and_platform(self, variables)
		return TaskExpanded(self, variables, json, allow_cmd)


class TaskExpanded(Task):
	def __init__(self, task: Task, variables: ConfigurationVariables, json: dict[str, Any], allow_cmd: bool):
		super().__init__(json, task.source)

		shell_cmd: str | None = json.get('shell_cmd')
		# possible types are:
		# - 'shell': for system command execution like 'shell_cmd' or 'cmd'
		# - 'sublime': for the sublime window command
		type = json.get('type', 'shell')

		# we make this an error because `shell_cmd` errors show up in the sublime console in a way we cannot detect making it appear broken with no error
		if type == 'shell' and not allow_cmd and json.get('cmd'):
			raise Error('`cmd` is not supported use `shell_cmd` in task configuration', source=task.source)

		if 'name' in json:
			name = json['name']
		else:
			# Forcing a name
			raise Error('expecting `name`', source=task.source)

		self.variables = variables
		self.name: str = name
		self.type: str = type
		self.background: bool = json.get('background', False)
		self.start_file_regex: str | None = json.get('start_file_regex')
		self.end_file_regex: str | None = json.get('end_file_regex')

		# what a task that never ends prints once it can be worked with, and how long it is given
		# to print it. A task that has one is a background task whether or not it says so: there
		# is nothing else to wait for the signal of
		self.ready_regex: str | None = json.get('ready_regex')
		self.ready_timeout: Any = json.get('ready_timeout')
		if self.ready_regex:
			self.background = True

		self.depends_on: list[str]|None = json.get('depends_on')
		self.depends_on_order: str|None = json.get('depends_on_order')


async def async_expand_variables(json: Any, variables: ConfigurationVariables, supress_errors: bool = False):
	'''`json` with every `${variable}` in it filled in, as a new value: what is handed in is left as it was

	A configuration is expanded each time it is started, from the configuration as it is written.
	Filling the lists and objects inside it in where they stand would leave the answers in place
	of the variables, and the second start would have nothing to ask for or to look up: an
	`${input:name}` answered once and for all, a `${file}` stuck on the file of the first run.
	'''
	if type(json) is str:
		regex = re.compile(r'(\${([^}]*)})')
		for match, key in regex.findall(json):
			if value := variables.get(key):
				value = await value.resolve()

				json = json.replace(match, value)

			elif not supress_errors:
				error = f'Unable to expand variable ${{{key}}}, available variables\n\n'
				for variable in variables:
					error += f'${{{variable}}}\n'

				raise Error(error)

		return json

	if isinstance(json, dict):
		return {key: await async_expand_variables(value, variables, supress_errors) for key, value in json.items()}

	if isinstance(json, list):
		return [await async_expand_variables(value, variables, supress_errors) for value in json]

	return json


async def async_expand_variables_and_platform(json: dict[str, Any], variables: ConfigurationVariables):
	json = json.copy()

	# This allows us to add a list of variables to each configuration which can be use throughout the configuration.
	# Its mostly so we can redefine $project_path when specifying a project file in debugger_configurations so $project_path refers to the correct location
	if extra_variables := json.get('$'):
		del json['$']

		variables = variables.copy()
		for key in extra_variables:
			variables[key] = InputLiteral(extra_variables[key])

	platform = None
	if core.platform.osx:
		platform = json.get('osx')
	elif core.platform.linux:
		platform = json.get('linux')
	elif core.platform.windows:
		platform = json.get('windows')

	if platform:
		for key, value in platform.items():
			json[key] = value

	# expanded whether or not there is a variable to fill in: it is also what makes the lists and
	# objects inside the result its own, so nothing done to them reaches the configuration
	# With no variables at all nothing is looked up, as before: the command of a terminal an
	# adapter asked for is expanded with none, and a `${...}` in it is the shells
	json = cast(dict, await async_expand_variables(json, variables or {}, supress_errors=not variables))

	return variables, json
