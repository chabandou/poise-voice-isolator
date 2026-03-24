const FinalCTA = () => {
	const downloadOptions = [
		{
			name: "Windows",
			url: "https://github.com/chabandou/poise-voice-isolator/tree/master?tab=readme-ov-file#windows",
			icon: "desktop_windows",
		},
		{
			name: "Linux",
			url: "https://github.com/chabandou/poise-voice-isolator/tree/master?tab=readme-ov-file#linux-binary",
			icon: "terminal",
		},
		{
			name: "Android",
			url: "https://github.com/chabandou/poise-android#installation",
			icon: "phone_android",
			disclaimer: "SAMSUNG Only",
		},
	];

	return (
		<section className="px-6 py-20 md:px-12 md:py-28" id="downloads">
			<div className="max-w-5xl mx-auto">
				{/* Headline */}
				<div className="mb-14 text-center md:mb-16">
					<div className="mb-4 inline-flex items-center gap-3 rounded-full border border-white/8 bg-surface-container/80 px-4 py-2 text-[11px] font-medium uppercase tracking-[0.24em] text-on-surface-variant">
						<span className="h-1.5 w-1.5 rounded-full bg-primary-fixed"></span>
						Choose Your Build
					</div>
					<h2 className="font-headline text-5xl font-bold text-white md:text-6xl">
						Download Poise
					</h2>
					<p className="mx-auto mt-5 max-w-2xl text-lg leading-relaxed text-on-surface-variant">
						Pick the version that fits your environment. Every build stays local-first and open-source.
					</p>
				</div>

				{/* Download Grid */}
				<div className="grid grid-cols-1 gap-6 md:grid-cols-3 md:gap-8">
					{downloadOptions.map((option) => (
						<a
							key={option.name}
							href={option.url}
							target="_blank"
							rel="noopener noreferrer"
							className="group relative flex flex-col items-center rounded-3xl bg-surface-container-low p-8 hover:bg-surface-container-high transition-colors duration-300"
						>
							<span className="material-symbols-outlined mb-4 text-5xl text-primary-container group-hover:brightness-125 transition-all">
								{option.icon}
							</span>
							<h3 className="mb-2 text-2xl font-bold text-white">{option.name}</h3>
							{option.disclaimer && (
								<div className="mb-4 rounded-full border border-secondary-fixed-dim/40 bg-secondary-fixed-dim/20 px-3 py-1">
									<span className="text-xs font-bold uppercase tracking-wider text-secondary-fixed-dim">
										{option.disclaimer}
									</span>
								</div>
							)}
							<p className="text-sm text-on-surface-variant">Download Now</p>
							<div className="pointer-events-none absolute inset-0 rounded-3xl border border-primary-container/0 transition-all duration-300 group-hover:border-primary-container/40" />
						</a>
					))}
				</div>

				{/* Subtitle */}
				<div className="text-center mt-12">
					<p className="text-on-surface-variant text-sm">
						All versions are open-source and available on GitHub
					</p>
				</div>
			</div>
		</section>
	);
};

export default FinalCTA;
