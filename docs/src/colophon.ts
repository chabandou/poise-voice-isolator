// Writes تَمَّ بِحَمْدِ اللَّهِ ("it is finished, with praise to God", the line
// scribes closed a manuscript with) the way a pen would, in gold.
//
// The letterforms come from the Aref Ruqaa font, so joins and the الله
// ligature are right. To animate them, the text is rasterised once and
// thinned to its centre lines (Zhang–Suen), with a distance transform for
// the stroke width along them. A pen then follows those lines from right to
// left, uncovering the gilded text under a mask of round stamps, with each
// letter group's dots and vowel marks right after it. A letter group's own
// shape settles in when the pen leaves it, so no edge is left unpainted.

const DW = 1000;
const DH = 330; // the text plus room for a star on each side
const RS = 0.9; // centre-line raster: px per design unit
const SPEED = 560; // design units per second at full pen speed
const SILVER = '#c9ced6';
const FAMILY = 'Aref Ruqaa';
const WEIGHT = 700;
export const COLOPHON_TEXT = 'تَمَّ بِحَمْدِ اللَّهِ';

type Pt = { x: number; y: number; r: number; s: number; vf: number };
type Comp = { mask: HTMLCanvasElement };
type Item = { comp: Comp; pts: Pt[]; newComp: boolean; lastOfComp: boolean };
type Layout = { font: string; x: number; y: number; top: number; bot: number; left: number; right: number };
type Rgb = [number, number, number];

const clamp = (v: number, a: number, b: number) => Math.max(a, Math.min(b, v));
const smooth = (t: number) => t * t * (3 - 2 * t);

const parseColor = (value: string): Rgb => {
	const probe = document.createElement('canvas').getContext('2d')!;
	probe.fillStyle = value.trim() || '#e8c468';
	const hex = probe.fillStyle; // normalised to #rrggbb
	const n = parseInt(hex.slice(1), 16);
	return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
};
const css = (c: Rgb, alpha = 1) => `rgba(${c[0]},${c[1]},${c[2]},${alpha})`;

const canvas2d = (w = 1, h = 1) => {
	const c = document.createElement('canvas');
	c.width = w;
	c.height = h;
	return [c, c.getContext('2d')!] as const;
};

function layout(): Layout {
	const [, c] = canvas2d();
	c.font = `${WEIGHT} 100px "${FAMILY}"`;
	c.direction = 'rtl';
	c.textAlign = 'center';
	const m = c.measureText(COLOPHON_TEXT);
	const L = m.actualBoundingBoxLeft, R = m.actualBoundingBoxRight, A = m.actualBoundingBoxAscent, D = m.actualBoundingBoxDescent;
	const k = Math.min(690 / (L + R), 310 / (A + D));
	const cy = DH / 2;
	return {
		font: `${WEIGHT} ${100 * k}px "${FAMILY}", serif`,
		x: DW / 2 - ((R - L) / 2) * k,
		y: cy + ((A - D) / 2) * k,
		top: cy - ((A + D) / 2) * k,
		bot: cy + ((A + D) / 2) * k,
		left: DW / 2 - ((L + R) / 2) * k,
		right: DW / 2 + ((L + R) / 2) * k,
	};
}

function drawText(c: CanvasRenderingContext2D, L: Layout, fill: string | CanvasGradient) {
	c.font = L.font;
	c.direction = 'rtl';
	c.textAlign = 'center';
	c.textBaseline = 'alphabetic';
	c.fillStyle = fill;
	c.fillText(COLOPHON_TEXT, L.x, L.y);
}

