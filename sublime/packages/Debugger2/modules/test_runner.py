from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable

import ast
import os
import re
import shlex

'''Finding the tests in a file and the configuration that debugs one of them

Nothing here touches sublime or a debugger: text in, tests out, and a test in, a configuration out.
That keeps every language a pair of plain functions, and it is what lets the whole of this be tested
without an editor.

A language is added by writing the functions of a `Language` for it and listing it in `LANGUAGES`.
'''


@dataclass(frozen=True)
class Test:
	# what the runner calls it, which is what gets passed to it to run just this one
	name: str
	# where its declaration starts in the text, the icon goes at the head of that line
	offset: int
	# where its body ends, a cursor between the two is in this test
	end: int


@dataclass(frozen=True)
class Language:
	# the key of this language in `test_configurations` and `debugger_test_configurations`
	key: str
	matches: Callable[[str], bool]
	find: Callable[[str], 'list[Test]']
	# (file, name of a test) to the configuration that debugs it. This may look around the disk for
	# the root of a project or a build file, so it is for when a test is started
	configuration: Callable[[str, str], 'dict[str, Any]']
	# (file, name of a test) to the name of that configuration, which is how a running test is found.
	# Asked for every icon each time they are drawn, so it only looks at its arguments
	label: Callable[[str, str], str]
	# a configuration, with the users values laid over it and its variables filled in, to the lines
	# that say what it runs. They are printed when it starts
	command: Callable[[Any], 'list[str]']
	# Whether what the runner writes to stderr is its report rather than errors. Jest writes every
	# result there, and stderr in red made a run that passed read as one that failed
	stderr_is_output: bool = False


def above(directory: str, found: Callable[[str], bool]) -> str | None:
	'''The nearest of a directory and the ones it is in that `found` says yes to'''
	while True:
		if found(directory):
			return directory

		parent = os.path.dirname(directory)
		if parent == directory:
			return None

		directory = parent


def has_any(*names: str) -> Callable[[str], bool]:
	return lambda directory: any(os.path.exists(os.path.join(directory, name)) for name in names)


def shell(directory: Any, command: list[Any]) -> str:
	'''A command as it would be typed to run it in a directory'''
	line = ' '.join(shlex.quote(str(part)) for part in command)
	return f'cd {shlex.quote(str(directory))} && {line}' if directory else line


def c_masked(text: str, quotes: str, multiline: tuple[str, ...]) -> str:
	'''What `go_masked` does, for the languages whose strings and comments are those of java and javascript

	`quotes` open a string that ends on its line, `multiline` are the delimiters of one that does not.
	'''
	out = list(text)
	i, n = 0, len(text)

	def blank(start: int, end: int) -> None:
		for at in range(start, min(end, n)):
			if out[at] != '\n':
				out[at] = ' '

	def closing(start: int, delimiter: str, one_line: bool) -> int:
		end = start
		while end < n and not text.startswith(delimiter, end) and not (one_line and text[end] == '\n'):
			end += 2 if text[end] == '\\' else 1
		return min(end, n)

	while i < n:
		if text.startswith('//', i):
			end = text.find('\n', i)
			end = n if end < 0 else end
			blank(i, end)
			i = end
			continue

		if text.startswith('/*', i):
			end = text.find('*/', i + 2)
			end = n if end < 0 else end + 2
			blank(i, end)
			i = end
			continue

		delimiter = next((delimiter for delimiter in multiline if text.startswith(delimiter, i)), None)
		one_line = delimiter is None
		if one_line and text[i] in quotes:
			delimiter = text[i]

		if delimiter:
			end = closing(i + len(delimiter), delimiter, one_line)
			blank(i + len(delimiter), end)
			i = end + len(delimiter)
		else:
			i += 1

	return ''.join(out)


# -- go ------------------------------------------------------------------------------------------

# `go test` runs a top level function whose name is one of these words followed by anything that does
# not start with a lower case letter: `TestPlugin` and `Test_plugin` are tests, `Testify` is a helper
# gofmt puts the brace that closes a top level function at the start of a line, and nothing else there
GO_END = re.compile(r'^}', re.MULTILINE)
GO_TEST = re.compile(r'^func[ \t]+((Test|Benchmark|Fuzz|Example)(\w*))[ \t]*\(', re.MULTILINE)


