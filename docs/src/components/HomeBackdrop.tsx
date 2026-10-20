import { useId, useMemo, type CSSProperties } from 'react';
import { Lattice, LatticeTile } from './Brand';

// What the app's Home card shows behind the dial (themes.py "backdrop"):
// the gilded lattice (stream_denoiser/gui/widgets/pattern_card.py), which
// pings while isolating, or for Vigil and Eclipse the night sky
// (widgets/sky.py). Both are ports, so the numbers are the app's own; the
// geometry around the dial is in dial units (the dial is 300 across) and
// scaled by k, the preview dial's size against the app's.

/** Where the dial sits on the card, in card px. */
export type DialAnchor = { w: number; h: number; cx: number; cy: number; k: number };

type BackdropProps = { kind: 'lattice' | 'sky'; live: boolean; anchor: DialAnchor | null };

const HomeBackdrop = ({ kind, live, anchor }: BackdropProps) =>
	kind === 'sky' ? (
		anchor && <NightSky anchor={anchor} live={live} />
	) : (
		<>
			<Lattice className={`backdrop-lattice ${live ? 'text-accent' : 'text-secondary'}`} />
			{live && anchor && <LatticePing anchor={anchor} />}
		</>
	);

export default HomeBackdrop;

// -- the lattice's ping --------------------------------------------------------
// While isolating a ring of accent lattice leaves the dial and crosses the
// card: the first as isolating begins, then a fainter one every 5.2 s. The
// ring is the bare lattice seen through a moving radial band (index.css).
const LatticePing = ({ anchor }: { anchor: DialAnchor }) => {
	const id = useId();
	const style = {
		'--cx': `${anchor.cx}px`,
		'--cy': `${anchor.cy}px`,
		'--k': anchor.k,
	} as CSSProperties;

	return (
		<div aria-hidden="true" className="pointer-events-none absolute inset-0" style={style}>
			{['lattice-ping--first', 'lattice-ping--loop'].map((variant) => (
				<svg key={variant} className={`lattice-ping ${variant} absolute inset-0 h-full w-full text-accent`}>
					<defs>
						<pattern height="64" id={`${id}-${variant}`} patternUnits="userSpaceOnUse" width="64" x="-14" y="-6">
							<LatticeTile />
						</pattern>
					</defs>
					<rect fill={`url(#${id}-${variant})`} height="100%" width="100%" />
				</svg>
			))}
		</div>
	);
};

// -- the night sky -------------------------------------------------------------
const SEED = 0x2f6b1d3;
const MOTE_COUNT = 18;
const SPARKLE_COUNT = 26;
const SPARKLE_GAP = 64;
const DESIGN_CARD = [912, 522];
const RING_R = 168;
const STAR_HALF = 136;
const DISC_R = 88;
const BAND_FROM = 90;
const BAND_TO = 780;
const BAND_MS = 3040;

// The design's seeded generator (mulberry32), so the scatter is the app's.
const mulberry32 = (seed: number) => {
	let state = seed >>> 0;
	return () => {
		state = (state + 0x6d2b79f5) >>> 0;
		let t = state;
		t = Math.imul(t ^ (t >>> 15), t | 1);
		t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
		return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
	};
};

type Mote = { fx: number; fy: number; size: number; period: number; offset: number };
type Sparkle = { fx: number; fy: number; size: number; alpha: number; twinkle: number; twinkleAt: number };

// sky.scatter: motes drifting up, and sparkles kept apart and clear of the
// dial and the headline.
const scatter = () => {
	const rand = mulberry32(SEED);
	const motes: Mote[] = [];
	for (let i = 0; i < MOTE_COUNT; i++) {
		const x = 5 + rand() * 90;
		const y = 28 + rand() * 66;
		const size = 1.3 + rand() * 1.6;
		const period = Math.round(14 + rand() * 12) * 1000;
		motes.push({ fx: x / 100, fy: y / 100, size, period, offset: rand() * 20000 });
	}
	const sparkles: Sparkle[] = [];
	const placed: [number, number][] = [];
	const sx = DESIGN_CARD[0] / 100;
	const sy = DESIGN_CARD[1] / 100;
	for (let i = 0; i < 900 && sparkles.length < SPARKLE_COUNT; i++) {
		const x = 3 + rand() * 94;
		const y = 5 + rand() * 90;
		if (((x - 50) / 24) ** 2 + ((y - 53) / 40) ** 2 < 1) continue; // the dial
		if (y < 15 && x > 22 && x < 78) continue; // the headline
		if (y > 90 && x > 15 && x < 85) continue; // under the dial
		const px = (x - 50) * sx;
		const py = (y - 52.5) * sy;
		if (placed.some(([ox, oy]) => Math.hypot(ox - px, oy - py) < SPARKLE_GAP)) continue;
		placed.push([px, py]);
		const size = Math.round(6 + rand() * 7);
		const alpha = 0.55 + rand() * 0.45;
		const twinkle = (4 + rand() * 6) * 1000;
		const twinkleAt = rand() * 8000;
		rand(); // the sway's period and phase (not drawn here)
		rand();
		sparkles.push({ fx: x / 100, fy: y / 100, size, alpha, twinkle, twinkleAt });
	}
	return { motes, sparkles };
};

