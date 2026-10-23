// Build-time half of the site's repo map (src/components/RepoMap.tsx).
// src/repo-map.json lists the files and what each does; this reads each
// file and keeps a short outline of it (its classes and functions, or its
// first lines), split into tokens the page colours like an editor would.
// vite.config.ts serves the result as virtual:repo-map-snippets, a chunk
// the page loads on the first click.
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'

const MAX_LINES = 16
const ABOUT_CHARS = 420

/** Token kinds, as the page's CSS classes (index.css .tok-*). */
export const KIND = { kw: 'k', fn: 'f', type: 't', param: 'p', self: 'x', str: 's', com: 'c', num: 'n', deco: 'd', konst: 'v' }

const PY_KW = new Set(['def', 'class', 'async', 'await', 'return', 'lambda', 'None', 'True', 'False', 'and', 'or', 'not', 'in', 'is', 'yield', 'import', 'from', 'as', 'if', 'else', 'for', 'while', 'with', 'try', 'except', 'raise', 'pass'])
const PY_TYPES = new Set(['int', 'float', 'str', 'bool', 'bytes', 'list', 'dict', 'tuple', 'set', 'object', 'type'])
const C_KW = new Set(['static', 'inline', 'const', 'return', 'if', 'else', 'struct', 'enum', 'typedef', 'unsigned', 'signed', 'extern', 'volatile', 'sizeof', 'for', 'while', 'switch', 'case'])
const C_TYPES = new Set(['void', 'int', 'char', 'float', 'double', 'long', 'short', 'bool'])