def go_find(text: str) -> list[Test]:
	tests: list[Test] = []
	masked = None

	for match in GO_TEST.finditer(text):
		name, kind, rest = match.group(1), match.group(2), match.group(3)

		if rest and (rest[0].islower() or rest[0].isdigit()):
			continue

		# the setup hook of a package rather than a test, running it alone runs every test there is
		if name == 'TestMain':
			continue

		# only an example may be the bare word, `func Test(` is not run by go
		if not rest and kind != 'Example':
			continue

		end = GO_END.search(text, match.end())
		test = Test(name, match.start(), end.end() if end else len(text))
		tests.append(test)

		if kind == 'Test':
			if masked is None:
				masked = go_masked(text)
			tests.extend(go_subtests(text, masked, test))

	# a table can be declared above the test that goes over it, the icons are still in file order
	return sorted(tests, key=lambda test: test.offset)


# -- go subtests -----------------------------------------------------------------------------------
#
# A subtest is a call of `t.Run(name, ...)`, and go can run one alone when it is told the names on the
# way down to it: `-test.run ^TestParse$/^empty_input$`. The name is only known by reading the file
# when it is written down in it, which is two shapes:
#
#   t.Run("empty input", func(t *testing.T) { ... })          the name is the argument
#
#   for _, tt := range tests { t.Run(tt.name, ...) }          the name is a field of each row of a table,
#                                                             or the key of each when the table is a map
#
# Anything else, a name that is built or a table that is filled in somewhere else, has no icon. The
# test it is in still has one and runs it.

GO_RUN = re.compile(r'\b\w+\.Run\(\s*(?:(")|(\w+)\.(\w+)\s*,|(\w+)\s*,)')
GO_RANGE = re.compile(r'\bfor\s+(\w+)\s*(?:,\s*(\w+)\s*)?:=\s*range\s+')
GO_IDENT = re.compile(r'(\w+)\s*\{')
# what may stand between a table's name and the brace that opens its rows: `[]struct{...}`, `[]*Case`,
# `map[string]pkg.Case`, with the bodies of struct types already taken out
GO_TYPE = re.compile(r'^[\w\s\[\]\*\.]*\[[\w\s\[\]\*\.]*$')
GO_KEY = re.compile(r'"\s*:\s*[\w\.\*&\[\]]*\s*$')
GO_KEYED = re.compile(r'(?<![\w.])\w+\s*:')

GO_CLOSERS = {'{': '}', '(': ')', '[': ']'}


def go_masked(text: str) -> str:
	'''The text with what is inside strings and comments blanked out, every position unchanged

	Braces are what the rows of a table are found by, and one in a string or a comment is not one.
	The quotes of a string are kept so it can still be found, and read out of the real text.
	'''
	out = list(text)
	i, n = 0, len(text)

	def blank(start: int, end: int) -> None:
		for at in range(start, min(end, n)):
			if out[at] != '\n':
				out[at] = ' '

	while i < n:
		char = text[i]

		if text.startswith('//', i):
			end = text.find('\n', i)
			end = n if end < 0 else end
			blank(i, end)
			i = end

		elif text.startswith('/*', i):
			end = text.find('*/', i + 2)
			end = n if end < 0 else end + 2
			blank(i, end)
			i = end

		elif char == '`':
			end = text.find('`', i + 1)
			end = n if end < 0 else end
			blank(i + 1, end)
			i = end + 1

		elif char == '"' or char == "'":
			end = i + 1
			while end < n and text[end] != char and text[end] != '\n':
				end += 2 if text[end] == '\\' else 1
			# a rune is blanked whole, `'{'` and `'"'` would otherwise be read as a brace and a quote
			blank(i + 1 if char == '"' else i, end if char == '"' else end + 1)
			i = end + 1

		else:
			i += 1

	return ''.join(out)


def go_close(masked: str, at: int, limit: int) -> int:
	'''Where the bracket opened at `at` is closed, or -1'''
	depth = 0
	for i in range(at, limit):
		char = masked[i]
		if char in '{([':
			depth += 1
		elif char in '})]':
			depth -= 1
			if depth == 0:
				return i
	return -1


