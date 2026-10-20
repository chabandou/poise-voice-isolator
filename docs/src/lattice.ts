// Port of stream_denoiser/gui/widgets/lattice.py: the line work a lattice
// theme draws behind the dial. The Islamic patterns come from Hankin's
// polygons-in-contact method (polygons laid edge to edge; from the middle
// of every edge two rays go into the polygon at a fixed angle, each
// stopping where it meets the next edge's ray). They are centred on the
// dial; the app tiles them, here each is built whole for the card.

export type LatticeKind = 'rub_el_hizb' | 'khatam' | 'twelve' | 'dome';

type Spec = {
	/** Line width (design px) and, for strapwork, the band's cleared middle. */
	stroke: number;
	gap: number;
	opacity: number;
	/** "card": clear round the card's middle; "dial": clear round the dial. */
	mask: 'card' | 'dial';
};

export const SPECS: Record<LatticeKind, Spec> = {
	rub_el_hizb: { stroke: 1, gap: 0, opacity: 0.2, mask: 'card' },
	khatam: { stroke: 3.6, gap: 1.6, opacity: 0.22, mask: 'card' },
	twelve: { stroke: 1, gap: 0, opacity: 0.22, mask: 'card' },
	dome: { stroke: 3.4, gap: 1.4, opacity: 0.26, mask: 'dial' },
};

const KHATAM_TILE = 72;
const KHATAM_ANGLE = 45;
const TWELVE_W = 128;
const TWELVE_H = 128 * Math.sqrt(3);
const TWELVE_ANGLE = 60;
const DOME_ANGLE = 67.5;
const DOME_FOLDS = 16;
const DOME_R0 = 150;
export const DOME_MASK_R = 400;
export const DOME_CLEAR = 0.36;
export const DOME_FULL = 0.92;

type Pt = [number, number];
type Poly = Pt[];

const regular = (cx: number, cy: number, n: number, r: number, a0: number): Poly =>
	Array.from({ length: n }, (_, i) => [cx + r * Math.cos(a0 + (2 * Math.PI * i) / n), cy + r * Math.sin(a0 + (2 * Math.PI * i) / n)]);

const rotate = ([x, y]: Pt, a: number): Pt => [x * Math.cos(a) - y * Math.sin(a), x * Math.sin(a) + y * Math.cos(a)];

/** One convex polygon's motif: (m1, p, m2) polylines, edge middle to the
 * rays' meeting and on to the next edge's middle. */
const hankin = (input: Poly, angleDeg: number): [Pt, Pt, Pt][] => {
	let poly = input;
	let area = 0;
	for (let i = 0; i < poly.length; i++) {
		const a = poly[(i + poly.length - 1) % poly.length];
		area += a[0] * poly[i][1] - poly[i][0] * a[1];
	}
	if (area < 0) poly = [...poly].reverse();
	const theta = (angleDeg * Math.PI) / 180;
	const n = poly.length;
	const rays = poly.map((a, i) => {
		const b = poly[(i + 1) % n];
		const length = Math.hypot(b[0] - a[0], b[1] - a[1]);
		const d: Pt = [(b[0] - a[0]) / length, (b[1] - a[1]) / length];
		const mid: Pt = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
		return { mid, ra: rotate(d, theta), rb: rotate([-d[0], -d[1]], -theta) };
	});
	const out: [Pt, Pt, Pt][] = [];
	for (let i = 0; i < n; i++) {
		const { mid: m1, ra } = rays[i];
		const { mid: m2, rb } = rays[(i + 1) % n];
		const den = ra[0] * rb[1] - ra[1] * rb[0];
		if (Math.abs(den) < 1e-9) continue;
		const t = ((m2[0] - m1[0]) * rb[1] - (m2[1] - m1[1]) * rb[0]) / den;
		const reach = Math.max(...poly.map((v) => Math.hypot(v[0] - m1[0], v[1] - m1[1])));
		if (!(t > 0 && t < reach)) continue;
		out.push([m1, [m1[0] + ra[0] * t, m1[1] + ra[1] * t], m2]);
	}
	return out;
};

const near = (poly: Poly, w: number, h: number, pad: number) =>
	Math.max(...poly.map((v) => v[0])) > -pad &&
	Math.min(...poly.map((v) => v[0])) < w + pad &&
	Math.max(...poly.map((v) => v[1])) > -pad &&
	Math.min(...poly.map((v) => v[1])) < h + pad;

/** 4.8.8: octagons on the lattice points, squares between (side t). */
function* tiling488(t: number, is: number[], js: number[], place: (v: Pt) => Pt) {
	const ro = t / 2 / Math.cos(Math.PI / 8);
	const rs = (t * Math.tan(Math.PI / 8)) / Math.sqrt(2);
	for (const i of is) {
		for (const j of js) {
			yield regular(i * t, j * t, 8, ro, Math.PI / 8).map(place);
			yield regular((i + 0.5) * t, (j + 0.5) * t, 4, rs, 0).map(place);
		}
	}
}

