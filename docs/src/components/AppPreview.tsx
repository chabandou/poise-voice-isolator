import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { FileText, GearSix, Info, Minus, Square, Waveform, X } from '../icons';
import { PoiseMark } from './Brand';
import Dial from './Dial';
import HomeBackdrop, { type DialAnchor } from './HomeBackdrop';
import { getTheme, setTheme, subscribeTheme, THEMES } from '../themes';
import { reveal } from '../reveal';
import { useWindowMotion } from '../windowMotion';

type Stats = { load: number; frame: number; skip: boolean; buffer: string };

const idleStats: Stats = { load: 0.42, frame: 4.3, skip: false, buffer: '2/3' };

const navIcons = [
	{ label: 'Home', Icon: Waveform },
	{ label: 'Settings', Icon: GearSix },
	{ label: 'Logs', Icon: FileText },
	{ label: 'About', Icon: Info },
];

const useActiveTheme = () => {
	const active = useSyncExternalStore(subscribeTheme, getTheme, () => 'halcyon');
	return THEMES.find((theme) => theme.id === active) ?? THEMES[0];
};

// Where the dial sits on the Home card, kept current as the preview resizes
// (the backdrop's geometry is centred on it and sized to it).
const useDialAnchor = () => {
	const cardRef = useRef<HTMLDivElement>(null);
	const dialRef = useRef<HTMLDivElement>(null);
	const [anchor, setAnchor] = useState<DialAnchor | null>(null);

	useEffect(() => {
		const card = cardRef.current;
		const dial = dialRef.current;
		if (!card || !dial) {
			return;
		}
		// Layout offsets, not on-screen boxes: the window's entrance, float
		// and lean transform both, and the backdrop is drawn untransformed.
		const measure = () => {
			if (card.clientWidth < 40 || dial.offsetWidth < 40) {
				return;
			}
			let cx = dial.offsetWidth / 2;
			let cy = dial.offsetHeight / 2;
			for (let el: HTMLElement | null = dial; el && el !== card; el = el.offsetParent as HTMLElement | null) {
				cx += el.offsetLeft;
				cy += el.offsetTop;
			}
			// The backdrop fills the card's padding box.
			const next = { w: card.clientWidth, h: card.clientHeight, cx, cy, k: dial.offsetWidth / 300 };
			setAnchor((prev) =>
				prev && Object.keys(next).every((key) => Math.abs(prev[key as keyof DialAnchor] - next[key as keyof DialAnchor]) < 0.5)
					? prev
					: next,
			);
		};
		measure();
		const observer = new ResizeObserver(measure);
		observer.observe(card);
		observer.observe(dial);
		return () => observer.disconnect();
	}, []);

	return { cardRef, dialRef, anchor };
};