def go_string(text: str, masked: str, at: int, limit: int) -> tuple[str, int] | None:
	'''The string literal that opens at `at` and where it ends, or None when it is not a plain one'''
	quote = masked[at]
	end = masked.find(quote, at + 1, limit)
	if end < 0:
		return None

	if quote == '`':
		return text[at + 1:end], end + 1

	try:
		# the escapes go and python share are the ones a test name has
		value = ast.literal_eval(text[at:end + 1])
	except Exception:
		return None

	return (value, end + 1) if isinstance(value, str) else None


def go_flat(masked: str, start: int, end: int) -> str:
	'''masked[start:end] with everything nested in brackets blanked, what is left is one level'''
	out = list(masked[start:end])
	i = start
	while i < end:
		if masked[i] in '{([':
			close = go_close(masked, i, end)
			if close < 0:
				break
			for at in range(i, close + 1):
				out[at - start] = ' '
			i = close + 1
		else:
			i += 1
	return ''.join(out)


def go_subtest_name(name: str) -> str:
	'''The name go gives a subtest: what was passed to `t.Run` with its spaces made underscores'''
	return ''.join('_' if char.isspace() else char for char in name)


def go_table(masked: str, at: int, limit: int) -> tuple[int, int, str | None] | None:
	'''The rows of the composite literal whose type starts at `at`: its braces, and the first field of a row'''
	kept = ''
	first_field = None
	i = at

	while True:
		brace = masked.find('{', i, limit)
		if brace < 0:
			return None

		kept += masked[i:brace]

		if kept.rstrip().endswith(('struct', 'interface')):
			close = go_close(masked, brace, limit)
			if close < 0:
				return None
			if field := re.match(r'\s*(\w+)', masked[brace + 1:close]):
				first_field = first_field or field.group(1)
			# the body stands in for the type it was, so the next brace is not taken for another body
			kept += ' _'
			i = close + 1
			continue

		if not GO_TYPE.match(kept):
			return None

		close = go_close(masked, brace, limit)
		if close < 0:
			return None

		if first_field is None and (named := re.search(r'(\w+)\s*$', kept)):
			# rows of a named type, which is written down once somewhere in the file
			if declared := re.search(r'\btype\s+' + named.group(1) + r'\s+struct\s*\{\s*(\w+)', masked):
				first_field = declared.group(1)

		return brace, close, first_field


def go_rows(text: str, masked: str, table: tuple[int, int, str | None], field: str | None) -> list[tuple[str, int, int]]:
	'''(name, start, end) of each row of a table: `field` of the row, or its key when `field` is None'''
	open_, close, first_field = table
	rows: list[tuple[str, int, int]] = []
	i = previous = open_ + 1

	while i < close:
		char = masked[i]

		if char == ',':
			previous = i + 1

		if char in '([':
			i = go_close(masked, i, close)
			if i < 0:
				break

		elif char == '{':
			end = go_close(masked, i, close + 1)
			if end < 0:
				break

			name = None

			if field is None:
				# `"key": {` or `"key": Case{`
				before = masked[previous:i]
				if GO_KEY.search(before) and (quote := before.find('"')) >= 0:
					if string := go_string(text, masked, previous + quote, i):
						name = string[0]

			else:
				flat = go_flat(masked, i + 1, end)
				at = None

				if keyed := re.search(r'(?<![\w.])' + re.escape(field) + r'\s*:\s*(?=["`])', flat):
					at = i + 1 + keyed.end()
				elif field == first_field and not GO_KEYED.search(flat) and re.match(r'\s*["`]', flat):
					# `{"name", 1, 2}`: no field is named, so the first value is the first field
					at = i + 1 + len(flat) - len(flat.lstrip())

				if at is not None and (string := go_string(text, masked, at, end)):
					# only a string that is the whole value, `"a" + suffix` is a name that is built
					if re.match(r'\s*(,|$)', flat[string[1] - i - 1:]):
						name = string[0]

			if name:
				rows.append((name, i, end + 1))

			i = end
			previous = end + 1

		i += 1

	return rows