const TOKEN = /("""[^]*?"""|'''[^]*?'''|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|#.*$|\/\/.*$|\/\*.*?\*\/|\b\d[\d_]*(?:\.\d+)?(?:[eE][-+]?\d+)?[fFuUlL]*\b|[A-Za-z_]\w*|->|\.\.\.|\*\*|\s+|.)/g
const isIdent = (t) => /^[A-Za-z_]\w*$/.test(t)
const isConst = (t) => /^[A-Z][A-Z0-9_]+$/.test(t)

/** Merges neighbours of the same kind so a line stays a short array. */
const pack = (pairs) => {
	const out = []
	for (const [text, kind] of pairs) {
		const last = out[out.length - 1]
		if (last && last[1] === kind) last[0] += text
		else out.push([text, kind])
	}
	return out
}

/** One line of Python, coloured by role: a def's name, its parameters, their annotations and defaults. */
export const tokenizePython = (line) => pack(pythonTokens(line))

function pythonTokens(line) {
	const tokens = line.match(TOKEN) ?? []
	const out = []
	let after = '' // the keyword before this name: def, class or @
	let paren = 0
	let bracket = 0
	let inDef = false
	let inClassHead = false
	let mode = 'name' // inside a def's parentheses: name, ann(otation) or val(ue)
	let arrow = false
	for (const [i, t] of tokens.entries()) {
		let kind = ''
		if (/^\s+$/.test(t)) {
			out.push([t, ''])
			continue
		}
		const call = tokens[i + 1] === '('
		if (/^("""|'''|"|')/.test(t)) kind = KIND.str
		else if (t.startsWith('#')) kind = KIND.com
		else if (/^\d/.test(t)) kind = KIND.num
		else if (isIdent(t)) {
			if (after === 'def') kind = KIND.fn
			else if (after === 'class') kind = KIND.type
			else if (after === '@') kind = KIND.deco
			else if (PY_KW.has(t)) kind = KIND.kw
			else if (inDef && paren === 1 && !bracket && mode === 'name') kind = t === 'self' || t === 'cls' ? KIND.self : KIND.param
			else if ((inDef && paren >= 1 && mode === 'ann') || arrow) kind = KIND.type
			else if (inClassHead && paren >= 1) kind = KIND.type
			else if (isConst(t)) kind = KIND.konst
			else if (PY_TYPES.has(t) || /^[A-Z]/.test(t)) kind = KIND.type
			else if (call) kind = KIND.fn
			if (t === 'def') inDef = true
			if (t === 'class') inClassHead = true
			after = t === 'def' || t === 'class' ? t : ''
			out.push([t, kind])
			continue
		} else if (t === '@' && !out.some(([text]) => text.trim())) {
			after = '@'
			kind = KIND.deco
			out.push([t, kind])
			continue
		} else if (t === '(') {
			paren++
		} else if (t === ')') {
			paren--
		} else if (t === '[') {
			bracket++
		} else if (t === ']') {
			bracket--
		} else if (paren === 1 && !bracket && inDef && t === ',') {
			mode = 'name'
		} else if (paren === 1 && !bracket && inDef && t === ':') {
			mode = 'ann'
		} else if (paren === 1 && !bracket && inDef && t === '=') {
			mode = 'val'
		} else if (t === '->') {
			arrow = true
		} else if (!paren && t === ':') {
			arrow = false
		}
		after = ''
		out.push([t, kind])
	}
	return out
}

const WRAP_AT = 88

/** A def too long for one line, one parameter per line, as an editor's hover shows it. */
export function wrapSignature(line) {
	const indent = /^\s*/.exec(line)[0]
	const pad = `${indent}    `
	const lines = [[]]
	let paren = 0
	let bracket = 0
	for (const [t, kind] of pythonTokens(line)) {
		const current = lines[lines.length - 1]
		if (t === ')' && --paren === 0) lines.push([[indent, '']])
		else if (/^\s+$/.test(t) && current.length === 1 && current[0][0] === pad) continue
		if (t === '[') bracket++
		if (t === ']') bracket--
		lines[lines.length - 1].push([t, kind])
		if (t === '(' && ++paren === 1) lines.push([[pad, '']])
		else if (t === ',' && paren === 1 && !bracket) lines.push([[pad, '']])
	}
	return lines.map(pack)
}

/** One line of C: types, the function's name, and the last name in each parameter. */
export function tokenizeC(line) {
	const tokens = line.match(TOKEN) ?? []
	const kinds = tokens.map((t) => {
		if (/^\s+$/.test(t)) return ''
		if (/^"/.test(t)) return KIND.str
		if (t.startsWith('//') || t.startsWith('/*')) return KIND.com
		if (/^\d/.test(t)) return KIND.num
		if (!isIdent(t)) return ''
		if (C_KW.has(t)) return KIND.kw
		if (C_TYPES.has(t) || /_t$/.test(t)) return KIND.type
		if (isConst(t)) return KIND.konst
		return '?'
	})
	// Undecided names: a call or definition if "(" follows, else a parameter
	// if it is the last name before "," or ")", else a type.
	let depth = 0
	for (let i = 0; i < tokens.length; i++) {
		const t = tokens[i]
		if (t === '(') depth++
		else if (t === ')') depth--
		if (kinds[i] !== '?') continue
		let j = i + 1
		while (j < tokens.length && /^\s+$/.test(tokens[j])) j++
		const next = tokens[j]
		if (next === '(') kinds[i] = KIND.fn
		else if (depth >= 1 && (next === ',' || next === ')' || next === '[')) kinds[i] = KIND.param
		else kinds[i] = KIND.type
	}
	return pack(tokens.map((t, i) => [t, kinds[i]]))
}

/** Anything else (shell, YAML, TOML, Inno Setup, Textual CSS): comments, strings, numbers, keys. */
export function tokenizePlain(line) {
	const comment = /^(\s*)([#;].*)$/.exec(line)
	if (comment) return pack([[comment[1], ''], [comment[2], KIND.com]])
	const key = /^(\s*-?\s*)([\w.$-]+)(\s*[:=])(.*)$/.exec(line)
	const rest = key ? key[4] : line
	const head = key ? [[key[1], ''], [key[2], KIND.fn], [key[3], '']] : []
	const body = (rest.match(TOKEN) ?? []).map((t) => [
		t,
		/^("|')/.test(t) ? KIND.str : /^\d/.test(t) ? KIND.num : /^(true|false|null)$/.test(t) ? KIND.kw : '',
	])
	return pack([...head, ...body])
}

const squash = (s) => s.replace(/\s+/g, ' ').trim()
const clip = (s) => (s.length <= ABOUT_CHARS ? s : s.slice(0, s.lastIndexOf(' ', ABOUT_CHARS)) + '…')
const balance = (s) => (s.match(/[([{]/g) ?? []).length - (s.match(/[)\]}]/g) ?? []).length

/** The module docstring's second paragraph (its first is the title). */
function pythonAbout(text) {
	const doc = /^\s*(?:#.*\n\s*)*(?:"""|''')([^]*?)(?:"""|''')/.exec(text)
	const paragraph = doc?.[1].split(/\n\s*\n/)[1]
	return paragraph ? clip(squash(paragraph)) : ''
}

/** Top-level classes and functions with their public methods, each with its docstring's first line. */
export function pythonOutline(text) {
	const lines = text.split('\n')
	const out = []
	let inClass = false
	let methods = 0
	for (let i = 0; i < lines.length && out.length < MAX_LINES; i++) {
		const line = lines[i]
		if (/^[^\s#@)\]}'"]/.test(line)) inClass = /^class /.test(line)
		const m = /^( {4})?(?:async )?(def|class) (\w+)/.exec(line)
		if (!m) continue
		const indent = m[1] ?? ''
		if (indent && (!inClass || m[2] === 'class')) continue
		if (m[3].startsWith('_') && m[3] !== '__init__') {
			// A private class's methods are private too.
			if (!indent) inClass = false
			continue
		}
		if (indent && ++methods > 4) continue
		if (!indent) methods = 0
		let sig = line.trim()
		while ((balance(sig) > 0 || !/:\s*(#.*)?$/.test(sig)) && i + 1 < lines.length) sig += ' ' + lines[++i].trim()
		sig = squash(sig).replace(/\(\s/g, '(').replace(/,?\s\)/g, ')').replace(/\s*#.*$/, '')
		out.push(indent + sig + (m[2] === 'def' ? ' ...' : ''))
		const doc = /^\s*(?:"""|''')\s*(.*?)\s*(?:"""|''')?\s*$/.exec(lines[i + 1] ?? '')
		if (doc?.[1] && out.length < MAX_LINES) out.push(`${indent}    """${doc[1].replace(/"""$/, '')}"""`)
	}
	return out
}

/** The first lines of code after the module docstring and imports. */
function firstLines(text) {
	const body = text.replace(/^\s*(?:#!.*\n)?\s*(?:"""[^]*?"""|'''[^]*?''')?/, '')
	return body
		.split('\n')
		.filter((line) => line.trim() && !/^\s*(#|import |from )/.test(line))
		.slice(0, 10)
}

/** C: definitions (.c) or prototypes (.h), the exported ones first. */
export function cOutline(text, header) {
	const lines = text.split('\n')
	const found = []
	for (let i = 0; i < lines.length; i++) {
		if (!/^[A-Za-z_][\w\s*]*\b\w+\s*\(/.test(lines[i]) || /^(typedef|return|if|for|while|switch|#)/.test(lines[i])) continue
		let sig = lines[i]
		while (balance(sig) > 0 && i + 1 < lines.length) sig += ' ' + lines[++i].trim()
		const isProto = /;\s*$/.test(sig)
		if (isProto !== header) continue
		found.push(squash(sig.replace(/\s*\{\s*$/, '').replace(/;\s*$/, header ? ';' : '')))
	}
	const exported = found.filter((s) => !/^static\b/.test(s))
	return (exported.length >= 2 ? exported : [...exported, ...found.filter((s) => /^static\b/.test(s))]).slice(0, 8)
}

function cAbout(text) {
	const comment = /^\s*\/\*([^]*?)\*\//.exec(text)
	if (!comment) return ''
	const paragraph = comment[1].split('\n').map((l) => l.replace(/^\s*\*\s?/, '')).join('\n').split(/\n\s*\n/)[0]
	return clip(squash(paragraph))
}

const TEXT = /\.(sh|spec|iss|ya?ml|tcss|toml|txt|md|csv|cfg)$|(^|\/)(PKGBUILD|Makefile)$/

/** The snippet for one file, or null for folders and binaries. */
export function snippetFor(path, raw) {
	const text = raw.replace(/\r\n?/g, '\n')
	if (path.endsWith('.py')) {
		const outline = pythonOutline(text)
		const lines = outline.length ? outline : firstLines(text)
		const long = (line) => line.length > WRAP_AT && /^\s*(async )?def /.test(line)
		return { about: pythonAbout(text), lines: lines.flatMap((line) => (long(line) ? wrapSignature(line) : [tokenizePython(line)])) }
	}
	if (/\.[ch]$/.test(path)) {
		return { about: cAbout(text), lines: cOutline(text, path.endsWith('.h')).map(tokenizeC) }
	}
	if (TEXT.test(path)) {
		return { about: '', lines: text.split('\n').filter((l) => l.trim()).slice(0, 12).map(tokenizePlain) }
	}
	return null
}

function* walk(nodes) {
	for (const node of nodes) {
		yield node
		if (node.children) yield* walk(node.children)
	}
}

// Source files the map should list; anything here it misses is reported.
const WATCHED = ['stream_denoiser', 'native', 'installer']
const SOURCE = /\.(py|c|h)$/

function* sourceFiles(root, dir) {
	for (const entry of readdirSync(join(root, dir))) {
		const rel = `${dir}/${entry}`
		if (entry === '__pycache__' || entry === 'assets' || entry === '__init__.py') continue
		if (statSync(join(root, rel)).isDirectory()) yield* sourceFiles(root, rel)
		else if (SOURCE.test(entry)) yield rel
	}
}

/** Reads every mapped file under `root`; warns about files the map lists that are gone, and source files it does not list. */
export function buildRepoMap(root, map) {
	const snippets = {}
	const warnings = []
	const listed = new Set()
	for (const section of map.sections) {
		for (const node of walk(section.nodes)) {
			if (!node.path || node.path.endsWith('/')) continue
			listed.add(node.path)
			const file = join(root, node.path)
			if (!existsSync(file)) {
				warnings.push(`listed but missing: ${node.path}`)
				continue
			}
			const snippet = snippetFor(node.path, readFileSync(file, 'utf8'))
			if (snippet && (snippet.lines.length || snippet.about)) snippets[node.path] = snippet
		}
	}
	for (const dir of WATCHED) {
		if (!existsSync(join(root, dir))) continue
		for (const file of sourceFiles(root, dir)) {
			// Entries like "core/poise_core.c · .h" stand for their header too.
			const twin = file.replace(/\.h$/, '.c')
			if (!listed.has(file) && !listed.has(twin)) warnings.push(`not on the map: ${file}`)
		}
	}
	return { snippets, warnings }
}
