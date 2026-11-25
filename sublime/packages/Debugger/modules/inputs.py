from __future__ import annotations
from typing import Any
from os import name

from .dap.configuration import Input

from . import core
from . import ui
from . import dap
from . import input_prompts


class SelectProcess(Input):
	async def resolve(self):
		try:
			import psutil
		except ImportError:
			raise dap.Error('Unable to select a process, `psutil` is not available')

		items: list[ui.InputListItem] = []
		selected_proc: Any = None

		def select(proc: Any):
			nonlocal selected_proc
			selected_proc = proc

		for proc in psutil.process_iter(['pid', 'name', 'username']):
			items.append(ui.InputListItem(lambda proc=proc: select(proc), proc.name() + f'\t{proc.pid}' + f'\t{proc.username()}'))

		await ui.InputList('Select a process to start debugging')[items]

		if selected_proc:
			return f'{selected_proc["pid"]}'

		raise core.CancelledError()


class PromptInput(Input):
	'''An input of `debugger_inputs`: asked for when a configuration that uses it is started

	Asked once however many times it is used: a configuration that has `${input:port}` in two
	places, or two configurations of a compound that both have it, are one question. The answer
	is remembered and is what the next start is offered first, so starting the same thing again
	is one press of enter.
	'''

	# the command palette is one place: a second question waits for the first to be answered
	asking: core.Future | None = None

	def __init__(self, definition: input_prompts.InputDefinition, answers: dict[str, str], ask: Any = input_prompts.ALWAYS):
		self.definition = definition
		self.answers = answers
		# the `inputs_ask` setting, for an input that does not say how often it is asked
		self.default_ask = ask
		self.answer: core.Future | None = None

	async def resolve(self) -> str:
		if not self.answer:
			self.answer = core.run(self.ask())
		return await self.answer

	async def ask(self) -> str:
		# asked once and answered: what it was answered with, without a question
		last = self.answers.get(self.definition.id)
		if last is not None and not self.definition.asked(last, self.default_ask):
			return last

		while PromptInput.asking:
			await PromptInput.asking

		PromptInput.asking = turn = core.Future()
		try:
			definition = self.definition
			if definition.type == input_prompts.PICK:
				value = await self.pick()
			else:
				value = await self.prompt()

			if value is None:
				# escape is not an answer, and a configuration with a hole in it is not started
				raise core.CancelledError()

			self.answers[definition.id] = value
			return value

		finally:
			PromptInput.asking = None
			turn.set_result(None)

	async def prompt(self) -> str | None:
		definition = self.definition
		answered: list[str] = []
		await ui.InputText(answered.append, definition.description or definition.id, definition.initial(self.answers.get(definition.id)))
		return answered[0] if answered else None

	async def pick(self) -> str | None:
		definition = self.definition
		answered: list[str] = []
		start = definition.initial(self.answers.get(definition.id))

		items = [ui.InputListItem(lambda value=option.value: answered.append(value), option.label) for option in definition.options]
		index = next((index for index, option in enumerate(definition.options) if option.value == start), 0)

		await ui.InputList(definition.description or definition.id, index)[items]
		return answered[0] if answered else None
