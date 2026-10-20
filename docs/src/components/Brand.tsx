import { useId } from 'react';

// The app icon (stream_denoiser/gui/assets/icon*.svg): a sine wave that
// fades from the theme's icon colour to silver, with a soft glow.
export const PoiseMark = ({
	className = '',
	glow = true,
	tone = 'var(--color-icon)',
}: {
	className?: string;
	glow?: boolean;
	/** Colour of the wave's head (the tail always fades to silver). */
	tone?: string;
}) => {
	const id = useId();
	const gradientId = `${id}-wave`;
	const glowId = `${id}-glow`;

	return (
		<svg aria-hidden="true" className={className} fill="none" viewBox="1.5 1.5 21 21">
			<defs>
				<linearGradient gradientUnits="userSpaceOnUse" id={gradientId} x1="12" x2="12" y1="3" y2="21">
					<stop offset="0" stopColor={tone} />
					<stop offset="0.45" stopColor={tone} />
					<stop offset="1" stopColor="#D1D6DD" />
				</linearGradient>
				{glow && (
					<filter height="220%" id={glowId} width="220%" x="-60%" y="-60%">
						<feGaussianBlur result="blur" stdDeviation="0.6" />
						<feMerge>
							<feMergeNode in="blur" />
							<feMergeNode in="SourceGraphic" />
						</feMerge>
					</filter>
				)}
			</defs>
			<path
				d="M3 12C3.00015 8.14286 4.28571 3 6.85714 3C10.7143 2.9999 13.2857 21 17.1429 21C19.7143 21 21 15.8571 21 12 M3 12H5 M19 12H21 M15.5 12H16.5 M7.5 12H8.5"
				filter={glow ? `url(#${glowId})` : undefined}
				stroke={`url(#${gradientId})`}
				strokeLinecap="round"
				strokeLinejoin="round"
				strokeWidth="1.9"
			/>
		</svg>
	);
};

// The line work of one lattice tile (widgets/pattern_card.py _tile_path):
// a square, its 45-degree twin, spokes to the tile's edges and a dot.
export const LatticeTile = () => (
	<g fill="none" stroke="currentColor" strokeWidth="1">
		<rect height="22" width="22" x="21" y="21" />
		<rect height="22" transform="rotate(45 32 32)" width="22" x="21" y="21" />
		<path d="M32 0V16.4M32 47.6V64M0 32H16.4M47.6 32H64M0 0L21 21M64 0L43 21M0 64L21 43M64 64L43 43" />
		<circle cx="32" cy="32" r="2.5" />
	</g>
);

// PatternCard's gilded lattice: 64px tiles starting at (-14, -6), at 20%
// through an elliptical radial mask, clear in the middle and full strength
// at the edges. Colour it with a text-* class; the app's is the secondary
// colour while idle, gliding to the accent while isolating.
export const Lattice = ({ className = 'text-accent' }: { className?: string }) => {
	const id = useId();
	const patternId = `${id}-tile`;
	const fadeId = `${id}-fade`;
	const maskId = `${id}-mask`;

	return (
		<svg aria-hidden="true" className={`pointer-events-none absolute inset-0 h-full w-full ${className}`}>
			<defs>
				<pattern height="64" id={patternId} patternUnits="userSpaceOnUse" width="64" x="-14" y="-6">
					<LatticeTile />
				</pattern>
				<radialGradient cx="0.5" cy="0.55" id={fadeId} r="0.72">
					<stop offset="0.4" stopColor="#000" />
					<stop offset="1" stopColor="#fff" />
				</radialGradient>
				<mask id={maskId}>
					<rect fill={`url(#${fadeId})`} height="100%" width="100%" />
				</mask>
			</defs>
			<rect fill={`url(#${patternId})`} height="100%" mask={`url(#${maskId})`} opacity="0.2" width="100%" />
		</svg>
	);
};

// The About page emblem: a closed tick ring around the mark, with the
// secondary-coloured needle at twelve o'clock.
export const Emblem = ({ className = '' }: { className?: string }) => {
	const ticks = Array.from({ length: 72 }, (_, index) => {
		const angle = (index / 72) * Math.PI * 2 - Math.PI / 2;
		const major = index % 9 === 0;
		const inner = major ? 110 : 118;
		return {
			index,
			x1: 150 + inner * Math.cos(angle),
			y1: 150 + inner * Math.sin(angle),
			x2: 150 + 136 * Math.cos(angle),
			y2: 150 + 136 * Math.sin(angle),
		};
	});

	return (
		<div className={`relative ${className}`}>
			<svg aria-hidden="true" className="h-full w-full" viewBox="0 0 300 300">
				{ticks.map((tick) => (
					<line
						key={tick.index}
						className={tick.index === 0 ? 'stroke-secondary' : 'stroke-accent'}
						opacity={tick.index === 0 ? 1 : 0.78}
						strokeLinecap="round"
						strokeWidth={tick.index === 0 ? 5 : 4}
						x1={tick.x1}
						x2={tick.x2}
						y1={tick.y1}
						y2={tick.y2}
					/>
				))}
				<circle className="fill-pill stroke-groove" cx="150" cy="150" r="88" strokeWidth="2" />
			</svg>
			<PoiseMark className="absolute left-1/2 top-1/2 h-[38%] w-[38%] -translate-x-1/2 -translate-y-1/2" />
		</div>
	);
};
