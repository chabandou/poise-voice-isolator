import { useEffect, useRef, useState, type CSSProperties } from 'react';
import CtaButton from './CtaButton';

const BAR_COUNT = 220;

const chaoticBars = Array.from({ length: BAR_COUNT }, (_, index) => {
	const x = index / (BAR_COUNT - 1);
	const envelope = Math.sin(x * Math.PI) ** 1.15;
	const turbulence = ((Math.sin(index * 0.83) + Math.cos(index * 0.37 + 0.8) + 2) / 4);

	return Math.round(18 + envelope * 118 + turbulence * 62);
});

const stableBars = Array.from({ length: BAR_COUNT }, (_, index) => {
	const x = index / (BAR_COUNT - 1);
	const envelope = Math.sin(x * Math.PI) ** 1.45;
	const detail = ((Math.sin(index * 0.48 + 0.6) + Math.cos(index * 0.22) + 2) / 4);

	return Math.round(16 + envelope * 88 + detail * 28);
});

const Hero = () => {
	const [isProcessingWave, setIsProcessingWave] = useState(false);
	const [isProcessingBadge, setIsProcessingBadge] = useState(false);
	const [isProcessingPulseActive, setIsProcessingPulseActive] = useState(false);
	const hasUserInteractedRef = useRef(false);
	const badgeTimerRef = useRef<number | null>(null);

	const clearPendingBadgeTimer = () => {
		if (badgeTimerRef.current !== null) {
			window.clearTimeout(badgeTimerRef.current);
			badgeTimerRef.current = null;
		}
	};

	const applyProcessingState = (nextProcessing: boolean) => {
		clearPendingBadgeTimer();
		setIsProcessingWave(nextProcessing);

		if (nextProcessing) {
			badgeTimerRef.current = window.setTimeout(() => {
				setIsProcessingBadge(true);
				badgeTimerRef.current = null;
			}, 180);
			return;
		}

		setIsProcessingBadge(false);
	};

	useEffect(() => {
		const waveTimer = window.setTimeout(() => {
			if (!hasUserInteractedRef.current) {
				applyProcessingState(true);
			}
		}, 4200);

		return () => {
			window.clearTimeout(waveTimer);
			clearPendingBadgeTimer();
		};
	}, []);

	useEffect(() => {
		if (!isProcessingBadge) {
			return;
		}

		setIsProcessingPulseActive(true);
		const pulseTimer = window.setTimeout(() => {
			setIsProcessingPulseActive(false);
		}, 900);

		return () => window.clearTimeout(pulseTimer);
	}, [isProcessingBadge]);

	const handleProcessingToggle = () => {
		hasUserInteractedRef.current = true;
		applyProcessingState(!isProcessingWave);
	};

	return (
		<section className="relative flex min-h-screen flex-col items-center justify-center overflow-hidden px-6 pb-28 pt-38 md:pb-40 md:pt-44" id="home">
			{/* Background Waveform Visual */}
			<div className="pointer-events-none absolute left-1/2 top-[56%] z-0 w-[150vw] max-w-none -translate-x-1/2 -translate-y-1/2 opacity-26 md:top-1/2 md:opacity-30">
				<div className={`player-waveform waveform-container w-full ${isProcessingWave ? 'is-stable' : 'is-chaotic'}`}>
					<div className="player-waveform__baseline"></div>
					<div className="player-waveform__scan"></div>
					<div className="player-waveform__stage">
						<div className="player-waveform__bars player-waveform__bars--chaotic">
							{chaoticBars.map((height, index) => (
								<span
									key={`chaotic-${index}`}
									className="player-waveform__bar player-waveform__bar--chaotic"
									style={
										{
											'--bar-height': `${height}px`,
											'--bar-phase': `-${260 + index * 42}ms`,
											'--bar-duration': `${1120 + (index % 6) * 110}ms`,
										} as CSSProperties
									}
								/>
							))}
						</div>
						<div className="player-waveform__bars player-waveform__bars--stable">
							{stableBars.map((height, index) => (
								<span
									key={`stable-${index}`}
									className="player-waveform__bar player-waveform__bar--stable"
									style={
										{
											'--bar-height': `${height}px`,
											'--bar-phase': `-${260 + index * 42}ms`,
											'--bar-duration': `${1120 + (index % 6) * 110}ms`,
										} as CSSProperties
									}
								/>
							))}
						</div>
					</div>
				</div>
			</div>

			<div className="absolute inset-x-0 top-28 z-20 md:top-40">
				<div className="mx-auto flex w-full max-w-360 justify-center px-6 md:px-12">
					<button
						aria-label={`Turn processing ${isProcessingWave ? 'off' : 'on'}`}
						aria-pressed={isProcessingWave}
						className={`status-badge flex cursor-pointer items-center gap-2 rounded-full border border-white/5 bg-surface-container-highest/40 px-4 py-2 backdrop-blur-xl ${isProcessingPulseActive ? 'status-badge--pulse' : ''}`}
						onClick={handleProcessingToggle}
						type="button"
					>
						<span className="status-badge__dot-wrap relative flex h-2 w-2">
							{isProcessingBadge && (
								<span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary-fixed opacity-75"></span>
							)}
							<span
								className={`status-badge__dot relative inline-flex h-2 w-2 rounded-full transition-colors duration-300 ${
									isProcessingBadge ? 'bg-primary-fixed' : 'bg-white/35'
								}`}
							></span>
						</span>
						<span className={`font-label text-[10px] uppercase tracking-[0.2em] text-on-surface-variant transition-colors duration-500 ${isProcessingBadge ? 'text-primary-fixed' : ''}`}>
							Processing {isProcessingBadge ? 'On' : 'Off'}
						</span>
					</button>
				</div>
			</div>

			{/* Hero Content */}
			<div className="relative z-10 mx-auto flex w-full max-w-6xl flex-col items-center text-center">
				<h1 className="font-headline my-8 max-w-4xl text-5xl font-bold leading-[0.98] tracking-[-0.05em] text-white sm:text-6xl md:text-7xl lg:text-[6.25rem]">
					Filter Music.<br />
					<span className="text-primary-fixed">In Real Time.</span>
				</h1>
				<p className="font-body mb-14 max-w-2xl text-balance leading-[1.55] text-on-surface-variant text-lg md:text-[1.35rem]">
					System-wide AI that helps you avoid haram audio effortlessly. Pure clarity from chaos.
				</p>

				{/* CTA Buttons */}
				<div className="flex w-full flex-col items-center justify-center gap-4 sm:w-auto sm:flex-row sm:gap-6">
					<CtaButton
						className="neon-glow w-full max-w-[20rem] px-10 py-5 text-lg font-semibold sm:w-auto"
						href="#downloads"
						icon={<span className="material-symbols-outlined text-[1.25em] leading-none">download</span>}
					>
						Download Now
					</CtaButton>
					<CtaButton
						className="w-full max-w-[20rem] px-10 py-5 text-lg font-medium sm:w-auto"
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
				<p className="mt-8 text-[0.72rem] uppercase tracking-[0.24em] text-on-surface-variant/70">
					Local AI. No cloud routing. No streaming detours.
				</p>
			</div>
		</section>
	);
};

export default Hero;
