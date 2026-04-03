import { useCallback, useEffect, useRef, useState, type CSSProperties } from 'react';
import CtaButton from './CtaButton';

const DESKTOP_BAR_COUNT = 220;
const MEDIUM_BAR_COUNT = 45;
const SMALL_BAR_COUNT = 20;
const SMALL_BREAKPOINT_QUERY = '(max-width: 500px)';
const MEDIUM_BREAKPOINT_QUERY = '(min-width: 501px) and (max-width: 1023px)';
type ViewportTier = 'small' | 'medium' | 'desktop';

const createChaoticBars = (barCount: number) =>
	Array.from({ length: barCount }, (_, index) => {
		const x = index / (barCount - 1);
		const envelope = Math.sin(x * Math.PI) ** 1.15;
		const turbulence = ((Math.sin(index * 0.83) + Math.cos(index * 0.37 + 0.8) + 2) / 4);

		return Math.round(18 + envelope * 118 + turbulence * 62);
	});

const createStableBars = (barCount: number) =>
	Array.from({ length: barCount }, (_, index) => {
		const x = index / (barCount - 1);
		const envelope = Math.sin(x * Math.PI) ** 1.45;
		const detail = ((Math.sin(index * 0.48 + 0.6) + Math.cos(index * 0.22) + 2) / 4);

		return Math.round(16 + envelope * 88 + detail * 28);
	});

const chaoticDesktopBars = createChaoticBars(DESKTOP_BAR_COUNT);
const chaoticMediumBars = createChaoticBars(MEDIUM_BAR_COUNT);
const chaoticSmallBars = createChaoticBars(SMALL_BAR_COUNT);
const stableDesktopBars = createStableBars(DESKTOP_BAR_COUNT);
const stableMediumBars = createStableBars(MEDIUM_BAR_COUNT);
const stableSmallBars = createStableBars(SMALL_BAR_COUNT);

const getViewportTier = (): ViewportTier => {
	if (typeof window === 'undefined') {
		return 'desktop';
	}

	if (window.matchMedia(SMALL_BREAKPOINT_QUERY).matches) {
		return 'small';
	}

	if (window.matchMedia(MEDIUM_BREAKPOINT_QUERY).matches) {
		return 'medium';
	}

	return 'desktop';
};