def go_subtests(text: str, masked: str, test: Test) -> list[Test]:
	start, limit = test.offset, test.end

	# every call of Run in the test: where, where its arguments end, and what its name is when the
	# name is the same every time it is called
	calls: list[tuple[int, int, str | None, Any]] = []
	for match in GO_RUN.finditer(masked, start, limit):
		paren = masked.index('(', match.start())
		end = go_close(masked, paren, limit)
		if end < 0:
			continue

		literal = None
		if match.group(1):
			if string := go_string(text, masked, match.end() - 1, end):
				if masked[string[1]:end].lstrip().startswith(','):
					literal = string[0]

		calls.append((match.start(), end, literal, match))

	found: dict[tuple[str, int], Test] = {}

	for at, end, literal, match in calls:
		around = [other for other in calls if other[0] < at < other[1]]

		# inside a subtest whose name is not known there is no way to say which one to go into
		if any(other[2] is None for other in around):
			continue

		path = [test.name, *(go_subtest_name(other[2]) for other in around)]

		if literal is not None:
			rows = [(literal, at, end + 1)]

		elif match.group(1):
			continue

		else:
			rows = go_table_rows(text, masked, test, at, match.group(2) or match.group(4), match.group(3))

		for name, row_start, row_end in rows:
			if not name:
				continue
			subtest = Test('/'.join([*path, go_subtest_name(name)]), row_start, row_end)
			found.setdefault((subtest.name, subtest.offset), subtest)

	return sorted(found.values(), key=lambda subtest: subtest.offset)


def go_table_rows(text: str, masked: str, test: Test, at: int, variable: str, field: str | None) -> list[tuple[str, int, int]]:
	'''The rows `variable` goes over in the loop that the Run at `at` is in

	`field` is the field of a row that is the name, None when the name is the loop's key.
	'''
	loop = None
	for match in GO_RANGE.finditer(masked, test.offset, at):
		key, value = match.group(1), match.group(2)
		if (field is None and key == variable and value) or (field is not None and value == variable):
			loop = match

	if not loop:
		return []

	table = None

	if named := GO_IDENT.match(masked, loop.end()):
		# `range tests {`: the table is a variable, assigned in the test or declared in the file
		declared = None
		pattern = re.compile(r'(?<![\w.])' + named.group(1) + r'\s*:?=\s*')
		for match in pattern.finditer(masked, test.offset, loop.start()):
			declared = match
		declared = declared or re.search(r'^var\s+' + named.group(1) + r'\b[^=\n]*=\s*', masked, re.MULTILINE)
		if declared:
			table = go_table(masked, declared.end(), len(masked))
	else:
		# `range []struct{...}{...} {`: the table is written where it is gone over
		table = go_table(masked, loop.end(), test.end)

	return go_rows(text, masked, table, field) if table else []


def go_quote(name: str) -> str:
	'''A name as a pattern that matches only it, what `regexp.QuoteMeta` does'''
	return re.sub(r'([\\.+*?()|\[\]{}^$])', r'\\\1', name)


def go_label(file: str, name: str) -> str:
	# the package is part of the name: two packages can each have a `TestPlugin`, and a
	# configuration is refused while one of the same name is running
	return f'{name} ({os.path.basename(os.path.dirname(file))})'


def go_configuration(file: str, name: str) -> dict[str, Any]:
	directory = os.path.dirname(file)
	# a subtest is `Test/sub/sub`, and go matches each of those against its own part of the pattern
	pattern = '/'.join(f'^{go_quote(part)}$' for part in name.split('/'))

	if name.startswith('Benchmark'):
		# `-test.run ^$` matches no test, so only the benchmark runs
		args = ['-test.run', '^$', '-test.bench', pattern]
	else:
		args = ['-test.run', pattern]

	return {
		'name': go_label(file, name),
		'type': 'go',
		'request': 'launch',
		'mode': 'test',
		# delve builds the test binary of a package, which is a directory and not the one file
		'program': directory,
		# go runs a test in the directory of its package, relative paths in a test depend on it
		'cwd': directory,
		'args': [*args, '-test.v'],
	}


def go_command(configuration: Any) -> list[str]:
	# delve builds the test binary of the package and runs it like this. The binary gets a name of its
	# own choosing that starts like this one
	run = ['./__debug_bin', *(configuration.get('args') or [])]

	return [shell(configuration.get('cwd') or configuration.get('program'), run)]


