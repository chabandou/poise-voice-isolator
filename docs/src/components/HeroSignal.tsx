import { useCallback, useEffect, useRef, useState } from 'react';
import { PoiseMark } from './Brand';
import { subscribeTheme } from '../themes';

// Hero visual: an audio stream flowing left to right through Poise (the
// gate in the middle). Upstream it is ragged music + noise; once a chunk
// passes the gate while isolation is on, only the voice survives. Turning
// isolation on/off changes the stream at the gate, so the change travels
// outward at the stream's speed, just like real-time processing.

const SPEED = 64; // px per second
const RAMP = 0.35; // seconds for the gate to fully open/close
const AUTO_START_MS = 1800;

const fract = (value: number) => value - Math.floor(value);
const hash = (n: number) => fract(Math.sin(n * 127.1 + 311.7) * 43758.5453);
const smooth = (t: number) => t * t * (3 - 2 * t);
const smoothstep = (a: number, b: number, x: number) => smooth(Math.min(1, Math.max(0, (x - a) / (b - a))));
const noise = (x: number) => {
	const i = Math.floor(x);
	return hash(i) + (hash(i + 1) - hash(i)) * smooth(x - i);
};

// Speech: phrases separated by pauses, words with short gaps, and
// syllables of varying loudness inside each word.
const voiceAt = (n: number) => {
	const phrase = smoothstep(0.3, 0.5, noise(n / 30 + 3.1));
	const word = smoothstep(0.22, 0.42, noise(n / 5.5 + 7.3));
	const syllable = 0.25 + 0.75 * Math.abs(Math.sin(n * 0.55 + 2.2 * noise(n / 8)));
	const loudness = 0.55 + 0.45 * noise(n / 3.1 + 11);
	return phrase * word * syllable * loudness * 0.95 + 0.03;
};

// Music + noise: kick on every 8th column, a tonal bed, and hiss.
const musicAt = (n: number) => {
	const kick = Math.exp(-(((n % 8) + 8) % 8) / 1.5) * 0.45;
	const bed = 0.12 + 0.22 * (0.5 + 0.5 * Math.sin(n * 0.31)) * (0.5 + 0.5 * Math.sin(n * 0.07 + 1));
	return kick + bed + 0.32 * hash(n * 3.7);
};

// Soft limiter so loud passages keep their shape instead of clipping flat.
const limit = (x: number) => 1 - Math.exp(-1.25 * x);

type Rgb = [number, number, number];

