import { useEffect, useState, useSyncExternalStore } from 'react';
import { FileText, GearSix, Info, Minus, Square, Waveform, X } from '@phosphor-icons/react';
import { Lattice, PoiseMark } from './Brand';
import Dial from './Dial';
import { getTheme, setTheme, subscribeTheme, THEMES } from '../themes';
import { reveal } from '../reveal';

type Stats = { load: number; frame: number; skip: boolean; buffer: string };

const idleStats: Stats = { load: 0.42, frame: 4.3, skip: false, buffer: '2/3' };

const navIcons = [
	{ label: 'Home', Icon: Waveform },
	{ label: 'Settings', Icon: GearSix },
	{ label: 'Logs', Icon: FileText },
	{ label: 'About', Icon: Info },
];

const AppWindow = () => {
	const [live, setLive] = useState(false);
	const [strengthDb, setStrengthDb] = useState(-30);
	const [stats, setStats] = useState<Stats>(idleStats);

	useEffect(() => {
		if (!live) {
			return;
		}
		const timer = window.setInterval(() => {
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
		<div className="overflow-hidden rounded-[18px] border border-edge bg-bg shadow-[0_40px_120px_-40px_rgb(0_0_0/0.8)]">
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
					<div className="card relative overflow-hidden px-4 pb-5 pt-6 text-center sm:px-6">
						<Lattice />
						<div className="relative">
							<h3 className="font-heading text-[1.9rem] font-bold leading-tight text-ink sm:text-[2.25rem]">
								{live ? 'Isolating voices' : 'Ready to isolate'}
							</h3>
							<p className={`mt-1 text-[0.95rem] transition-colors duration-300 ${live ? 'text-accent' : 'text-muted'}`}>
								{live ? 'Processing' : 'Press the dial to start.'}
							</p>
							<Dial
								className="mx-auto mt-4 aspect-square w-full max-w-[17rem]"
								live={live}
								onStrengthChange={setStrengthDb}
								onToggle={() => setLive((value) => !value)}
								strengthDb={strengthDb}
							/>
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
		</div>
	);
};

const ThemePicker = () => {
	const active = useSyncExternalStore(subscribeTheme, getTheme, () => 'abyss');
	const activeTheme = THEMES.find((theme) => theme.id === active) ?? THEMES[0];

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
									stroke={theme.accent}
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

const AppPreview = () => (
	<section className="px-6 py-24 md:px-12 md:py-32" id="app">
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
					Preview a theme and press the dial to start isolating, drag the ring to choose how strongly music and noise are
					removed. Fully yours, and in your control. 
				</p>
				<div className="mt-9">
					<ThemePicker />
				</div>
			</div>

			<div {...reveal(160, 'scale')}>
				<AppWindow />
			</div>
		</div>
	</section>
);

export default AppPreview;
