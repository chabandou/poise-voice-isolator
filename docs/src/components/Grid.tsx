const Grid = () => {
	return (
		<section className="px-6 py-24 md:px-12 md:py-32" id="features">
			<div className="max-w-360 mx-auto">
				<h2 className="font-headline mb-14 text-center text-4xl font-medium tracking-tight text-white md:mb-20">
					Designed for total control.
				</h2>

				<div className="grid grid-cols-1 gap-6 md:grid-cols-12 md:gap-8">
					{/* Feature 1: Real-Time Processing */}
					<div className="md:col-span-7 bg-surface-container-low p-12 rounded-xl relative overflow-hidden group hover:bg-surface-container-high transition-colors duration-300">
						<div className="absolute -right-20 -top-20 w-64 h-64 bg-primary-fixed/10 blur-[100px]"></div>
						<span className="material-symbols-outlined text-primary-fixed text-4xl mb-8 block">bolt</span>
						<h4 className="font-headline text-3xl text-white mb-4 font-medium">Real-Time Processing</h4>
						<p className="text-on-surface-variant text-lg max-w-md">
							Zero-latency neural processing ensures your audio sync remains perfect while filtering.
						</p>
					</div>

					{/* Feature 2: System-Wide */}
					<div className="md:col-span-5 bg-surface-container-low p-12 rounded-xl border border-white/5 relative group hover:bg-surface-container-high transition-colors duration-300">
						<span className="material-symbols-outlined text-secondary-fixed-dim text-4xl mb-8 block">public</span>
						<h4 className="font-headline text-3xl text-white mb-4 font-medium">System-Wide</h4>
						<p className="text-on-surface-variant text-lg">
							Works on browsers, apps, and video calls without individual plugin configuration.
						</p>
					</div>

					{/* Feature 3: 100% Local AI */}
					<div className="md:col-span-5 bg-surface-container-low p-12 rounded-xl border border-white/5 relative group hover:bg-surface-container-high transition-colors duration-300">
						<span className="material-symbols-outlined text-primary-fixed text-4xl mb-8 block">lock</span>
						<h4 className="font-headline text-3xl text-white mb-4 font-medium">100% Local AI</h4>
						<p className="text-on-surface-variant text-lg">
							No data ever leaves your device. Private, secure, and fully offline.
						</p>
					</div>

					{/* Feature 4: Smart Isolation */}
					<div className="md:col-span-7 bg-surface-container-low p-12 rounded-xl relative overflow-hidden group hover:bg-surface-container-high transition-colors duration-300">
						<div className="absolute -left-20 -bottom-20 w-64 h-64 bg-secondary-fixed-dim/10 blur-[100px]"></div>
						<span className="material-symbols-outlined text-secondary-fixed-dim text-4xl mb-8 block">psychology</span>
						<h4 className="font-headline text-3xl text-white mb-4 font-medium">Smart Isolation</h4>
						<p className="text-on-surface-variant text-lg max-w-md">
							Distinguishes between speech cues and background audio with extreme precision.
						</p>
					</div>
				</div>
			</div>
		</section>
	);
};

export default Grid;
