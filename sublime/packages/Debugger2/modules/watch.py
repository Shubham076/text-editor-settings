from __future__ import annotations
from dataclasses import dataclass, field
from typing import Awaitable
from . import core
from . import ui
from . import dap


@dataclass
class WatchExpression:
	value: str
	message = ''
	evaluate_response: dap.Variable | None = None
	results: dict[dap.Session, dap.Variable | Exception] = field(default_factory=dict)
	on_updated: core.Event = field(default_factory=core.Event)

	def into_json(self) -> core.JSON:
		return core.JSON(
			{
				'value': self.value,
			}
		)

	@staticmethod
	def from_json(json: core.JSON) -> WatchExpression:
		return WatchExpression(
			json['value'],
		)


class Watch(core.Dispose):
	on_updated = core.Event[None]()
	expressions: list[WatchExpression] = []

	def __init__(self, debugger: dap.Debugger):
		self.debugger = debugger
		self.expressions = []
		self.on_updated = core.Event[None]()

		self.dispose_add(
			debugger.on_session_thread_or_frame_updated.add(self._on_thread_or_frame_updated),
			debugger.on_session_removed.add(self.clear_session_data),
		)

	def _on_thread_or_frame_updated(self, session: dap.Session):
		self.clear_session_data(session)
		if session.selected_frame:
			self.evaluate(session, session.selected_frame)

	def load_json(self, json: list[core.JSON]):
		self.expressions = list(map(lambda j: WatchExpression.from_json(j), json))
		self.on_updated()

	def into_json(self) -> list[core.JSON]:
		return list(map(lambda e: e.into_json(), self.expressions))

	def add(self, value: str) -> None:
		expression = WatchExpression(value)
		self.expressions.append(expression)
		self.on_updated()

		# just re-evaluate all the expressions since we just added one
		for session in self.debugger.sessions:
			if session.selected_frame:
				self.evaluate(session, session.selected_frame)

	@core.run
	async def evaluate(self, session: dap.Session, frame: dap.StackFrame) -> None:
		results: list[Awaitable[dap.EvaluateResponse]] = []
		expressions = [(expression, expression.value) for expression in self.expressions]
		for expression, value in expressions:
			results.append(session.evaluate_expression(value, 'watch'))

		evaluations = await core.gather_results(*results)
		if session not in self.debugger.sessions or session.selected_frame is not frame or not session.is_paused:
			return
		for (expression, value), evaluation in zip(expressions, evaluations):
			if expression in self.expressions and expression.value == value:
				self.evaluated(session, expression, evaluation)
		self.on_updated()

	async def evaluate_expression(self, session: dap.Session, expression: WatchExpression) -> None:
		try:
			result = await session.evaluate_expression(expression.value, 'watch')
			self.evaluated(session, expression, result)
		except dap.Error as result:
			self.evaluated(session, expression, result)
		self.on_updated()

	def evaluated(self, session: dap.Session, expression: WatchExpression, evaluation: Exception | dap.EvaluateResponse):
		if isinstance(evaluation, Exception):
			expression.message = str(evaluation)
			expression.evaluate_response = None
			expression.results[session] = evaluation
		else:
			expression.message = ''
			expression.evaluate_response = dap.Variable.from_evaluate(session, expression.value, evaluation)
			expression.results[session] = expression.evaluate_response

	def clear_session_data(self, session: dap.Session):
		for expression in self.expressions:
			expression.results.pop(session, None)
			if expression.evaluate_response and expression.evaluate_response.session is session:
				expression.message = ''
				expression.evaluate_response = None
		self.on_updated()

	def edit(self, expression: WatchExpression, value: str):
		'''Changes what an expression watches, keeping its place in the list'''
		if not value or value == expression.value:
			return

		expression.value = value
		expression.results.clear()
		expression.message = ''
		expression.evaluate_response = None
		self.on_updated()

		for session in self.debugger.sessions:
			if session.selected_frame:
				self.evaluate(session, session.selected_frame)

	def remove(self, expression: WatchExpression):
		self.expressions.remove(expression)
		self.on_updated()

	def remove_all(self):
		self.expressions.clear()
		self.on_updated()