# -- python ----------------------------------------------------------------------------------------
#
# What pytest collects, which is also what unittest runs: a function whose name starts with `test`, at
# the top of the file or in a class that is `Test...` or a `TestCase`. Found by the indentation rather
# than by parsing: the file is being typed in and is not always python, and the python that reads it
# here is older than the one it may be written for.

PY_DECLARATION = re.compile(r'(?:(class)|(?:async\s+)?def)\s+(\w+)\s*(?:\(([^)]*)\))?')
PY_ROOTS = ('pytest.ini', 'pyproject.toml', 'tox.ini', 'setup.cfg', 'setup.py', '.git')


def python_find(text: str) -> list[Test]:
	tests: list[Test] = []

	# the classes and functions the line being read is inside of: (indent, name, its functions are tests)
	scopes: list[tuple[int, str, bool]] = []
	# the tests whose body the line being read may still be in: (indent, name, offset)
	unfinished: list[tuple[int, str, int]] = []

	offset = 0
	# where the last line that had code on it ended, which is where a body ends when the next one starts
	code_end = 0

	for line in text.splitlines(keepends=True):
		start = offset
		offset += len(line)

		stripped = line.strip()
		# a bracket that closes what an indented line opened is not the end of the block it is in
		if not stripped or stripped[0] in '#)]}':
			continue

		indent = len(line) - len(line.lstrip())

		while scopes and scopes[-1][0] >= indent:
			scopes.pop()

		for test in [test for test in unfinished if test[0] >= indent]:
			unfinished.remove(test)
			tests.append(Test(test[1], test[2], code_end))

		code_end = start + len(line.rstrip())

		declared = PY_DECLARATION.match(stripped)
		if not declared:
			continue

		name = declared.group(2)
		# a function in a function is not collected, and neither is anything in a class that is not
		collected = all(scope[2] for scope in scopes)
		holds_tests = False

		if declared.group(1):
			holds_tests = collected and (name.startswith('Test') or 'TestCase' in (declared.group(3) or ''))
			is_test = holds_tests
		else:
			is_test = collected and name.startswith('test')

		if is_test:
			unfinished.append((indent, '::'.join([*(scope[1] for scope in scopes), name]), start + indent))

		scopes.append((indent, name, holds_tests))

	tests.extend(Test(test[1], test[2], code_end) for test in unfinished)

	return sorted(tests, key=lambda test: test.offset)


def python_label(file: str, name: str) -> str:
	return f'{name} ({os.path.basename(file)})'


def python_configuration(file: str, name: str) -> dict[str, Any]:
	directory = os.path.dirname(file)

	return {
		'name': python_label(file, name),
		'type': 'python',
		'request': 'launch',
		'module': 'pytest',
		# `-s`: what a test prints is shown as it prints it, and a `breakpoint()` in one can be typed at
		'args': [f'{file}::{name}', '-s'],
		# where pytest is run from in a project: imports of the code under test are found from here,
		# and the adapter looks for a virtual environment from here up
		'cwd': above(directory, has_any(*PY_ROOTS)) or directory,
		# with the rest of the session rather than in a terminal of its own
		'console': 'internal',
	}


def python_command(configuration: Any) -> list[str]:
	python = configuration.get('python') or configuration.get('pythonPath') or 'python'
	command = [python, '-m', configuration.get('module') or 'pytest', *(configuration.get('args') or [])]

	return [shell(configuration.get('cwd'), command)]


# -- java ------------------------------------------------------------------------------------------
#
# The methods junit runs, found by their annotation. A test is run by the build of the project, which
# is the one thing that knows its classpath: maven or gradle is asked to run the one test and to have
# its JVM wait for a debugger, and the configuration is an attach to that JVM. The java adapter is
# what starts the command (`command`) before it attaches.

JAVA_TYPE = re.compile(r'(?<![\w.])(?:class|interface|enum|record)\s+(\w+)[^{;]*\{')
JAVA_TEST = re.compile(r'@(?:[\w.]+\.)?(?:Test|ParameterizedTest|RepeatedTest|TestFactory|TestTemplate)\b')
JAVA_ANNOTATION = re.compile(r'@[\w.]+')
# what stands between the annotations of a method and its parameters: modifiers, a type, and its name
JAVA_METHOD = re.compile(r'[\w\s<>\[\],.?]*?(\w+)\s*')