const parseColor = (value: string, fallback: Rgb): Rgb => {
	const hex = value.trim().match(/^#([0-9a-f]{6})$/i);
	if (!hex) {
		return fallback;
	}
	const int = parseInt(hex[1], 16);
	return [(int >> 16) & 255, (int >> 8) & 255, int & 255];
};

// `ready` is false while the theme's CSS has not applied yet (its custom
// properties read back empty); the canvas keeps re-reading until it has.
const readPalette = () => {
	const style = getComputedStyle(document.documentElement);
	return {
		ready: style.getPropertyValue('--color-accent').trim() !== '',
		accent: parseColor(style.getPropertyValue('--color-accent'), [95, 213, 235]),
		accentLight: parseColor(style.getPropertyValue('--color-accent-light'), [165, 243, 252]),
		muted: parseColor(style.getPropertyValue('--color-muted'), [139, 148, 163]),
		secondary: parseColor(style.getPropertyValue('--color-secondary'), [232, 196, 104]),
	};
};

const mix = (a: Rgb, b: Rgb, t: number) =>
	`${Math.round(a[0] + (b[0] - a[0]) * t)}, ${Math.round(a[1] + (b[1] - a[1]) * t)}, ${Math.round(a[2] + (b[2] - a[2]) * t)}`;

type Toggle = { time: number; on: boolean };

const HeroSignal = ({ className = '' }: { className?: string }) => {
	const canvasRef = useRef<HTMLCanvasElement>(null);
	const [live, setLive] = useState(false);
	const liveRef = useRef(false);
	const togglesRef = useRef<Toggle[]>([]);
	const interactedRef = useRef(false);
	const clockRef = useRef(0);
	const redrawRef = useRef<() => void>(() => {});

	const setProcessing = useCallback((on: boolean) => {
		if (on === liveRef.current) {
			return;
		}
		liveRef.current = on;
		togglesRef.current.push({ time: clockRef.current, on });
		setLive(on);
		redrawRef.current();
	}, []);

	useEffect(() => {
		const timer = window.setTimeout(() => {
			if (!interactedRef.current) {
				setProcessing(true);
			}
		}, AUTO_START_MS);
		return () => window.clearTimeout(timer);
	}, [setProcessing]);

	useEffect(() => {
		const canvas = canvasRef.current;
		const ctx = canvas?.getContext('2d');
		if (!canvas || !ctx) {
			return;
		}

		const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
		let palette = readPalette();
		let width = 0;
		let height = 0;
		let frame = 0;
		let visible = true;
		let last = performance.now();

		// How "isolated" audio that crossed the gate at `time` is (0..1).
		const processedAt = (time: number) => {
			const toggles = togglesRef.current;
			for (let i = toggles.length - 1; i >= 0; i -= 1) {
				const toggle = toggles[i];
				if (toggle.time <= time) {
					const ramp = smooth(Math.min(1, (time - toggle.time) / RAMP));
					return toggle.on ? ramp : 1 - ramp;
				}
			}
			return 0;
		};

		const draw = () => {
			if (!palette.ready) {
				palette = readPalette();
			}
			const t = clockRef.current;
			const dpr = window.devicePixelRatio || 1;
			ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
			ctx.clearRect(0, 0, width, height);

			const narrow = width < 640;
			const spacing = narrow ? 6 : 7;
			const barWidth = narrow ? 2.5 : 3;
			const gateX = width / 2;
			const cy = height / 2;
			const maxHalf = height * 0.46;
			const gateOpen = processedAt(t);

			// Gate glow + line.
			// Elliptical glow that fades out inside the band (no clipped edges).
			const glowColor = mix(palette.secondary, palette.accent, gateOpen);
			const glowRadius = height * 0.48;
			const glow = ctx.createRadialGradient(0, 0, 0, 0, 0, glowRadius);
			glow.addColorStop(0, `rgba(${glowColor}, ${0.1 + 0.14 * gateOpen})`);
			glow.addColorStop(1, `rgba(${glowColor}, 0)`);
			ctx.save();
			ctx.translate(gateX, cy);
			ctx.scale(2.2, 1);
			ctx.fillStyle = glow;
			ctx.fillRect(-glowRadius, -glowRadius, glowRadius * 2, glowRadius * 2);
			ctx.restore();

			const line = ctx.createLinearGradient(0, 0, 0, height);
			const lineColor = mix(palette.secondary, palette.accentLight, gateOpen);
			line.addColorStop(0, `rgba(${lineColor}, 0)`);
			line.addColorStop(0.5, `rgba(${lineColor}, ${0.35 + 0.4 * gateOpen})`);
			line.addColorStop(1, `rgba(${lineColor}, 0)`);
			ctx.fillStyle = line;
			ctx.fillRect(gateX - 0.75, 0, 1.5, height);

			// Bars glide right; each keeps its stream index n while it moves.
			const travelled = SPEED * t;
			const offset = travelled % spacing;
			const shift = Math.floor(travelled / spacing);
			const count = Math.ceil(width / spacing) + 2;
			const fadeEdge = Math.min(260, width * 0.22);
			ctx.lineCap = 'round';
			ctx.lineWidth = barWidth;

			for (let k = -1; k < count; k += 1) {
				const x = k * spacing + offset;
				const n = k - shift;
				const amount = x <= gateX ? 0 : processedAt(t - (x - gateX) / SPEED);
				const voice = voiceAt(n);
				const noisy = (1 - amount) * musicAt(n);
				const up = limit(voice + noisy) * maxHalf;
				// Unfiltered audio is ragged (asymmetric); clean voice is symmetric.
				const down = limit(voice + noisy * (0.55 + 0.9 * hash(n + 91))) * maxHalf;

				const edge = Math.min(1, Math.min(x, width - x) / fadeEdge);
				const alpha = smooth(Math.max(0, edge)) * (0.42 + 0.53 * amount);
				if (alpha <= 0.01) {
					continue;
				}
				ctx.strokeStyle = `rgba(${mix(palette.muted, palette.accent, amount)}, ${alpha})`;
				ctx.beginPath();
				ctx.moveTo(x, cy - up);
				ctx.lineTo(x, cy + down);
				ctx.stroke();
			}
		};

		const tick = (now: number) => {
			clockRef.current += Math.min(0.05, (now - last) / 1000);
			last = now;
			draw();
			frame = window.requestAnimationFrame(tick);
		};

		const start = () => {
			window.cancelAnimationFrame(frame);
			if (reducedMotion.matches || !visible) {
				// Static frame: show the gate's settled effect across the output side.
				if (reducedMotion.matches) {
					clockRef.current += 60;
					togglesRef.current = [{ time: -1e6, on: liveRef.current }];
				}
				draw();
				return;
			}
			last = performance.now();
			frame = window.requestAnimationFrame(tick);
		};

		const resize = () => {
			const rect = canvas.getBoundingClientRect();
			const dpr = window.devicePixelRatio || 1;
			width = rect.width;
			height = rect.height;
			canvas.width = Math.round(width * dpr);
			canvas.height = Math.round(height * dpr);
			draw();
		};

		const resizeObserver = new ResizeObserver(resize);
		resizeObserver.observe(canvas);
		const intersection = new IntersectionObserver(([entry]) => {
			visible = entry.isIntersecting;
			start();
		});
		intersection.observe(canvas);
		const unsubscribe = subscribeTheme(() => {
			palette = readPalette();
			draw();
		});
		reducedMotion.addEventListener('change', start);

		// Under reduced motion, toggles snap instead of travelling.
		redrawRef.current = () => {
			if (reducedMotion.matches) {
				togglesRef.current = [{ time: -1e6, on: liveRef.current }];
			}
			draw();
		};

		resize();
		start();

		return () => {
			window.cancelAnimationFrame(frame);
			resizeObserver.disconnect();
			intersection.disconnect();
			unsubscribe();
			reducedMotion.removeEventListener('change', start);
		};
	}, []);

	return (
		<div className={`relative w-full ${className}`}>
			<div className="mx-auto grid max-w-5xl grid-cols-[1fr_auto_1fr] items-center gap-4 px-6 font-mono text-[0.72rem] md:px-12 md:text-[0.75rem]">
				<span className="text-muted">
					in · <span className="sm:hidden">noisy</span><span className="hidden sm:inline">music + noise</span>
				</span>
				<span aria-live="polite" className="flex items-center gap-2">
					<span className={`h-2 w-2 rounded-full transition-colors duration-300 ${live ? 'bg-accent' : 'bg-muted'}`} />
					<span className={`transition-colors duration-300 ${live ? 'text-ink' : 'text-muted'}`}>{live ? 'isolating' : 'standby'}</span>
				</span>
				<span className={`text-right transition-colors duration-500 ${live ? 'text-accent' : 'text-muted/60'}`}>
					out · {live ? (
						<><span className="sm:hidden">voice</span><span className="hidden sm:inline">voice only</span></>
					) : 'as-is'}
				</span>
			</div>

			<div className="relative mt-2 h-[clamp(120px,20vh,200px)]">
				<canvas ref={canvasRef} aria-hidden="true" className="absolute inset-0 h-full w-full" />

				{/* The gate: same language as the app's dial (idle secondary, live accent). */}
				<button
					aria-label={live ? 'Stop the isolation demo' : 'Start the isolation demo'}
					aria-pressed={live}
					className={`hero-gate absolute left-1/2 top-1/2 flex h-16 w-16 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full border-2 bg-pill ${
						live ? 'hero-gate--live text-accent' : 'text-secondary'
					}`}
					title={live ? 'Bypass' : 'Isolate'}
					onClick={() => {
						interactedRef.current = true;
						setProcessing(!liveRef.current);
					}}
					type="button"
				>
					{/* Idle: secondary like the app's dial; live: accent. */}
					<PoiseMark className="h-8 w-8" glow={live} tone={live ? 'var(--color-accent)' : 'var(--color-secondary)'} />
				</button>
			</div>

		</div>
	);
};

export default HeroSignal;
