const Hero = () => {
	return (
		<section className="relative flex min-h-screen flex-col items-center justify-center overflow-hidden px-6 pb-50 pt-50" id="home">
			{/* Background Waveform Visual */}
			<div className="pointer-events-none absolute inset-0 z-0 flex items-center justify-center opacity-20">
				<div className="waveform-container flex w-full items-center justify-center gap-1 h-75">
					<div className="w-1 bg-primary-fixed-dim h-12 rounded-full"></div>
					<div className="w-1 bg-secondary-fixed-dim h-32 rounded-full"></div>
					<div className="w-1 bg-primary-fixed-dim h-48 rounded-full"></div>
					<div className="w-1 bg-secondary-fixed-dim h-64 rounded-full"></div>
					<div className="w-1 bg-primary-fixed-dim h-56 rounded-full"></div>
					<div className="w-1 bg-secondary-fixed-dim h-80 rounded-full"></div>
					<div className="w-1 bg-primary-fixed-dim h-40 rounded-full"></div>
					<div className="w-1 bg-secondary-fixed-dim h-60 rounded-full"></div>
					<div className="w-1 bg-primary-fixed-dim h-24 rounded-full"></div>
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
					<a href="#downloads" className="pulse-gradient neon-glow rounded-full px-10 py-5 text-lg font-semibold text-on-primary-fixed transition-all duration-300 hover:brightness-110 active:scale-95">
						Download Now
					</a>
					<button className="rounded-full border border-white/10 bg-surface-container-highest/20 px-10 py-5 text-lg font-medium text-white transition-all duration-300 hover:bg-surface-container-highest/40">
						View Source
					</button>
				</div>
			</div>
		</section>
	);
};

export default Hero;
