import CtaButton from './CtaButton';

const Hero = () => {
	return (
		<section className="relative flex min-h-screen flex-col items-center justify-center overflow-hidden px-6 pb-50 pt-50" id="home">
			{/* Background Waveform Visual */}
			<div className="pointer-events-none absolute inset-x-0 top-1/2 z-0 -translate-y-1/2 opacity-30">
				<div className="waveform-container mx-auto w-[140vw] max-w-none">
					<svg
						aria-hidden="true"
						className="h-[24rem] w-full md:h-[30rem]"
						fill="none"
						viewBox="0 0 1600 320"
						xmlns="http://www.w3.org/2000/svg"
					>
						<defs>
							<linearGradient id="waveGlow" x1="0" x2="1" y1="0.5" y2="0.5">
								<stop offset="0%" stopColor="#22d3ee" stopOpacity="0" />
								<stop offset="18%" stopColor="#22d3ee" stopOpacity="0.75" />
								<stop offset="50%" stopColor="#67e8f9" stopOpacity="1" />
								<stop offset="82%" stopColor="#5eead4" stopOpacity="0.75" />
								<stop offset="100%" stopColor="#5eead4" stopOpacity="0" />
							</linearGradient>
							<linearGradient id="waveSecondary" x1="0" x2="1" y1="0.5" y2="0.5">
								<stop offset="0%" stopColor="#22d3ee" stopOpacity="0" />
								<stop offset="20%" stopColor="#22d3ee" stopOpacity="0.18" />
								<stop offset="50%" stopColor="#67e8f9" stopOpacity="0.32" />
								<stop offset="80%" stopColor="#5eead4" stopOpacity="0.18" />
								<stop offset="100%" stopColor="#5eead4" stopOpacity="0" />
							</linearGradient>
							<filter id="waveBlur" x="-10%" y="-40%" width="120%" height="180%">
								<feGaussianBlur stdDeviation="10" />
							</filter>
						</defs>

						<path
							d="M0 160C60 160 75 118 112 118C154 118 162 242 216 242C270 242 281 54 344 54C406 54 418 282 480 282C545 282 548 88 608 88C668 88 684 212 742 212C804 212 813 138 872 138C935 138 944 258 1004 258C1065 258 1074 72 1138 72C1200 72 1205 230 1268 230C1334 230 1331 112 1396 112C1458 112 1485 160 1600 160"
							filter="url(#waveBlur)"
							stroke="url(#waveSecondary)"
							strokeLinecap="round"
							strokeLinejoin="round"
							strokeWidth="18"
						/>
						<path
							d="M0 160C60 160 75 118 112 118C154 118 162 242 216 242C270 242 281 54 344 54C406 54 418 282 480 282C545 282 548 88 608 88C668 88 684 212 742 212C804 212 813 138 872 138C935 138 944 258 1004 258C1065 258 1074 72 1138 72C1200 72 1205 230 1268 230C1334 230 1331 112 1396 112C1458 112 1485 160 1600 160"
							stroke="url(#waveGlow)"
							strokeLinecap="round"
							strokeLinejoin="round"
							strokeWidth="8"
						/>
						<path
							d="M0 160H1600"
							stroke="url(#waveSecondary)"
							strokeDasharray="8 24"
							strokeOpacity="0.4"
							strokeWidth="1.5"
						/>
					</svg>
				</div>
			</div>

			{/* LIVE Signal Indicator */}
			<div className="absolute right-12 top-40 z-20 flex items-center gap-2 rounded-full bg-surface-container-highest/40 px-4 py-2 backdrop-blur-xl border border-white/5">
				<span className="relative flex h-2 w-2">
					<span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-secondary-fixed-dim opacity-75"></span>
					<span className="relative inline-flex rounded-full h-2 w-2 bg-secondary-fixed-dim"></span>
				</span>
				<span className="font-label text-[10px] uppercase tracking-[0.2em] font-medium text-on-surface-variant">Live Signal</span>
			</div>

			{/* Hero Content */}
			<div className="relative z-10 mx-auto max-w-5xl text-center">
				<h1 className="font-headline mb-8 text-5xl sm:text-6xl font-bold leading-[1.1] tracking-[-0.04em] text-white md:text-7xl">
					Filter Music.<br />
					<span className="text-primary-fixed">In Real Time.</span>
				</h1>
				<p className="font-body mb-12 max-w-xl mx-auto leading-relaxed text-on-surface-variant text-lg md:text-xl">
					System-wide AI that helps you avoid haram audio effortlessly. Pure clarity from chaos.
				</p>

				{/* CTA Buttons */}
				<div className="flex flex-col items-center justify-center gap-6 sm:flex-row">
					<CtaButton
						className="neon-glow px-10 py-5 text-lg font-semibold"
						href="#downloads"
						icon={<span className="material-symbols-outlined text-[1.25em] leading-none">download</span>}
					>
						Download Now
					</CtaButton>
					<CtaButton
						className="px-10 py-5 text-lg font-medium"
						href="https://github.com/chabandou/poise-voice-isolator"
						icon={(
							<svg
								aria-hidden="true"
								className="h-[1.25em] w-[1.25em]"
								fill="currentColor"
								viewBox="0 0 24 24"
							>
								<path d="M12 .5C5.65.5.5 5.66.5 12.03c0 5.1 3.3 9.43 7.87 10.96.58.11.79-.25.79-.56 0-.27-.01-1.17-.02-2.13-3.2.7-3.88-1.37-3.88-1.37-.52-1.34-1.28-1.69-1.28-1.69-1.05-.72.08-.7.08-.7 1.16.08 1.77 1.2 1.77 1.2 1.03 1.78 2.7 1.27 3.36.97.1-.75.4-1.27.73-1.56-2.55-.29-5.23-1.28-5.23-5.71 0-1.26.45-2.29 1.18-3.09-.12-.29-.51-1.46.11-3.04 0 0 .96-.31 3.14 1.18a10.9 10.9 0 0 1 5.72 0c2.18-1.49 3.13-1.18 3.13-1.18.63 1.58.24 2.75.12 3.04.74.8 1.18 1.83 1.18 3.09 0 4.44-2.69 5.41-5.26 5.69.41.36.78 1.08.78 2.18 0 1.57-.01 2.83-.01 3.22 0 .31.21.68.8.56A11.54 11.54 0 0 0 23.5 12.03C23.5 5.66 18.35.5 12 .5Z" />
							</svg>
						)}
						target="_blank"
						rel="noopener noreferrer"
						variant="secondary"
					>
						View Source
					</CtaButton>
				</div>
			</div>
		</section>
	);
};

export default Hero;
