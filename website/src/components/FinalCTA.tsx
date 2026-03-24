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
		<section className="py-40 px-6 md:px-12" id="downloads">
			<div className="max-w-5xl mx-auto">
				{/* Headline */}
				<h2 className="font-headline text-5xl md:text-6xl text-white mb-12 font-bold text-center">
					Download Poise
				</h2>

				{/* Download Grid */}
				<div className="grid grid-cols-1 md:grid-cols-3 gap-8">
					{downloadOptions.map((option) => (
						<a
							key={option.name}
							href={option.url}
							target="_blank"
							rel="noopener noreferrer"
							className="group relative flex flex-col items-center p-8 bg-surface-container-low rounded-3xl hover:bg-surface-container-high transition-colors duration-300"
						>
							{/* Icon */}
							<span className="material-symbols-outlined text-5xl text-primary-container mb-4 group-hover:brightness-125 transition-all">
								{option.icon}
							</span>

							{/* Platform Name */}
							<h3 className="text-2xl font-bold text-white mb-2">{option.name}</h3>

							{/* Disclaimer Badge */}
							{option.disclaimer && (
								<div className="mb-4 px-3 py-1 bg-secondary-fixed-dim/20 rounded-full border border-secondary-fixed-dim/40">
									<span className="text-xs font-bold uppercase tracking-wider text-secondary-fixed-dim">
										{option.disclaimer}
									</span>
								</div>
							)}

							{/* CTA Text */}
							<p className="text-on-surface-variant text-sm">Download Now</p>

							{/* Hover Indicator */}
							<div className="absolute inset-0 rounded-3xl border border-primary-container/0 group-hover:border-primary-container/40 transition-all duration-300 pointer-events-none" />
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