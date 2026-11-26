from __future__ import annotations
from pathlib import Path
from typing import Any

from ..settings import SettingsRegistery
from .adapter import Adapter
from .. import console_mode
from .. import core

import json

SCHEMA_PATH = Path(core.package_path('contributes/Schema/sublime-package.json'))


def initialize_lsp_json_schema():
	if not SCHEMA_PATH.exists() or settings_schema_is_stale():
		generate_lsp_json_schema()


def settings_schema_is_stale() -> bool:
	'''Whether the schema file describes other settings than the package has now

	The file is generated, and was only ever generated when it was missing or an adapter was
	installed. A setting that was added, renamed or grouped since was then unknown to it, and
	LSP-json underlined it in the settings file as a property that is not allowed.
	'''
	try:
		contributions = json.loads(SCHEMA_PATH.read_text())['contributions']['settings']
		written = next(item['schema'] for item in contributions if 'Debugger.sublime-settings' in item.get('file_patterns', []))
	except Exception:
		return True
	# through json, as the file went: a tuple in the schema is a list there
	return written != json.loads(json.dumps(SettingsRegistery.schema()))


def generate_lsp_json_schema():
	adapters = Adapter.registered

	allOf: list[Any] = []
	installed_adapters: list[str] = []
	all_adapters: list[str] = []
	for adapter in adapters:
		for type in adapter.types:
			all_adapters.append(type)
			if adapter.installed_version:
				installed_adapters.append(type)

	definitions = {}
	debugger_snippets = []

	definitions['type'] = {
		'properties': {
			'type': {
				'type': 'string',
				'description': 'Type of configuration.',
				'enum': all_adapters,
			},
		},
		'required': ['type'],
	}

	definitions['type_installed'] = {
		'properties': {
			'type': {
				'type': 'string',
				'description': 'Type of configuration.',
				'enum': installed_adapters,
				'errorMessage': 'This adapter is not installed, install this adapter to get completions',
			},
		},
		'required': ['type'],
	}

	allOf.append(
		{
			'if': {
				'$ref': f'sublime://settings/debugger#/definitions/type',
			},
			'then': {'$ref': f'sublime://settings/debugger#/definitions/type_installed'},
			'else': {
				'$ref': f'sublime://settings/debugger#/definitions/type',
			},
		}
	)

	for adapter in adapters:
		schema = console_mode.in_schema(adapter.configuration_schema or {})
		snippets = adapter.configuration_snippets or []
		installed = adapter.installed_version

		types = adapter.types
		key = adapter.types[0]

		if not installed:
			continue

		if installed and not schema:
			core.info(f'Warning: {adapter.type}: schema not provided')

		if installed and not snippets:
			core.info(f'Warning: {adapter.type}: snippets not provided')

		requests: list[str] = []
		for request, value in schema.items():
			requests.append(request)

		definitions[key] = {
			'properties': {
				'request': {
					'type': 'string',
					'description': f'Request type of configuration.',
					'enum': requests,
				},
				'name': {
					'type': 'string',
					'description': 'Name of configuration which appears in the launch configuration drop down menu.',
				},
			},
			'required': ['type', 'name', 'request'],
		}

		for type in types:
			allOf.append(
				{
					'if': {
						'properties': {
							'type': {'const': type},
						},
						'required': ['type'],
					},
					'then': {'$ref': f'sublime://settings/debugger#/definitions/{key}'},
				}
			)

		for request, value in schema.items():
			# make sure all the default properties are defined here because we are setting additionalProperties to false
			value.setdefault('properties', {})
			value.setdefault('type', 'object')

			value['properties']['pre_debug_task'] = {
				'type': ['string', 'array'],
				'items': {'type': 'string'},
				'description': 'Name of the task to run before debugging starts, or a list of names run in that order. Debugging starts when the last of them is done, or ready for a task with a ready_regex',
			}
			value['properties']['post_debug_task'] = {
				'type': ['string', 'array'],
				'items': {'type': 'string'},
				'description': 'Name of the task to run after debugging ends, or a list of names run in that order',
			}
			value['properties']['log'] = {
				'type': 'object',
				'description': 'Saves what the program prints (stdout and stderr together) to a file, as well as showing it in the console or the terminal',
				'properties': {
					'file': {'type': 'string', 'description': 'Path of the file, from `cwd` or the project folder when it is not absolute. Its folder is created'},
					'append': {'type': 'boolean', 'description': 'Add to the file instead of starting it again on every run, false when not set'},
				},
				'required': ['file'],
				'additionalProperties': False,
			}
			value['properties']['envFile'] = {
				'type': ['string', 'array'],
				'items': {'type': 'string'},
				'description': 'A dotenv file, or a list of them, whose variables are laid under `env`',
			}
			# the same two values for every adapter, in place of whatever names it lists itself
			value['properties']['console'] = console_mode.SCHEMA
			value['properties']['osx'] = {
				'$ref': f'sublime://settings/debugger#/definitions/{key}.{request}',
				'description': 'MacOS specific configuration attributes',
			}
			value['properties']['windows'] = {
				'$ref': f'sublime://settings/debugger#/definitions/{key}.{request}',
				'description': 'Windows specific configuration attributes',
			}
			value['properties']['linux'] = {
				'$ref': f'sublime://settings/debugger#/definitions/{key}.{request}',
				'description': 'Linux specific configuration attributes',
			}

			definitions[f'{key}.{request}'] = value

			for type in types:
				allOf.append(
					{
						'if': {'properties': {'type': {'const': type}, 'request': {'const': request}}, 'required': ['name', 'type', 'request']},
						'then': {
							'unevaluatedProperties': False,
							'allOf': [
								{'$ref': f'sublime://settings/debugger#/definitions/type'},
								{'$ref': f'sublime://settings/debugger#/definitions/{key}'},
								{'$ref': f'sublime://settings/debugger#/definitions/{key}.{request}'},
							],
						},
					}
				)

		for snippet in snippets:
			debugger_snippets.append(console_mode.in_snippet(snippet))

	definitions['debugger_configuration'] = {
		'defaultSnippets': debugger_snippets,
		'allOf': allOf,
	}

	definitions['debugger_compound'] = {
		'properties': {
			'name': {
				'type': 'string',
				'description': 'Name of compound which appears in the launch configuration drop down menu.',
			},
			'configurations': {'type': 'array', 'description': 'Names of configurations that compose this compound configuration', 'items': {'type': 'string'}},
		},
		'required': ['name', 'configurations'],
	}

	definitions['debugger_input'] = {
		'properties': {
			'id': {'type': 'string', 'description': 'The name it is used by: ${input:id}'},
			'type': {
				'type': 'string',
				'enum': ['promptString', 'pickString'],
				'description': 'promptString asks for text, pickString offers the list in options. promptString when not set',
			},
			'description': {'type': 'string', 'description': 'What is asked'},
			'ask': {'type': 'string', 'enum': ['always', 'once'], 'description': 'always: asked on every start. once: asked the first time and used from then on, until Debugger: Ask Inputs Again. The inputs_ask setting when not set'},
			'default': {'type': ['string', 'number', 'boolean'], 'description': 'What is offered the first time. After that it is the last answer'},
			'options': {
				'type': 'array',
				'description': 'What a pickString is chosen from',
				'items': {
					'type': ['string', 'object'],
					'properties': {'label': {'type': 'string'}, 'value': {'type': 'string'}},
				},
			},
		},
		'required': ['id'],
	}

	definitions['debugger_task'] = {
		'properties': {
			'name': {
				'type': 'string',
				'description': 'Name of task',
			},
			'type':{
				"type": 'string',
				'description': 'The type of task to be used. shell: default option used to run shell commands specified in shell_cmd; sublime: option to run sublime command specified via "command" and "args"',
				'enum':['shell', 'sublime']
			},
			'shell_cmd': {
				'type': 'string',
				'description': 'Shell command to execute (used in case if type is not given or equal to "shell")',
			},
			'command':{
				'type':'string',
				'description':'Sublime command to execute with `window.run_command(command, args)` when type is specified as "sublime")'
			},
			'args':{
				'type':'object',
				'description':'Arguments provided to window.run_command when type is specified as "sublime"'
			},
			'background': {
				'type': 'boolean',
				'description': 'This task will run in the background and not prevent the debugger from starting',
			},
			'ready_regex': {
				'type': 'string',
				'description': 'For a task that never ends (a server, a watcher): a regular expression for the line it prints once it is ready. The debugger starts when a line of its output matches, the task keeps running in a tab of its own and is stopped when the session ends. Implies "background".',
			},
			'ready_timeout': {
				'type': 'number',
				'description': 'Seconds to wait for a line matching ready_regex before giving up, 30 when not set and 0 to wait for as long as it takes',
			},
			'env': {
				'type': 'object',
				'markdownDescription': 'Environment variables to use when running the shell command.\nExample:\n```\n{"KEY": "VALUE"}```',
			},
		},
		'required': ['name'],
		'additionalProperties': False,
	}


	definitions_schma = {
		'schema': {
			'$id': 'sublime://settings/debugger',
			'definitions': definitions,
		}
	}

	schema_debug_configurations = {
		'contributions': {
			'settings': [
				definitions_schma,
				{
					'file_patterns': ['/*.sublime-project'],
					'schema': {
						'properties': {
							'debugger_configurations': {
								'description': 'Debugger Configurations',
								'type': 'array',
								'items': {'$ref': f'sublime://settings/debugger#/definitions/debugger_configuration'},
							},
							'debugger_tasks': {
								'description': 'Debugger Tasks',
								'type': 'array',
								'items': {'$ref': f'sublime://settings/debugger#/definitions/debugger_task'},
							},
							'debugger_inputs': {
								'description': 'Debugger Inputs: values a configuration or a task asks for when it is started, used as ${input:id}',
								'type': 'array',
								'items': {'$ref': f'sublime://settings/debugger#/definitions/debugger_input'},
							},
							'debugger_compounds': {
								'description': 'Debugger Compounds',
								'type': 'array',
								'items': {'$ref': f'sublime://settings/debugger#/definitions/debugger_compound'},
							},
						},
					},
				},
				{
					'file_patterns': ['Debugger.sublime-settings'],
					'schema': SettingsRegistery.schema(),
				},
			]
		}
	}

	SCHEMA_PATH.write_text(json.dumps(schema_debug_configurations, indent='\t'))
