const Steps = () => {
	return (
		<section className="bg-surface-container-low px-6 py-20 md:px-12 md:py-24" id="how-it-works">
		<div className="max-w-360 mx-auto">
				<div className="grid grid-cols-1 gap-12 md:grid-cols-3 md:gap-20">
					{/* Step 1: Install */}
					<div className="flex flex-col items-center text-center">
						<div className="w-16 h-16 rounded-2xl bg-surface-container-highest flex items-center justify-center mb-8 border border-white/5">
							<span className="material-symbols-outlined text-primary-fixed text-3xl">download_for_offline</span>
						</div>
						<h3 className="mb-4 font-headline text-[1.7rem] font-semibold tracking-[-0.04em] text-white">Step 1: Install</h3>
						<p className="max-w-[18rem] font-body text-[1rem] leading-[1.65] text-on-surface-variant">Download the lightweight client for your OS and complete the 30-second setup.</p>
					</div>

					{/* Step 2: Run */}
					<div className="flex flex-col items-center text-center">
						<div className="w-16 h-16 rounded-2xl bg-surface-container-highest flex items-center justify-center mb-8 border border-white/5">
							<span className="material-symbols-outlined text-secondary-fixed-dim text-3xl">play_circle</span>
						</div>
						<h3 className="mb-4 font-headline text-[1.7rem] font-semibold tracking-[-0.04em] text-white">Step 2: Run</h3>
						<p className="max-w-[18rem] font-body text-[1rem] leading-[1.65] text-on-surface-variant">Poise lives in your system tray, watching audio streams as they process.</p>
					</div>

					{/* Step 3: Auto-Filter */}
					<div className="flex flex-col items-center text-center">
						<div className="w-16 h-16 rounded-2xl bg-surface-container-highest flex items-center justify-center mb-8 border border-white/5">
							<span className="material-symbols-outlined text-primary-fixed text-3xl">auto_awesome</span>
						</div>
						<h3 className="mb-4 font-headline text-[1.7rem] font-semibold tracking-[-0.04em] text-white">Step 3: Auto-Filter</h3>
						<p className="max-w-[18rem] font-body text-[1rem] leading-[1.65] text-on-surface-variant">AI isolates voices and strips unwanted background audio instantly.</p>
					</div>
				</div>
			</div>
		</section>
	);
};

export default Steps;