const SCATTER = scatter();

// An eight-point sparkle, 10 units across (long, short, long...).
const SPARKLE_PATH = (() => {
	const points = Array.from({ length: 16 }, (_, k) => {
		const r = k % 2 ? 0.9 : k % 4 === 0 ? 5 : 2.6;
		const a = (k * Math.PI) / 8;
		return `${(r * Math.sin(a)).toFixed(3)} ${(-r * Math.cos(a)).toFixed(3)}`;
	});
	return `M${points.join('L')}Z`;
})();

// The band's easing, cubic-bezier(0.2, 0.5, 0.3, 1), and when its edge
// reaches a distance (dial units): the moment each sparkle flashes.
const bandEase = (u: number) => {
	const [x1, y1, x2, y2] = [0.2, 0.5, 0.3, 1];
	const at = (t: number, a: number, b: number) => 3 * a * t * (1 - t) ** 2 + 3 * b * t * t * (1 - t) + t ** 3;
	let lo = 0;
	let hi = 1;
	for (let i = 0; i < 24; i++) {
		const mid = (lo + hi) / 2;
		if (at(mid, x1, x2) < u) lo = mid;
		else hi = mid;
	}
	return at((lo + hi) / 2, y1, y2);
};

const bandArrival = (distance: number) => {
	const f = (distance - BAND_FROM) / (BAND_TO - BAND_FROM);
	if (f <= 0) return 0;
	if (f >= 1) return BAND_MS;
	let lo = 0;
	let hi = 1;
	for (let i = 0; i < 24; i++) {
		const mid = (lo + hi) / 2;
		if (bandEase(mid) < f) lo = mid;
		else hi = mid;
	}
	return ((lo + hi) / 2) * BAND_MS;
};

const ms = (value: number) => `${Math.round(value)}ms`;

