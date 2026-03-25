const Transparency = () => {
	return (
		<section className="px-6 py-24 md:px-12 md:py-32">
			<div className="mx-auto max-w-360 rounded-xl border border-white/5 bg-surface-container-high/40 p-8 backdrop-blur-xl md:p-20">
				<div className="flex flex-col items-center justify-between gap-10 md:flex-row md:gap-12">
					{/* Left Content */}
					<div className="space-y-8 max-w-xl">
						{/* Badge */}
						<div className="inline-flex items-center gap-2 rounded-full border border-secondary-fixed-dim/20 bg-secondary-fixed-dim/10 px-4 py-1">
							<span
								className="material-symbols-outlined text-sm"
								style={{ fontVariationSettings: "'FILL' 1" }}
							>
								verified_user
							</span>
							<span className="font-label text-[0.69rem] font-semibold uppercase tracking-[0.18em]">
								Local AI Verified
							</span>
						</div>

						{/* Title */}
						<h2 className="font-headline text-[2.5rem] font-semibold tracking-[-0.05em] text-white md:text-[3.15rem]">
							Technically Transparent.
						</h2>

						{/* Features List */}
						<ul className="space-y-6">
							{/* Item 1 */}
							<li className="flex items-start gap-4">
								<span className="material-symbols-outlined text-primary-fixed mt-1">
									memory
								</span>
								<div>
									<p className="font-body text-[1.08rem] font-medium tracking-[-0.015em] text-white">Built with local AI models</p>
									<p className="font-body text-[0.98rem] leading-[1.65] text-on-surface-variant">
										Optimized for CPU and GPU acceleration without cloud reliance.
									</p>
								</div>
							</li>

							{/* Item 2 */}
							<li className="flex items-start gap-4">
								<span className="material-symbols-outlined text-primary-fixed mt-1">
									no_sim
								</span>
								<div>
									<p className="font-body text-[1.08rem] font-medium tracking-[-0.015em] text-white">No internet required after install</p>
									<p className="font-body text-[0.98rem] leading-[1.65] text-on-surface-variant">
										Works perfectly in airplane mode or secure offline environments.
									</p>
								</div>
							</li>

							{/* Item 3 */}
							<li className="flex items-start gap-4">
								<span className="material-symbols-outlined text-primary-fixed mt-1">
									code
								</span>
								<div>
									<p className="font-body text-[1.08rem] font-medium tracking-[-0.015em] text-white">Open-source on GitHub</p>
									<p className="font-body text-[0.98rem] leading-[1.65] text-on-surface-variant">
										Audit the code, contribute to the engine, or build your own fork.
									</p>
								</div>
							</li>
						</ul>
					</div>

					{/* Right Visual Card */}
					<div className="relative w-full md:w-100 aspect-square flex items-center justify-center">
						{/* Background Glow */}
						<div className="absolute inset-0 bg-primary-fixed/5 rounded-full blur-[60px]"></div>

						{/* Card */}
						<div className="relative bg-surface-container-highest p-12 rounded-3xl border border-white/10 flex flex-col items-center gap-6 shadow-2xl">
							{/* Shield Icon */}
							<span
								className="material-symbols-outlined text-primary-fixed"
								style={{ fontVariationSettings: "'FILL' 1", fontSize: "120px", lineHeight: "120px" }}
							>
								shield
							</span>

							{/* Title */}
							<span className="font-headline text-[1.75rem] font-semibold tracking-[-0.04em] text-white">
								LOCAL AI
							</span>

							{/* Badge */}
							<div className="flex items-center gap-2 font-label text-[0.7rem] font-semibold uppercase tracking-[0.18em] text-on-surface-variant">
								<span className="material-symbols-outlined text-sm">lock</span>
								Encrypted &amp; Private
							</div>
						</div>
					</div>
				</div>
			</div>
		</section>
	);
};

export default Transparency;