/** Centre lines of the text as pen paths, in writing order. */
function analyse(L: Layout): Item[] {
	const W = Math.round(DW * RS), H = Math.round(DH * RS), N = W * H;
	const [, c] = canvas2d(W, H);
	c.setTransform(RS, 0, 0, RS, 0, 0);
	drawText(c, L, '#000');
	const alpha = c.getImageData(0, 0, W, H).data;
	const mask = new Uint8Array(N);
	for (let i = 0; i < N; i++) mask[i] = alpha[i * 4 + 3] > 110 ? 1 : 0;

	// Connected components (8-way): letter groups, dots and vowel marks.
	const lab = new Int32Array(N).fill(-1);
	const comps: { id: number; area: number; x0: number; x1: number; y0: number; y1: number; px: number[] }[] = [];
	for (let i = 0; i < N; i++) {
		if (!mask[i] || lab[i] >= 0) continue;
		const cp = { id: comps.length, area: 0, x0: W, x1: 0, y0: H, y1: 0, px: [] as number[] };
		const q = [i];
		lab[i] = cp.id;
		while (q.length) {
			const p = q.pop()!;
			const x = p % W, y = Math.floor(p / W);
			cp.area++;
			cp.px.push(p);
			cp.x0 = Math.min(cp.x0, x);
			cp.x1 = Math.max(cp.x1, x);
			cp.y0 = Math.min(cp.y0, y);
			cp.y1 = Math.max(cp.y1, y);
			for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) {
				const n = p + dy * W + dx;
				if (n >= 0 && n < N && mask[n] && lab[n] < 0) { lab[n] = cp.id; q.push(n); }
			}
		}
		comps.push(cp);
	}

	// Chamfer distance to the nearest background pixel: half the stroke width.
	const dt = new Float32Array(N);
	for (let i = 0; i < N; i++) dt[i] = mask[i] ? 1e9 : 0;
	for (let y = 1; y < H - 1; y++) for (let x = 1; x < W - 1; x++) {
		const i = y * W + x;
		if (mask[i]) dt[i] = Math.min(dt[i], dt[i - 1] + 1, dt[i - W] + 1, dt[i - W - 1] + 1.4142, dt[i - W + 1] + 1.4142);
	}
	for (let y = H - 2; y > 0; y--) for (let x = W - 2; x > 0; x--) {
		const i = y * W + x;
		if (mask[i]) dt[i] = Math.min(dt[i], dt[i + 1] + 1, dt[i + W] + 1, dt[i + W + 1] + 1.4142, dt[i + W - 1] + 1.4142);
	}

	// Zhang–Suen thinning.
	const sk = mask.slice();
	const del: number[] = [];
	for (let changed = true; changed;) {
		changed = false;
		for (let pass = 0; pass < 2; pass++) {
			del.length = 0;
			for (let y = 1; y < H - 1; y++) for (let x = 1; x < W - 1; x++) {
				const i = y * W + x;
				if (!sk[i]) continue;
				const p2 = sk[i - W], p3 = sk[i - W + 1], p4 = sk[i + 1], p5 = sk[i + W + 1];
				const p6 = sk[i + W], p7 = sk[i + W - 1], p8 = sk[i - 1], p9 = sk[i - W - 1];
				const B = p2 + p3 + p4 + p5 + p6 + p7 + p8 + p9;
				if (B < 2 || B > 6) continue;
				const ring = [p2, p3, p4, p5, p6, p7, p8, p9, p2];
				let A = 0;
				for (let k = 0; k < 8; k++) if (!ring[k] && ring[k + 1]) A++;
				if (A !== 1) continue;
				if (pass === 0 ? (p2 && p4 && p6) || (p4 && p6 && p8) : (p2 && p4 && p8) || (p2 && p6 && p8)) continue;
				del.push(i);
			}
			for (const i of del) sk[i] = 0;
			if (del.length) changed = true;
		}
	}

	const NB = [-W - 1, -W, -W + 1, -1, 1, W - 1, W, W + 1];
	const nbrs = (i: number, keep: (n: number) => boolean) => NB.map((o) => i + o).filter((n) => sk[n] && keep(n));

	// Prune the short spurs thinning leaves at blunt terminals.
	for (let round = 0; round < 2; round++) for (let i = 0; i < N; i++) {
		if (!sk[i] || nbrs(i, () => true).length !== 1) continue;
		const path = [i];
		let prev = -1, cur = i;
		for (;;) {
			const next = nbrs(cur, (n) => n !== prev && !path.includes(n));
			if (next.length !== 1) break;
			if (nbrs(next[0], () => true).length >= 3) {
				if (path.length < Math.max(4, dt[next[0]] * 0.9)) path.forEach((p) => (sk[p] = 0));
				break;
			}
			prev = cur;
			cur = next[0];
			path.push(cur);
			if (path.length > 40) break;
		}
	}

	const seen = new Uint8Array(N);
	const toPt = (i: number): Pt => ({ x: (i % W) / RS, y: Math.floor(i / W) / RS, r: (dt[i] / RS) * 1.28 + 0.9, s: 0, vf: 1 });
	const angle = (a: number, b: number) => Math.atan2(Math.floor(b / W) - Math.floor(a / W), (b % W) - (a % W));

	// Walk a centre line, preferring the straightest continuation; forks are
	// returned so their branches are drawn next.
	const walk = (from: number, cid: number) => {
		const line = [from];
		const forks: number[] = [];
		seen[from] = 1;
		let cur = from;
		let dir: number | null = null;
		for (;;) {
			const cand = nbrs(cur, (n) => !seen[n] && lab[n] === cid);
			if (!cand.length) break;
			if (cand.length > 1) forks.push(cur);
			let best = cand[0];
			if (dir !== null) {
				let bd = 9;
				for (const n of cand) {
					const d = Math.abs(Math.atan2(Math.sin(angle(cur, n) - dir), Math.cos(angle(cur, n) - dir)));
					if (d < bd) { bd = d; best = n; }
				}
			}
			const nd = angle(cur, best);
			dir = dir === null ? nd : Math.atan2(Math.sin(dir) * 0.6 + Math.sin(nd) * 0.4, Math.cos(dir) * 0.6 + Math.cos(nd) * 0.4);
			seen[best] = 1;
			line.push(best);
			// Corner pixels of a staircase step would otherwise become stubs.
			for (const n of cand) if (n !== best && (Math.abs(n - best) === 1 || Math.abs(n - best) === W)) seen[n] = 1;
			cur = best;
		}
		return { line, forks };
	};

	const maxArea = Math.max(...comps.map((cp) => cp.area));
	const textHeight = (L.bot - L.top) * RS;
	// Dots and vowel marks: small and short (an alif is small but tall).
	const isMark = (cp: (typeof comps)[number]) => cp.area < maxArea * 0.16 && cp.y1 - cp.y0 < textHeight * 0.3;
	const traced = comps.map((cp) => {
		const skel = cp.px.filter((i) => sk[i]);
		const paths: Pt[][] = [];
		if (!skel.length) {
			let best = cp.px[0];
			for (const i of cp.px) if (dt[i] > dt[best]) best = i;
			paths.push([toPt(best)]);
		} else {
			const ends = skel.filter((i) => nbrs(i, (n) => lab[n] === cp.id).length === 1);
			const rightmost = (arr: number[]) => arr.reduce((b, i) => ((i % W) > (b % W) ? i : b));
			const stack = [rightmost(ends.length ? ends : skel)];
			let first = true;
			while (stack.length || skel.some((i) => !seen[i])) {
				const from = stack.pop() ?? rightmost(skel.filter((i) => !seen[i]));
				if (!first && seen[from] && !nbrs(from, (n) => !seen[n] && lab[n] === cp.id).length) continue;
				first = false;
				const { line, forks } = walk(from, cp.id);
				// Stubs are covered anyway when the component settles.
				if (line.length > 10 || paths.length === 0) paths.push(line.map(toPt));
				stack.push(...forks);
			}
		}
		// The component's own shape, slightly dilated, to settle its edges.
		const [m, mc] = canvas2d(W, H);
		const img = mc.createImageData(W, H);
		for (const i of cp.px) for (const o of [0, ...NB]) img.data[(i + o) * 4 + 3] = 255;
		mc.putImageData(img, 0, 0);
		return { comp: { mask: m }, paths, small: isMark(cp), x0: cp.x0, x1: cp.x1, cx: (cp.x0 + cp.x1) / 2 };
	});

	// Letter groups right to left, each followed by its dots and marks.
	const mains = traced.filter((t) => !t.small).sort((a, b) => b.x1 - a.x1);
	const extras = new Map(mains.map((m) => [m, [] as typeof traced]));
	for (const s of traced.filter((t) => t.small)) {
		let host = mains[0], bd = Infinity;
		for (const m of mains) {
			const d = s.cx >= m.x0 && s.cx <= m.x1 ? Math.abs(s.cx - m.cx) * 0.2 : Math.min(Math.abs(s.cx - m.x0), Math.abs(s.cx - m.x1)) + 50;
			if (d < bd) { bd = d; host = m; }
		}
		extras.get(host)!.push(s);
	}
	const order = mains.flatMap((m) => [m, ...extras.get(m)!.sort((a, b) => b.cx - a.cx)]);

	const items: Item[] = [];
	for (const t of order) t.paths.forEach((p, pi) => {
		let s = 0;
		p.forEach((q, k) => { if (k) s += Math.hypot(q.x - p[k - 1].x, q.y - p[k - 1].y); q.s = s; });
		// Slower through tight curves and as the pen sets down.
		p.forEach((q, k) => {
			const a = p[Math.max(0, k - 5)], b = p[Math.min(p.length - 1, k + 5)];
			const c0 = p[Math.max(0, k - 10)], c1 = p[Math.min(p.length - 1, k + 10)];
			let d = Math.atan2(c1.y - b.y, c1.x - b.x) - Math.atan2(a.y - c0.y, a.x - c0.x);
			d = Math.abs(Math.atan2(Math.sin(d), Math.cos(d)));
			q.vf = clamp(1 / (1 + d * 1.6), 0.35, 1) * (0.45 + 0.55 * clamp(q.s / 14, 0, 1));
		});
		items.push({ comp: t.comp, pts: p, newComp: pi === 0, lastOfComp: pi === t.paths.length - 1 });
	});
	return items;
}