const range = (from: number, to: number) => Array.from({ length: Math.max(0, to - from) }, (_, i) => from + i);

const fmt = (v: number) => (Math.round(v * 10) / 10).toString();

const toPath = (lines: [Pt, Pt, Pt][]) =>
	lines.map(([a, b, c]) => `M${fmt(a[0])} ${fmt(a[1])}L${fmt(b[0])} ${fmt(b[1])}L${fmt(c[0])} ${fmt(c[1])}`).join('');

export type LatticeArt = { d: string; dots: [number, number, number][] };

/** A centred pattern for a w x h card, with a star on the dial's centre
 * (cx, cy), at scale s (the preview's dial against the app's). */
export const latticeArt = (kind: Exclude<LatticeKind, 'rub_el_hizb'>, w: number, h: number, cx: number, cy: number, s: number): LatticeArt => {
	const lines: [Pt, Pt, Pt][] = [];
	const dots: [number, number, number][] = [];
	const place = (v: Pt): Pt => [cx + v[0] * s, cy + v[1] * s];
	// Cells (in design units, from the centre) that reach the card.
	const cells = (tw: number, th: number) => ({
		is: range(Math.floor(-cx / s / tw) - 1, Math.ceil((w - cx) / s / tw) + 2),
		js: range(Math.floor(-cy / s / th) - 1, Math.ceil((h - cy) / s / th) + 2),
	});

	if (kind === 'khatam') {
		const { is, js } = cells(KHATAM_TILE, KHATAM_TILE);
		for (const poly of tiling488(KHATAM_TILE, is, js, place)) {
			if (near(poly, w, h, 4)) lines.push(...hankin(poly, KHATAM_ANGLE));
		}
		for (const i of is) {
			for (const j of js) {
				const [x, y] = place([i * KHATAM_TILE, j * KHATAM_TILE]);
				dots.push([x, y, 2 * s]);
				const [mx, my] = place([(i + 0.5) * KHATAM_TILE, (j + 0.5) * KHATAM_TILE]);
				dots.push([mx, my, 1.4 * s]);
			}
		}
	} else if (kind === 'twelve') {
		// 4.6.12: dodecagons on a hexagonal lattice, squares between
		// neighbours, hexagons in the gaps.
		const tw = TWELVE_W;
		const th = TWELVE_H;
		const e = tw / (3 + Math.sqrt(3));
		const rd = e / (2 * Math.sin(Math.PI / 12));
		const { is, js } = cells(tw, th);
		for (const i of is) {
			for (const j of js) {
				for (const [ox, oy] of [
					[i * tw, j * th],
					[i * tw + tw / 2, j * th + th / 2],
				]) {
					dots.push([...place([ox, oy]), 2.4 * s]);
					const polys: Poly[] = [regular(ox, oy, 12, rd, Math.PI / 12)];
					for (let k = 0; k < 3; k++) {
						const a = (Math.PI / 3) * k;
						polys.push(regular(ox + (Math.cos(a) * tw) / 2, oy + (Math.sin(a) * tw) / 2, 4, e / Math.sqrt(2), a + Math.PI / 4));
					}
					for (const a of [Math.PI / 6, Math.PI / 2]) {
						polys.push(regular(ox + (Math.cos(a) * tw) / Math.sqrt(3), oy + (Math.sin(a) * tw) / Math.sqrt(3), 6, e, a + Math.PI / 6));
					}
					for (const poly of polys) {
						const placed = poly.map(place);
						if (near(placed, w, h, 4)) lines.push(...hankin(placed, TWELVE_ANGLE));
					}
				}
			}
		}
	} else {
		// The dome: 4.8.8 in DOME_FOLDS columns wrapped round the dial by a
		// log-polar map, each ring of stars a little larger than the last.
		const step = (2 * Math.PI) / DOME_FOLDS;
		const r0 = DOME_R0 * s;
		const wrap = (v: Pt): Pt => {
			const a = v[0] * step - Math.PI / 2;
			const r = r0 * Math.exp(v[1] * step);
			return [cx + r * Math.cos(a), cy + r * Math.sin(a)];
		};
		const reach = Math.hypot(Math.max(cx, w - cx), Math.max(cy, h - cy)) + 2 * r0;
		const rows = Math.ceil(Math.log(Math.max(reach / r0, 1)) / step) + 1;
		for (const poly of tiling488(1, range(0, DOME_FOLDS), range(-1, rows + 2), wrap)) {
			const mx = poly.reduce((sum, v) => sum + v[0], 0) / poly.length;
			const my = poly.reduce((sum, v) => sum + v[1], 0) / poly.length;
			if (Math.hypot(mx - cx, my - cy) < 0.4 * r0) continue;
			if (near(poly, w, h, 4)) lines.push(...hankin(poly, DOME_ANGLE));
		}
	}
	return { d: toPath(lines), dots: dots.filter(([x, y]) => x > -4 && x < w + 4 && y > -4 && y < h + 4) };
};
