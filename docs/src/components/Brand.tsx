import { useId } from 'react';

// The app icon (stream_denoiser/gui/assets/icon.svg): a sine wave that
// fades from the theme accent to silver, with a soft glow.
export const PoiseMark = ({
	className = '',
	glow = true,
	tone = 'var(--color-accent)',
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

// PatternCard's 8-point-star lattice: two overlapping squares and a dot
// per 72px cell, strongest at the edges and fading out toward the middle.
export const Lattice = ({ className = '' }: { className?: string }) => {
	const id = useId();
	const patternId = `${id}-tile`;
	const fadeId = `${id}-fade`;
	const maskId = `${id}-mask`;

	return (
		<svg aria-hidden="true" className={`pointer-events-none absolute inset-0 h-full w-full text-accent ${className}`}>
			<defs>
				<pattern height="72" id={patternId} patternUnits="userSpaceOnUse" width="72" x="50%" y="50%">
					<g fill="none" stroke="currentColor" strokeWidth="1" transform="translate(36 36)">
						<rect height="30" width="30" x="-15" y="-15" />
						<rect height="30" transform="rotate(45)" width="30" x="-15" y="-15" />
						<circle r="3" />
					</g>
				</pattern>
				<radialGradient id={fadeId} r="0.75">
					<stop offset="0.42" stopColor="#000" />
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