const AppWindow = () => {
	const theme = useActiveTheme();
	const { cardRef, dialRef, anchor } = useDialAnchor();
	const [live, setLive] = useState(false);
	const [strengthDb, setStrengthDb] = useState(-50);
	const [stats, setStats] = useState<Stats>(idleStats);
	const tiltRef = useWindowMotion<HTMLDivElement>();
	const settleRef = useRef<HTMLDivElement>(null);
	const shownTheme = useRef(theme.id);

	// A theme change: the window settles, a touch, to acknowledge it.
	useEffect(() => {
		if (shownTheme.current === theme.id) {
			return;
		}
		shownTheme.current = theme.id;
		if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) {
			return;
		}
		settleRef.current?.animate([{ scale: '1' }, { scale: '0.988', offset: 0.35 }, { scale: '1' }], {
			duration: 520,
			easing: 'cubic-bezier(0.22, 1, 0.36, 1)',
		});
	}, [theme.id]);

	useEffect(() => {
		if (!live) {
			return;
		}
		const timer = window.setInterval(() => {
			// Nobody is watching the status bar while the preview is off screen.
			if (settleRef.current?.closest('[data-offscreen]')) {
				return;
			}
			setStats({
				load: 0.36 + Math.random() * 0.12,
				frame: 3.8 + Math.random() * 1.1,
				// Live like the app: on only while the input is silent.
				skip: Math.random() < 0.15,
				buffer: `${1 + Math.round(Math.random() * 2)}/3`,
			});
		}, 900);
		return () => window.clearInterval(timer);
	}, [live]);

	return (
		<div className="app-stage relative">
			{/* While isolating a glow behind the window swells with each pulse. */}
			<div aria-hidden="true" className={`app-glow ${live ? 'app-glow--live' : ''}`}>
				<div className={`app-glow__pulse ${theme.backdrop === 'sky' ? 'app-glow__pulse--breath' : ''}`} />
			</div>
			<div className="app-float">
				<div ref={tiltRef} className="app-tilt">
					<div ref={settleRef} className="app-window relative overflow-hidden rounded-[18px] border border-edge">
						{/* Title bar (themed, like the Windows build) */}
						<div className="flex h-9 items-center justify-between border-b border-white/5 bg-deep pl-3.5 text-muted">
							<div className="flex items-center gap-2 text-[0.75rem]">
								<PoiseMark className="h-3.5 w-3.5" glow={false} />
								Poise Voice Isolator
							</div>
							<div aria-hidden="true" className="flex h-full">
								<span className="flex w-10 items-center justify-center"><Minus size={13} /></span>
								<span className="flex w-10 items-center justify-center"><Square size={11} /></span>
								<span className="flex w-10 items-center justify-center"><X size={13} /></span>
							</div>
						</div>

						<div className="flex">
							{/* Sidebar */}
							<div className="hidden w-[4.5rem] shrink-0 flex-col items-center gap-2 border-r border-white/8 bg-deep py-5 sm:flex">
								<PoiseMark className="mb-6 h-9 w-9" />
								{navIcons.map(({ label, Icon }, index) => (
									<div
										key={label}
										aria-hidden="true"
										className={`flex h-11 w-[3.6rem] items-center justify-center rounded-[10px] ${index === 0 ? 'nav-wash text-accent' : 'text-muted'}`}
									>
										<Icon size={22} />
									</div>
								))}
							</div>

							{/* Home page */}
							<div className="min-w-0 flex-1 p-3 sm:p-5">
								<div ref={cardRef} className="card relative overflow-hidden px-4 pb-5 pt-6 text-center sm:px-6">
									<HomeBackdrop anchor={anchor} kind={theme.backdrop} lattice={theme.lattice} live={live} />
									<div className="relative">
										<h3 className="app-heading font-heading text-[1.9rem] leading-tight text-ink sm:text-[2.25rem]">
											{live ? 'Isolating voices' : 'Ready to isolate'}
										</h3>
										<p className={`mt-1 text-[0.95rem] transition-colors duration-300 ${live ? 'text-accent' : 'text-muted'}`}>
											{live ? 'Processing' : 'Press the dial to start.'}
										</p>
										<div ref={dialRef} className="mx-auto mt-4 aspect-square w-full max-w-[17rem]">
											<Dial
												breath={theme.backdrop === 'sky'}
												className="h-full w-full"
												live={live}
												onStrengthChange={setStrengthDb}
												onToggle={() => setLive((value) => !value)}
												strengthDb={strengthDb}
											/>
										</div>
										<p className="mt-3 text-[0.8rem] text-muted">Drag the ring to set the reduction strength.</p>
									</div>
								</div>
							</div>
						</div>

						{/* Status bar */}
						<div className="flex h-9 items-center gap-5 overflow-hidden whitespace-nowrap border-t border-white/8 bg-deep px-4 font-mono text-[0.72rem]">
							<span className="flex items-center gap-2 text-ink">
								<span className={`h-2 w-2 rounded-full transition-colors duration-300 ${live ? 'bg-accent' : 'bg-muted'}`} />
								{live ? 'processing' : 'ready'}
							</span>
							{live ? (
								<>
									<span className="text-muted">load <span className="text-success">{stats.load.toFixed(2)}x</span></span>
									<span className="hidden text-muted sm:inline">frame <span className="text-ink">{stats.frame.toFixed(1)} ms</span></span>
									<span className="hidden text-muted md:inline">skip <span className="text-ink">{stats.skip ? 'on' : 'off'}</span></span>
								</>
							) : (
								<span className="text-muted">stats appear when running</span>
							)}
							<span className="ml-auto hidden text-muted sm:inline">source <span className="text-ink">vb-cable</span></span>
						</div>

						{/* The sheen that follows the pointer across the glass. */}
						<div aria-hidden="true" className="app-sheen" />
					</div>
				</div>
			</div>
		</div>
	);
};