export type Colophon = {
	/** Writes the line from a blank page. */
	play(): void;
	/** Shows it finished, without motion. */
	still(): void;
	/** Repaints the gilding in the current theme's colours. */
	recolor(): void;
	destroy(): void;
};

export async function mountColophon(canvas: HTMLCanvasElement): Promise<Colophon | null> {
	try {
		await document.fonts.load(`${WEIGHT} 100px "${FAMILY}"`, COLOPHON_TEXT);
	} catch {
		// Falls back to whatever Arabic face the system has.
	}
	const view = canvas.getContext('2d');
	if (!view) return null;

	const L = layout();
	const items = analyse(L);
	const [fillCv, fill] = canvas2d();
	const [revCv, rev] = canvas2d();
	const [inkCv, ink] = canvas2d();
	const [fxCv, fx] = canvas2d();

	let scale = 1, dpr = 1, gold: Rgb = [232, 196, 104], ornFrom = 0;
	let qi = 0, k = 0, budget = 0, pauseUntil = 0, last = 0, endAt = 0, glintAt = 0, raf = 0;
	let wet: { x: number; y: number; r: number; t0: number }[] = [];

	const design = (c: CanvasRenderingContext2D) => c.setTransform(scale * dpr, 0, 0, scale * dpr, 0, 0);
	const device = (c: CanvasRenderingContext2D) => c.setTransform(1, 0, 0, 1, 0, 0);

	const readColors = () => {
		gold = parseColor(getComputedStyle(document.documentElement).getPropertyValue('--color-secondary'));
	};

	// Flat gold in the theme's secondary colour, like the site's other line work.
	const paintFill = () => {
		device(fill);
		fill.clearRect(0, 0, fillCv.width, fillCv.height);
		design(fill);
		drawText(fill, L, css(gold));
	};

	const stamp = (q: Pt) => { rev.beginPath(); rev.arc(q.x, q.y, q.r, 0, Math.PI * 2); rev.fill(); };
	const settle = (comp: Comp) => { rev.imageSmoothingEnabled = true; rev.drawImage(comp.mask, 0, 0, DW, DH); };

	const restamp = () => {
		device(rev);
		rev.clearRect(0, 0, revCv.width, revCv.height);
		design(rev);
		rev.fillStyle = '#000';
		items.forEach((it, i) => {
			if (i < qi) { it.pts.forEach(stamp); if (it.lastOfComp) settle(it.comp); }
			else if (i === qi) it.pts.slice(0, k + 1).forEach(stamp);
		});
	};

	const composeInk = () => {
		device(ink);
		ink.globalCompositeOperation = 'source-over';
		ink.clearRect(0, 0, inkCv.width, inkCv.height);
		ink.drawImage(revCv, 0, 0);
		ink.globalCompositeOperation = 'source-in';
		ink.drawImage(fillCv, 0, 0);
		ink.globalCompositeOperation = 'source-over';
	};

	// A rub el hizb flanks the line once it is finished: Halcyon's lattice
	// motif (Brand.tsx LatticeTile), two 22-unit squares, one turned 45°,
	// in flat gold with a silver boss.
	const star = (x: number, alpha: number) => {
		const y = (L.top + L.bot) / 2;
		const R = 11 * Math.SQRT2; // square corners
		const r = 11 / Math.cos(Math.PI / 8); // where the two squares' edges cross
		view.save();
		design(view);
		view.globalAlpha = alpha;
		view.translate(x, y);
		view.rotate((1 - alpha) * (-Math.PI / 4));
		view.scale(1.9, 1.9);
		view.beginPath();
		for (let i = 0; i < 16; i++) {
			const a = (i * Math.PI) / 8, d = i % 2 ? r : R;
			if (i) view.lineTo(Math.cos(a) * d, Math.sin(a) * d);
			else view.moveTo(d, 0);
		}
		view.closePath();
		view.fillStyle = css(gold);
		view.fill();
		view.fillStyle = SILVER;
		view.beginPath();
		view.arc(0, 0, 3, 0, Math.PI * 2);
		view.fill();
		view.restore();
	};

	const render = (now: number, head: Pt | null) => {
		device(view);
		view.clearRect(0, 0, canvas.width, canvas.height);
		view.drawImage(inkCv, 0, 0);

		device(fx);
		fx.clearRect(0, 0, fxCv.width, fxCv.height);
		design(fx);
		// Wet shine trailing the pen, and one glint across the gilding at the end.
		wet = wet.filter((w) => now - w.t0 < 1000);
		fx.fillStyle = '#fff';
		for (const w of wet) {
			fx.globalAlpha = 0.5 * Math.pow(1 - (now - w.t0) / 1000, 1.7);
			fx.beginPath();
			fx.arc(w.x - w.r * 0.22, w.y - w.r * 0.28, w.r * 0.42, 0, Math.PI * 2);
			fx.fill();
		}
		fx.globalAlpha = 1;
		if (glintAt) {
			const t = (now - glintAt) / 1500;
			if (t >= 1) glintAt = 0;
			else {
				const x = L.right + 120 - (L.right - L.left + 240) * smooth(t);
				const g = fx.createLinearGradient(x - 60, 0, x + 60, 0);
				g.addColorStop(0, 'rgba(255,250,230,0)');
				g.addColorStop(0.5, 'rgba(255,250,230,0.7)');
				g.addColorStop(1, 'rgba(255,250,230,0)');
				fx.fillStyle = g;
				fx.fillRect(x - 60, 0, 120, DH);
			}
		}
		device(fx);
		fx.globalCompositeOperation = 'destination-in';
		fx.drawImage(fillCv, 0, 0);
		fx.globalCompositeOperation = 'source-over';
		view.drawImage(fxCv, 0, 0);

		if (head) {
			// The bead of ink on the pen's tip.
			design(view);
			const r = head.r * 0.6 + 3;
			const g = view.createRadialGradient(head.x, head.y, 0, head.x, head.y, r * 1.6);
			g.addColorStop(0, css(gold, 0.6));
			g.addColorStop(1, css(gold, 0));
			view.fillStyle = g;
			view.beginPath();
			view.arc(head.x, head.y, r * 1.6, 0, Math.PI * 2);
			view.fill();
			view.fillStyle = 'rgba(255,255,255,0.85)';
			view.beginPath();
			view.arc(head.x - r * 0.25, head.y - r * 0.3, Math.max(0.8, r * 0.13), 0, Math.PI * 2);
			view.fill();
		}
		if (ornFrom) {
			const a = smooth(clamp((now - ornFrom) / 900, 0, 1));
			star(L.left - 70, a);
			star(L.right + 70, a);
		}
	};

	const frame = (now: number) => {
		const dt = Math.min(0.05, (now - last) / 1000);
		last = now;
		let head: Pt | null = null, dirty = false;
		if (qi < items.length && now >= pauseUntil) {
			const it = items[qi];
			budget += dt * SPEED;
			if (k === 0) { stamp(it.pts[0]); dirty = true; }
			while (k < it.pts.length - 1) {
				const a = it.pts[k], b = it.pts[k + 1], cost = (b.s - a.s) / a.vf;
				if (cost > budget) break;
				budget -= cost;
				k++;
				stamp(b);
				wet.push({ x: b.x, y: b.y, r: b.r, t0: now });
				dirty = true;
			}
			head = it.pts[k];
			if (k >= it.pts.length - 1) {
				if (it.lastOfComp) settle(it.comp);
				qi++;
				k = 0;
				budget = 0;
				dirty = true;
				const next = items[qi];
				// The pen lifts between letter groups, briefly between branches.
				pauseUntil = now + (next ? (next.newComp ? 130 : 50) : 0);
				if (!next) endAt = now + 250;
			}
		}
		if (dirty) composeInk();
		if (endAt && now >= endAt) { endAt = 0; glintAt = now; ornFrom = now; }
		render(now, head);
		const settling = wet.length || endAt || glintAt || (ornFrom && now - ornFrom < 900);
		if (qi < items.length || settling) raf = requestAnimationFrame(frame);
	};

	const resize = () => {
		const rect = canvas.getBoundingClientRect();
		if (!rect.width) return;
		dpr = Math.min(2, window.devicePixelRatio || 1);
		scale = rect.width / DW;
		for (const c of [canvas, fillCv, revCv, inkCv, fxCv]) {
			c.width = Math.round(rect.width * dpr);
			c.height = Math.round((rect.width * DH / DW) * dpr);
		}
		readColors();
		paintFill();
		restamp();
		composeInk();
		render(performance.now(), null);
	};

	const observer = new ResizeObserver(resize);
	observer.observe(canvas);
	resize();

	return {
		play() {
			cancelAnimationFrame(raf);
			qi = 0; k = 0; budget = 0; endAt = 0; glintAt = 0; ornFrom = 0; wet = [];
			last = performance.now();
			pauseUntil = last;
			restamp();
			composeInk();
			raf = requestAnimationFrame(frame);
		},
		still() {
			cancelAnimationFrame(raf);
			qi = items.length; k = 0; endAt = 0; glintAt = 0; wet = [];
			ornFrom = performance.now() - 900;
			restamp();
			composeInk();
			render(performance.now(), null);
		},
		recolor() {
			readColors();
			paintFill();
			composeInk();
			render(performance.now(), null);
		},
		destroy() {
			cancelAnimationFrame(raf);
			observer.disconnect();
		},
	};
}
