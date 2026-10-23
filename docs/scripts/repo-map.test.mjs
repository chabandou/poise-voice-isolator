// node --test scripts/
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { cOutline, KIND, pythonOutline, tokenizeC, tokenizePython, wrapSignature } from './repo-map.mjs'

const kinds = (pairs) => Object.fromEntries(pairs.filter(([, k]) => k).map(([t, k]) => [t.trim(), k]))

test('python: a def colours its name, parameters, annotations and defaults by role', () => {
	const k = kinds(tokenizePython('def wait(self, name: str, timeout: Optional[int] = None) -> bool: ...'))
	assert.equal(k.def, KIND.kw)
	assert.equal(k.wait, KIND.fn)
	assert.equal(k.self, KIND.self)
	assert.equal(k.name, KIND.param)
	assert.equal(k.timeout, KIND.param)
	assert.equal(k.str, KIND.type)
	assert.equal(k.int, KIND.type) // inside Optional[...], not a parameter
	assert.equal(k.None, KIND.kw)
	assert.equal(k.bool, KIND.type)
})

test('python: class bases are types, calls are functions', () => {
	assert.equal(kinds(tokenizePython('class GTCRNEngine(DenoiseEngine):')).DenoiseEngine, KIND.type)
	assert.equal(kinds(tokenizePython('    run_gui()')).run_gui, KIND.fn)
})

test('python outline: public API with docstrings, private classes left out', () => {
	const src = [
		'class _Pipe:',
		'    def send(self, msg):',
		'        pass',
		'class Host:',
		'    """The handle."""',
		'    def start(self,',
		'              config):',
		'        pass',
		'    def _hidden(self):',
		'        pass',
		'def helper(x):',
		'    """Help."""',
	].join('\n')
	assert.deepEqual(pythonOutline(src), [
		'class Host:',
		'    """The handle."""',
		'    def start(self, config): ...',
		'def helper(x): ...',
		'    """Help."""',
	])
})

test('c: types, the function name and each parameter name', () => {
	const k = kinds(tokenizeC('int64_t poise_core_wait_frame(poise_core *c, float *dst, int timeout_ms)'))
	assert.equal(k.int64_t, KIND.type)
	assert.equal(k.poise_core_wait_frame, KIND.fn)
	assert.equal(k.poise_core, KIND.type)
	assert.equal(k.c, KIND.param)
	assert.equal(k.dst, KIND.param)
	assert.equal(k.timeout_ms, KIND.param)
})

test('c outline: exported definitions before static ones', () => {
	const src = 'static int helper_(int a)\n{\n}\nvoid poise_a(int x)\n{\n}\nint poise_b(float y,\n            int z)\n{\n}\n'
	assert.deepEqual(cOutline(src, false), ['void poise_a(int x)', 'int poise_b(float y, int z)'])
})

test('python: a long def wraps one parameter per line, brackets kept whole', () => {
	const text = (lines) => lines.map((line) => line.map(([t]) => t).join(''))
	assert.deepEqual(text(wrapSignature('    def f(self, on_event: Optional[Callable[[dict], None]] = None, n: int = 3) -> bool: ...')), [
		'    def f(',
		'        self,',
		'        on_event: Optional[Callable[[dict], None]] = None,',
		'        n: int = 3',
		'    ) -> bool: ...',
	])
})

test('readme image: tree rows with guides, and a folded folder as one line of names', async () => {
	const { treeRows } = await import('./render-file-tree.mjs')
	const rows = treeRows([
		{ name: 'gui/', path: 'gui/', children: [
			{ name: 'app.py', path: 'gui/app.py', stage: 1 },
			{ name: 'widgets/', path: 'gui/widgets/', folded: true, children: [
				{ name: 'dial.py', path: 'gui/widgets/dial.py', stage: 1 },
				{ name: 'sky.py', path: 'gui/widgets/sky.py', stage: 1 },
			] },
		] },
	])
	assert.deepEqual(rows.map(({ pre, name, stage }) => pre + name + (stage ? ` ${stage}` : '')), [
		'gui/',
		'├─ app.py 1',
		'└─ widgets/  2 files 1',
		'   dial · sky',
	])
})