const ThemePicker = () => {
	const activeTheme = useActiveTheme();
	const active = activeTheme.id;

	return (
		<div>
			<div className="grid grid-cols-3 gap-3" role="radiogroup" aria-label="Colour theme">
				{THEMES.map((theme, index) => {
					const selected = theme.id === active;
					return (
						<button
							key={theme.id}
							aria-checked={selected}
							className={`theme-tile flex flex-col items-start gap-3 rounded-xl border p-3.5 text-left ${
								selected
									? 'border-secondary shadow-[0_0_0_3px_var(--color-bg),0_0_0_5px_color-mix(in_srgb,var(--color-secondary)_45%,transparent)]'
									: 'border-white/10 hover:border-white/25'
							}`}
							onClick={() => setTheme(theme.id)}
							role="radio"
							{...reveal(260 + index * 70, 'up', { backgroundColor: theme.bg })}
							type="button"
						>
							<svg aria-hidden="true" className="h-6 w-6" fill="none" viewBox="1.5 1.5 21 21">
								<path
									d="M3 12C3.00015 8.14286 4.28571 3 6.85714 3C10.7143 2.9999 13.2857 21 17.1429 21C19.7143 21 21 15.8571 21 12 M3 12H5 M19 12H21 M15.5 12H16.5 M7.5 12H8.5"
									stroke={theme.icon}
									strokeLinecap="round"
									strokeLinejoin="round"
									strokeWidth="1.9"
								/>
							</svg>
							<span className="font-heading text-[1.05rem] font-bold text-white">{theme.label}</span>
						</button>
					);
				})}
			</div>
			<p aria-live="polite" className="mt-4 text-[0.95rem] text-muted">
				{activeTheme.blurb}
			</p>
		</div>
	);
};

// Off screen the preview's endless animations (the float, the dial's
// breathing, the backdrop's pings and sky) hold still: data-offscreen
// pauses them in index.css. Set straight on the DOM, so no re-render.
const usePauseOffscreen = () => {
	const ref = useRef<HTMLElement>(null);

	useEffect(() => {
		const section = ref.current;
		if (!section || !('IntersectionObserver' in window)) {
			return;
		}
		const observer = new IntersectionObserver(
			([entry]) => section.toggleAttribute('data-offscreen', !entry.isIntersecting),
			{ rootMargin: '100px 0px' },
		);
		observer.observe(section);
		return () => observer.disconnect();
	}, []);

	return ref;
};

const AppPreview = () => {
	const sectionRef = usePauseOffscreen();

	return (
		<section ref={sectionRef} className="px-6 py-24 md:px-12 md:py-32" id="app">
			<div className="mx-auto grid max-w-6xl items-center gap-14 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)] lg:gap-16">
				<div>
					<div className="kicker mb-5" {...reveal(0)}>
						<span className="kicker__dot" />
						the app
					</div>
					<h2 className="font-heading text-[2.9rem] font-bold leading-[0.98] text-ink md:text-[3.6rem]" {...reveal(90)}>
						One dial.<br />
						<span className="text-accent">Six colorways.</span>
					</h2>
					<p className="mt-5 max-w-md text-[1.05rem] leading-[1.7] text-muted" {...reveal(180)}>
						Press the dial to start isolating, drag the ring to choose how strongly music and noise are removed. Make it yours, you're in control. 
					</p>
					<div className="mt-9">
						<ThemePicker />
					</div>
				</div>

				<div className="[perspective:1400px]">
					<div {...reveal(160, 'tilt')}>
						<AppWindow />
					</div>
				</div>
			</div>
		</section>
	);
};

export default AppPreview;