JAVA_MAVEN = ('pom.xml',)
JAVA_GRADLE = ('build.gradle', 'build.gradle.kts')
# the port a JVM waits for a debugger on when maven or gradle is asked to make it wait
JAVA_DEBUG_PORT = 5005


def java_find(text: str) -> list[Test]:
	masked = c_masked(text, '"\'', ('"""',))
	n = len(masked)

	# every class of the file: (name, where it is declared, where its body ends)
	types: list[tuple[str, int, int]] = []
	for match in JAVA_TYPE.finditer(masked):
		close = go_close(masked, match.end() - 1, n)
		if close >= 0:
			types.append((match.group(1), match.start(), close + 1))

	tests: list[Test] = []
	holders: set[tuple[str, int, int]] = set()

	for match in JAVA_TEST.finditer(masked):
		i = match.end()

		# the arguments of the annotation and the annotations after it
		while True:
			while i < n and masked[i].isspace():
				i += 1

			if i < n and masked[i] == '(':
				close = go_close(masked, i, n)
				if close < 0:
					break
				i = close + 1

			elif annotation := JAVA_ANNOTATION.match(masked, i):
				i = annotation.end()

			else:
				break

		paren = masked.find('(', i)
		declared = JAVA_METHOD.fullmatch(masked[i:paren]) if paren >= 0 else None
		close = go_close(masked, paren, n) if declared else -1
		if not declared or close < 0:
			continue

		# a method that ends where it is declared has no body to run
		body, ends = masked.find('{', close), masked.find(';', close)
		if body < 0 or 0 <= ends < body:
			continue

		end = go_close(masked, body, n)
		if end < 0:
			continue

		inside = [type_ for type_ in types if type_[1] < match.start() and end < type_[2]]
		if not inside:
			continue

		holders.update(inside)
		tests.append(Test('$'.join(type_[0] for type_ in inside) + '#' + declared.group(1), match.start(), end + 1))

	# a class with a test in it is run as the whole of its tests
	for holder in holders:
		outer = [type_ for type_ in types if type_[1] < holder[1] and holder[2] <= type_[2]]
		tests.append(Test('$'.join(type_[0] for type_ in [*outer, holder]), holder[1], holder[2]))

	return sorted(tests, key=lambda test: test.offset)


def java_label(file: str, name: str) -> str:
	return f'{name} ({os.path.basename(file)})'


def java_configuration(file: str, name: str) -> dict[str, Any]:
	directory = os.path.dirname(file)

	# the module the test is in, which is the nearest build file. Maven when there is none at all,
	# what it says about that is clearer than anything that could be said here
	module = above(directory, has_any(*JAVA_MAVEN, *JAVA_GRADLE)) or directory
	type_, _, method = name.partition('#')

	if has_any(*JAVA_GRADLE)(module) and not has_any(*JAVA_MAVEN)(module):
		wrapper = above(module, has_any('gradlew'))
		command = [
			os.path.join(wrapper, 'gradlew') if wrapper else 'gradle',
			'test',
			'--tests', f'{type_}.{method}' if method else type_,
			'--debug-jvm',
		]
	else:
		wrapper = above(module, has_any('mvnw'))
		command = [
			os.path.join(wrapper, 'mvnw') if wrapper else 'mvn',
			'test',
			f'-Dtest={name}',
			# a module the test depends on is built on the way and has no test of this name
			'-Dsurefire.failIfNoSpecifiedTests=false',
			'-Dmaven.surefire.debug',
		]

	return {
		'name': java_label(file, name),
		'type': 'java',
		'request': 'attach',
		'hostName': 'localhost',
		'port': JAVA_DEBUG_PORT,
		'cwd': module,
		'command': command,
	}


def java_command(configuration: Any) -> list[str]:
	return [shell(configuration.get('cwd'), configuration.get('command') or [])]


# -- jest ------------------------------------------------------------------------------------------
#
# `describe`, `it` and `test` calls whose name is written down. Jest knows a test by its name and the
# names of the `describe`s it is in, joined by spaces, and runs the ones that a pattern matches. Here
# they are joined by `JEST_INSIDE` so the name can be taken apart again, and a `describe` ends in
# `JEST_GROUP`: it is run as everything whose name starts with its own.

