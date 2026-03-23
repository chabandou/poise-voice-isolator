const Steps = () => {
	return (
		<section className="py-24 px-6 md:px-12 bg-surface-container-low" id="how-it-works">
		<div className="max-w-360 mx-auto">
				<div className="grid grid-cols-1 md:grid-cols-3 gap-20">
					{/* Step 1: Install */}
					<div className="flex flex-col items-center text-center">
						<div className="w-16 h-16 rounded-2xl bg-surface-container-highest flex items-center justify-center mb-8 border border-white/5">
							<span className="material-symbols-outlined text-primary-fixed text-3xl">download_for_offline</span>
						</div>
						<h3 className="font-headline text-2xl text-white mb-4 font-medium">Step 1: Install</h3>
						<p className="text-on-surface-variant leading-relaxed">Download the lightweight client for your OS and complete the 30-second setup.</p>
					</div>

					{/* Step 2: Run */}
					<div className="flex flex-col items-center text-center">
						<div className="w-16 h-16 rounded-2xl bg-surface-container-highest flex items-center justify-center mb-8 border border-white/5">
							<span className="material-symbols-outlined text-secondary-fixed-dim text-3xl">play_circle</span>
						</div>
						<h3 className="font-headline text-2xl text-white mb-4 font-medium">Step 2: Run</h3>
						<p className="text-on-surface-variant leading-relaxed">Poise lives in your system tray, watching audio streams as they process.</p>
					</div>

					{/* Step 3: Auto-Filter */}
					<div className="flex flex-col items-center text-center">
						<div className="w-16 h-16 rounded-2xl bg-surface-container-highest flex items-center justify-center mb-8 border border-white/5">
							<span className="material-symbols-outlined text-primary-fixed text-3xl">auto_awesome</span>
						</div>
						<h3 className="font-headline text-2xl text-white mb-4 font-medium">Step 3: Auto-Filter</h3>
						<p className="text-on-surface-variant leading-relaxed">AI isolates voices and strips unwanted background audio instantly.</p>
					</div>
				</div>
			</div>
		</section>
	);
};

export default Steps;