const Hero = () => {
	const [viewportTier, setViewportTier] = useState<ViewportTier>(getViewportTier);
	const [isProcessingWave, setIsProcessingWave] = useState(false);
	const [isProcessingBadge, setIsProcessingBadge] = useState(false);
	const [isProcessingPulseActive, setIsProcessingPulseActive] = useState(false);
	const [isWaveTransitioning, setIsWaveTransitioning] = useState(false);
	const hasUserInteractedRef = useRef(false);
	const isProcessingWaveRef = useRef(false);
	const badgeTimerRef = useRef<number | null>(null);
	const waveTransitionTimerRef = useRef<number | null>(null);
	const pulseTimerRef = useRef<number | null>(null);

	const clearPendingBadgeTimer = useCallback(() => {
		if (badgeTimerRef.current !== null) {
			window.clearTimeout(badgeTimerRef.current);
			badgeTimerRef.current = null;
		}
	}, []);

	const clearPendingWaveTransitionTimer = useCallback(() => {
		if (waveTransitionTimerRef.current !== null) {
			window.clearTimeout(waveTransitionTimerRef.current);
			waveTransitionTimerRef.current = null;
		}
	}, []);

	const clearPendingPulseTimer = useCallback(() => {
		if (pulseTimerRef.current !== null) {
			window.clearTimeout(pulseTimerRef.current);
			pulseTimerRef.current = null;
		}
	}, []);

	const isLiteWaveMode = viewportTier !== 'desktop';
	const visibleChaoticBars = viewportTier === 'small'
		? chaoticSmallBars
		: viewportTier === 'medium'
			? chaoticMediumBars
			: chaoticDesktopBars;
	const visibleStableBars = viewportTier === 'small'
		? stableSmallBars
		: viewportTier === 'medium'
			? stableMediumBars
			: stableDesktopBars;
	const visibleBarCount = viewportTier === 'small'
		? SMALL_BAR_COUNT
		: viewportTier === 'medium'
			? MEDIUM_BAR_COUNT
			: DESKTOP_BAR_COUNT;
	const barPhaseStep = viewportTier === 'small' ? 58 : viewportTier === 'medium' ? 50 : 42;
	const chaoticDurationBase = viewportTier === 'small' ? 1480 : viewportTier === 'medium' ? 1320 : 1120;
	const stableDurationBase = viewportTier === 'small' ? 1680 : viewportTier === 'medium' ? 1480 : 1120;
	const barDurationStep = viewportTier === 'small' ? 140 : viewportTier === 'medium' ? 120 : 110;
	const barDurationModulo = viewportTier === 'desktop' ? 6 : 5;

	useEffect(() => {
		if (typeof window === 'undefined') {
			return;
		}

		const smallQuery = window.matchMedia(SMALL_BREAKPOINT_QUERY);
		const mediumQuery = window.matchMedia(MEDIUM_BREAKPOINT_QUERY);
		const handleViewportChange = () => {
			setViewportTier(getViewportTier());
		};

		smallQuery.addEventListener('change', handleViewportChange);
		mediumQuery.addEventListener('change', handleViewportChange);

		return () => {
			smallQuery.removeEventListener('change', handleViewportChange);
			mediumQuery.removeEventListener('change', handleViewportChange);
		};
	}, []);

	const applyProcessingState = useCallback((nextProcessing: boolean) => {
		clearPendingBadgeTimer();
		clearPendingWaveTransitionTimer();
		clearPendingPulseTimer();

		if (isLiteWaveMode) {
			setIsWaveTransitioning(false);
		}

		if (!isLiteWaveMode && nextProcessing !== isProcessingWaveRef.current) {
			setIsWaveTransitioning(true);
			waveTransitionTimerRef.current = window.setTimeout(() => {
				setIsWaveTransitioning(false);
				waveTransitionTimerRef.current = null;
			}, 900);
		}

		isProcessingWaveRef.current = nextProcessing;
		setIsProcessingWave(nextProcessing);

		if (nextProcessing) {
			badgeTimerRef.current = window.setTimeout(() => {
				setIsProcessingBadge(true);
				setIsProcessingPulseActive(true);
				pulseTimerRef.current = window.setTimeout(() => {
					setIsProcessingPulseActive(false);
					pulseTimerRef.current = null;
				}, 900);
				badgeTimerRef.current = null;
			}, 180);
			return;
		}

		setIsProcessingBadge(false);
		setIsProcessingPulseActive(false);
	}, [clearPendingBadgeTimer, clearPendingPulseTimer, clearPendingWaveTransitionTimer, isLiteWaveMode]);

	useEffect(() => {
		const waveTimer = window.setTimeout(() => {
			if (!hasUserInteractedRef.current) {
				applyProcessingState(true);
			}
		}, 4200);

		return () => {
			window.clearTimeout(waveTimer);
			clearPendingBadgeTimer();
			clearPendingPulseTimer();
			clearPendingWaveTransitionTimer();
		};
	}, [applyProcessingState, clearPendingBadgeTimer, clearPendingPulseTimer, clearPendingWaveTransitionTimer]);

	useEffect(() => {
		return () => {
			clearPendingPulseTimer();
			clearPendingWaveTransitionTimer();
		};
	}, [clearPendingPulseTimer, clearPendingWaveTransitionTimer]);

	const handleProcessingToggle = () => {
		hasUserInteractedRef.current = true;
		applyProcessingState(!isProcessingWaveRef.current);
	};

	return (
		<section className="relative flex min-h-screen flex-col items-center justify-center overflow-hidden px-6 pb-28 pt-38 md:pb-40 md:pt-44" id="home">
			{/* Background Waveform Visual */}
			<div className="pointer-events-none absolute left-1/2 top-[56%] z-0 w-[150vw] max-w-none -translate-x-1/2 -translate-y-1/2 opacity-26 md:top-1/2 md:opacity-30">
				<div className={`player-waveform waveform-container w-full ${isProcessingWave ? 'is-stable' : 'is-chaotic'}`}>
					<div className="player-waveform__baseline"></div>
					<div className="player-waveform__scan"></div>
					<div className="player-waveform__stage">
						{(isWaveTransitioning || !isProcessingWave) && (
							<div
								className="player-waveform__bars player-waveform__bars--chaotic"
								style={{ '--waveform-columns': `${visibleBarCount}` } as CSSProperties}
							>
								{visibleChaoticBars.map((height, index) => (
									<span
										key={`chaotic-${index}`}
										className="player-waveform__bar player-waveform__bar--chaotic"
										style={
											{
												'--bar-height': `${height}px`,
												'--bar-phase': `-${260 + index * barPhaseStep}ms`,
												'--bar-duration': `${chaoticDurationBase + (index % barDurationModulo) * barDurationStep}ms`,
											} as CSSProperties
										}
									/>
								))}
							</div>
						)}
						{(isWaveTransitioning || isProcessingWave) && (
							<div
								className="player-waveform__bars player-waveform__bars--stable"
								style={{ '--waveform-columns': `${visibleBarCount}` } as CSSProperties}
							>
								{visibleStableBars.map((height, index) => (
									<span
										key={`stable-${index}`}
										className="player-waveform__bar player-waveform__bar--stable"
										style={
											{
												'--bar-height': `${height}px`,
												'--bar-phase': `-${260 + index * barPhaseStep}ms`,
												'--bar-duration': `${stableDurationBase + (index % barDurationModulo) * barDurationStep}ms`,
											} as CSSProperties
										}
									/>
								))}
							</div>
						)}
					</div>
				</div>
			</div>

			<div className="absolute inset-x-0 top-28 z-20 md:top-40">
				<div className="mx-auto flex w-full max-w-360 justify-center px-6 md:px-12">
					<button
						aria-label={`Turn processing ${isProcessingWave ? 'off' : 'on'}`}
						aria-pressed={isProcessingWave}
						className={`status-badge flex cursor-pointer items-center gap-2 rounded-full border border-white/5 bg-surface-container-highest/65 px-4 py-2 md:bg-surface-container-highest/40 md:backdrop-blur-xl ${isProcessingPulseActive ? 'status-badge--pulse' : ''}`}
						onClick={handleProcessingToggle}
						type="button"
					>
						<span className="status-badge__dot-wrap relative flex h-2 w-2">
							{isProcessingBadge && !isLiteWaveMode && (
								<span className="status-badge__dot-ping absolute inline-flex h-full w-full animate-ping rounded-full bg-primary-fixed opacity-75"></span>
							)}
							<span
								className={`status-badge__dot relative inline-flex h-2 w-2 rounded-full transition-colors duration-300 ${
									isProcessingBadge ? 'bg-primary-fixed' : 'bg-white/35'
								}`}
							></span>
						</span>
						<span className={`font-label text-[0.69rem] font-medium uppercase tracking-[0.18em] text-on-surface-variant transition-colors duration-500 ${isProcessingBadge ? 'text-primary-fixed' : ''}`}>
							Processing {isProcessingBadge ? 'On' : 'Off'}
						</span>
					</button>
				</div>
			</div>

			{/* Hero Content */}
			<div className="relative z-10 mx-auto flex w-full max-w-6xl flex-col items-center text-center">
				<h1 className="font-headline my-8 max-w-4xl text-[3.45rem] font-semibold leading-[0.92] tracking-[-0.065em] text-white sm:text-[4.45rem] md:text-[5.55rem] lg:text-[6rem]">
					Filter Music.<br />
					<span className="text-primary-fixed">In Real Time.</span>
				</h1>
				<p className="font-body mb-14 max-w-2xl text-balance text-[1.04rem] leading-[1.62] text-on-surface-variant md:text-[1.22rem]">
					System-wide AI that helps you avoid haram audio effortlessly. Pure clarity from chaos.
				</p>

				{/* CTA Buttons */}
				<div className="flex w-full flex-col items-center justify-center gap-4 sm:max-w-120 sm:flex-row sm:gap-6">
					<CtaButton
						className="hero-cta neon-glow w-full max-w-[20rem] px-10 py-5 text-[1.02rem] font-semibold sm:max-w-none sm:flex-1"
						href="#downloads"
						icon={<span className="material-symbols-outlined text-[1.25em] leading-none">download</span>}
					>
						Download Now
					</CtaButton>
					<CtaButton
						className="hero-cta w-full max-w-[20rem] px-10 py-5 text-[1.02rem] font-medium sm:max-w-none sm:flex-1"
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
				<p className="mt-8 font-body text-[0.68rem] font-medium uppercase tracking-[0.18em] text-on-surface-variant/70">
					Local AI. No cloud routing. No streaming detours.
				</p>
			</div>
		</section>
	);
};

export default Hero;