JEST_FILE = re.compile(r'\.(?:test|spec)\.[cm]?[jt]sx?$|[\\/]__tests__[\\/].*\.[cm]?[jt]sx?$')
JEST_CALL = re.compile(r'(?<![\w.$])(describe|it|test|fdescribe|fit)((?:\.\w+)*)\s*\(\s*')
JEST_EACH = re.compile(r'(?<![\w.$])(?:describe|it|test|fdescribe|fit|xdescribe|xit|xtest)(?:\.\w+)*\.each\b')
# `.skip` and `.todo` are not here: a test that is not run has nothing to debug
JEST_RUNS = {'only', 'concurrent', 'failing'}
JEST_GROUPS = {'describe', 'fdescribe'}
JEST_ESCAPE = re.compile(r'\\(.)', re.DOTALL)
JEST_ESCAPES = {'n': '\n', 't': '\t'}

JEST_INSIDE = ' › '
JEST_GROUP = ' ›'

JEST_ROOTS = ('jest.config.js', 'jest.config.ts', 'jest.config.mjs', 'jest.config.cjs', 'jest.config.mts', 'jest.config.cts', 'jest.config.json', 'package.json')
JEST_BIN = os.path.join('node_modules', 'jest', 'bin', 'jest.js')
# what marks the top of a repository, which is as far as the code a test runs is looked for
JEST_WORKSPACES = ('.git', 'pnpm-workspace.yaml', 'lerna.json', 'nx.json', 'turbo.json')


def jest_string(text: str, masked: str, at: int) -> tuple[str, int] | None:
	'''The string that opens at `at` and where it ends, or None when it is not all written down'''
	quote = masked[at]
	end = masked.find(quote, at + 1)
	if end < 0:
		return None

	raw = text[at + 1:end]
	if ('${' in raw) if quote == '`' else ('\n' in raw):
		return None

	return JEST_ESCAPE.sub(lambda match: JEST_ESCAPES.get(match.group(1), match.group(1)), raw), end + 1


def jest_find(text: str) -> list[Test]:
	masked = c_masked(text, '"\'', ('`',))
	n = len(masked)

	# where the names are not known: under a `describe.each` or a `describe` whose name is built, the
	# name of a test starts with something that is only known when it runs
	unknown: list[tuple[int, int]] = []

	for match in JEST_EACH.finditer(masked):
		i = match.end()

		# the table, as arguments or as a template, and then the call that is given the name
		for _ in range(2):
			while i < n and masked[i].isspace():
				i += 1

			if i < n and masked[i] == '`':
				close = masked.find('`', i + 1)
			elif i < n and masked[i] == '(':
				close = go_close(masked, i, n)
			else:
				break

			if close < 0:
				break
			i = close + 1

		unknown.append((match.start(), i))

	# (start, end, name, is a describe)
	calls: list[tuple[int, int, str, bool]] = []

	for match in JEST_CALL.finditer(masked):
		start = match.start()
		if any(a <= start < b for a, b in unknown):
			continue

		if any(modifier not in JEST_RUNS for modifier in match.group(2).split('.') if modifier):
			continue

		close = go_close(masked, masked.index('(', start), n)
		if close < 0:
			continue

		is_group = match.group(1) in JEST_GROUPS
		string = jest_string(text, masked, match.end()) if match.end() < n and masked[match.end()] in '"\'`' else None

		# only a string that is the whole name, and a name alone is a test that is yet to be written
		if not string or not masked[string[1]:close].lstrip().startswith(','):
			if is_group:
				unknown.append((start, close + 1))
			continue

		calls.append((start, close + 1, string[0], is_group))

	tests: list[Test] = []

	for start, end, name, is_group in calls:
		around = [call[2] for call in calls if call[3] and call[0] < start and end <= call[1]]
		tests.append(Test(JEST_INSIDE.join([*around, name]) + (JEST_GROUP if is_group else ''), start, end))

	return tests


def jest_label(file: str, name: str) -> str:
	return f'{name[:-len(JEST_GROUP)] if name.endswith(JEST_GROUP) else name} ({os.path.basename(file)})'