const NightSky = ({ anchor, live }: { anchor: DialAnchor; live: boolean }) => {
	const id = useId();
	const { w, h, cx, cy, k } = anchor;
	// The design's card is 912 px wide; the preview's sparkles shrink with it.
	const ui = Math.min(1, w / DESIGN_CARD[0] + 0.25);

	const sparkles = useMemo(
		() =>
			SCATTER.sparkles.map((s) => {
				const x = s.fx * w;
				const y = s.fy * h;
				return { ...s, x, y, arrival: bandArrival(Math.hypot(x - cx, y - cy) / k) };
			}),
		[w, h, cx, cy, k],
	);

	const beads = Array.from({ length: 8 }, (_, i) => {
		const angle = (i * Math.PI) / 4;
		return { i, x: RING_R * Math.sin(angle), y: -RING_R * Math.cos(angle) };
	});

	const squares = (
		<>
			<rect height={STAR_HALF * 2} width={STAR_HALF * 2} x={-STAR_HALF} y={-STAR_HALF} />
			<rect height={STAR_HALF * 2} transform="rotate(45)" width={STAR_HALF * 2} x={-STAR_HALF} y={-STAR_HALF} />
		</>
	);

	return (
		<svg
			aria-hidden="true"
			className={`sky pointer-events-none absolute inset-0 h-full w-full ${live ? 'sky--live' : ''}`}
			viewBox={`0 0 ${w} ${h}`}
		>
			<defs>
				<radialGradient cx="0" cy="0" gradientUnits="userSpaceOnUse" id={`${id}-gold`} r="410">
					<stop offset="0" style={{ stopColor: 'var(--color-secondary)', stopOpacity: 0.12 }} />
					<stop offset="0.32" style={{ stopColor: 'var(--color-secondary)', stopOpacity: 0.045 }} />
					<stop offset="0.62" style={{ stopColor: 'var(--color-secondary)', stopOpacity: 0 }} />
				</radialGradient>
				<radialGradient cx="0" cy="0" gradientUnits="userSpaceOnUse" id={`${id}-lit`} r="410">
					<stop offset="0" style={{ stopColor: 'var(--color-accent)', stopOpacity: 0.24 }} />
					<stop offset="0.34" style={{ stopColor: 'var(--color-accent)', stopOpacity: 0.08 }} />
					<stop offset="0.64" style={{ stopColor: 'var(--color-accent)', stopOpacity: 0 }} />
				</radialGradient>
				<radialGradient cx="0" cy="0" gradientUnits="userSpaceOnUse" id={`${id}-band`} r={BAND_TO}>
					<stop offset={(BAND_TO - 150) / BAND_TO} style={{ stopColor: 'var(--color-accent)', stopOpacity: 0 }} />
					<stop offset={(BAND_TO - 50) / BAND_TO} style={{ stopColor: 'var(--color-accent)', stopOpacity: 0.065 }} />
					<stop offset="1" style={{ stopColor: 'var(--color-accent)', stopOpacity: 0 }} />
				</radialGradient>
			</defs>

			{/* Motes of light drifting up through the card. */}
			<g className={`sky__tone ${live ? 'text-accent' : 'text-secondary'}`} fill="currentColor">
				{SCATTER.motes.map((m, i) => (
					<g key={i} transform={`translate(${m.fx * w} ${m.fy * h})`}>
						<g
							className="sky__mote"
							style={{ animationDuration: ms(m.period), animationDelay: ms(-m.offset) } as CSSProperties}
						>
							<circle opacity="0.22" r={(m.size / 2 + 2.6) * ui} />
							<circle r={(m.size / 2) * ui} />
						</g>
					</g>
				))}
			</g>

			{/* Sparkles: a slow twinkle; while isolating, a flash as each pulse reaches them. */}
			<g className={`sky__tone ${live ? 'text-accent-light' : 'text-secondary'}`} fill="currentColor">
				{sparkles.map((s, i) => (
					<g key={i} opacity={s.alpha} transform={`translate(${s.x.toFixed(1)} ${s.y.toFixed(1)}) scale(${(s.size / 10) * ui})`}>
						<g
							className="sky__sparkle"
							style={
								{
									'--twinkle': ms(s.twinkle),
									'--twinkle-at': ms(-s.twinkleAt),
									'--arrival': ms(s.arrival),
								} as CSSProperties
							}
						>
							<path d={SPARKLE_PATH} opacity="0.22" transform="scale(1.5)" />
							<path d={SPARKLE_PATH} />
						</g>
					</g>
				))}
			</g>

			<g transform={`translate(${cx} ${cy}) scale(${k})`}>
				{/* The pulse's band of light. */}
				{live && <circle className="sky__band" fill={`url(#${id}-band)`} r={BAND_TO} />}

				{/* The aura: candle gold at rest, the accent while isolating. */}
				<circle className="sky__aura sky__aura--gold" fill={`url(#${id}-gold)`} r="290" />
				<circle className="sky__aura sky__aura--lit" fill={`url(#${id}-lit)`} r="290" />

				{/* The ring with its beads, and the eight-point star turning slowly. */}
				<g className={`sky__tone ${live ? 'text-accent' : 'text-secondary'}`} fill="none" stroke="currentColor">
					<circle opacity="0.13" r={RING_R} strokeWidth={Math.max(1, k) / k} />
					<g className="sky__turn">
						<g className="sky__star">
							<g className="sky__star-lines" strokeWidth="1">
								{squares}
							</g>
							{live && (
								<g className="sky__charge" stroke="var(--color-accent-light)">
									<g opacity="0.03" strokeWidth="10">{squares}</g>
									<g opacity="0.06" strokeWidth="4">{squares}</g>
									<g opacity="0.26" strokeWidth="1">{squares}</g>
								</g>
							)}
						</g>
					</g>
					<g fill="currentColor" stroke="none">
						{beads.map((b) => (
							<circle key={b.i} className="sky__bead" cx={b.x} cy={b.y} r="1.8" style={{ animationDelay: ms(b.i * 750 - 6000) }} />
						))}
					</g>
				</g>

				{live && (
					<>
						{/* The charge the ring holds, gathering before each pulse (the
						    star's turns with it, above). */}
						<g className="sky__charge text-accent-light" fill="none" stroke="currentColor">
							<circle opacity="0.04" r={RING_R} strokeWidth="10" />
							<circle opacity="0.08" r={RING_R} strokeWidth="4" />
							<circle opacity="0.32" r={RING_R} strokeWidth="1" />
						</g>

						{/* The beads flare as the band passes them. */}
						<g className="text-accent" fill="currentColor">
							{beads.map((b) => (
								<circle key={b.i} className="sky__flare" cx={b.x} cy={b.y} r="3.2" />
							))}
						</g>

						{/* Three halos leave the disc. */}
						<g fill="none">
							{[0, 450, 900].map((delay) => (
								<g key={delay} className="sky__halo" style={{ animationDelay: ms(delay) }}>
									<circle r={DISC_R} stroke="var(--color-accent)" strokeOpacity="0.07" strokeWidth="10" />
									<circle r={DISC_R} stroke="var(--color-accent)" strokeOpacity="0.14" strokeWidth="5" />
									<circle r={DISC_R} stroke="var(--color-accent-light)" strokeWidth="1" />
								</g>
							))}
						</g>
					</>
				)}
			</g>
		</svg>
	);
};
