// Loaded into jest before anything else (`node --require`) when a test is run from the debugger.
//
// A breakpoint in a .ts file is found through the source map of the javascript that was made
// from it, and the debugger only knows of a map the javascript itself points to. @swc/jest
// writes the map into the code when a project says nothing about source maps, and beside it,
// in jest's cache, when the project says `"sourceMaps": true`: the code that runs then names no
// map, and no breakpoint in the file it was made from is ever reached.
//
// So whatever the project asked swc for, a test under the debugger gets the map in the code.
// Only that: the code swc makes is the same, and a project that does not use swc is not touched.

'use strict';

const Module = require('module');

const load = Module._load;
const patched = new WeakMap();

function withInlineSourceMaps(real) {
	const copy = {};

	const inline = (name) =>
		function (source, options) {
			return real[name].call(real, source, Object.assign({}, options, { sourceMaps: 'inline' }));
		};

	for (const key of Reflect.ownKeys(real)) {
		if ((key === 'transformSync' || key === 'transform') && typeof real[key] === 'function') {
			Object.defineProperty(copy, key, { value: inline(key), enumerable: true, writable: true, configurable: true });
		} else {
			Object.defineProperty(copy, key, Object.getOwnPropertyDescriptor(real, key));
		}
	}

	return copy;
}

Module._load = function (request) {
	const loaded = load.apply(this, arguments);

	if (request !== '@swc/core' || loaded === null || typeof loaded !== 'object') {
		return loaded;
	}

	if (!patched.has(loaded)) {
		patched.set(loaded, withInlineSourceMaps(loaded));
	}
	return patched.get(loaded);
};