def jest_pattern(name: str) -> str:
	is_group = name.endswith(JEST_GROUP)
	if is_group:
		name = name[:-len(JEST_GROUP)]

	# everything in a describe has its name and a space in front of its own
	return '^' + go_quote(' '.join(name.split(JEST_INSIDE))) + (' ' if is_group else '$')


def jest_configuration(file: str, name: str) -> dict[str, Any]:
	directory = os.path.dirname(file)

	# jest is run from where its configuration is. In a workspace it is often installed further up
	root = above(directory, has_any(*JEST_ROOTS)) or directory
	installed = above(directory, has_any(JEST_BIN)) or root

	return {
		'name': jest_label(file, name),
		'type': 'node',
		'request': 'launch',
		'program': os.path.join(installed, JEST_BIN),
		# in this process: jest otherwise hands a file to a worker, which is not the process being debugged.
		# `--colors`: it is not writing to a terminal and would drop them, the console draws them
		'args': ['--runInBand', '--colors', '--runTestsByPath', file, '-t', jest_pattern(name)],
		'cwd': root,
		'console': 'internal',
		# jest writes its results to stderr, and without this only what `console.log` prints is shown
		'outputCapture': 'std',
		# Where the source of what runs is looked for: the repository, not what is installed into it
		# or generated in it. Unsaid, the adapter goes after the source map of every script that is
		# loaded, and each one that names a map it was not shipped with is a `Could not read source
		# map` in the middle of the results: typescript itself, the runtime of a generated client
		'resolveSourceMapLocations': [
			os.path.join(above(directory, has_any(*JEST_WORKSPACES)) or installed, '**'),
			'!**/node_modules/**',
			'!**/generated/**',
		],
	}


def jest_command(configuration: Any) -> list[str]:
	command = ['node', configuration.get('program'), *(configuration.get('args') or [])]

	return [shell(configuration.get('cwd'), command)]


LANGUAGES: list[Language] = [
	Language('go', lambda file: file.endswith('_test.go'), go_find, go_configuration, go_label, go_command),
	Language('python', lambda file: bool(re.search(r'(^|[\\/])(test_\w*|\w*_test)\.py$', file)), python_find, python_configuration, python_label, python_command),
	Language('java', lambda file: file.endswith('.java'), java_find, java_configuration, java_label, java_command),
	Language('jest', lambda file: bool(JEST_FILE.search(file)), jest_find, jest_configuration, jest_label, jest_command, stderr_is_output=True),
]


def language_for(file: str | None) -> Language | None:
	if not file:
		return None

	for language in LANGUAGES:
		if language.matches(file):
			return language

	return None


def test_at(tests: list[Test], offset: int) -> Test | None:
	'''The test a position in the file is inside of, from the start of its declaration to the end of its body'''
	found = None

	# a subtest is inside its test and listed after it, so the last that holds the position is the
	# innermost
	for test in tests:
		if test.offset <= offset <= test.end and (not found or test.end - test.offset <= found.end - found.offset):
			found = test

	return found


def merged(configuration: dict[str, Any], *overrides: Any) -> dict[str, Any]:
	'''A generated configuration with the users own values laid over it, later ones winning

	`args` are added after the generated ones rather than replacing them, replacing would drop the
	argument that selects the test. Objects such as `env` are merged key by key. Anything else is
	replaced, which is how a `cwd` or `buildFlags` is set.
	'''
	result = dict(configuration)

	for override in overrides:
		if not isinstance(override, dict):
			continue

		for key, value in override.items():
			current = result.get(key)

			if key == 'args' and isinstance(value, list) and isinstance(current, list):
				result[key] = [*current, *value]
			elif isinstance(value, dict) and isinstance(current, dict):
				result[key] = {**current, **value}
			else:
				result[key] = value

	return result


def configuration_for(language: Language, file: str, name: str, *overrides: Any) -> dict[str, Any]:
	'''The configuration that debugs one test, `overrides` being `{language key: {...}}` objects'''
	generated = language.configuration(file, name)
	configuration = merged(generated, *((override or {}).get(language.key) for override in overrides if isinstance(override, dict)))

	# what is running is found by name, the icon of a test turns into stop by it, so it stays ours
	configuration['name'] = language.label(file, name)
	return configuration
