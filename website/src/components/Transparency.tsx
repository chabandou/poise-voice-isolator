const Transparency = () => {
	return (
		<section className="py-32 px-6 md:px-12">
			<div className="max-w-360 mx-auto bg-surface-container-high/40 p-12 md:p-20 rounded-xl border border-white/5 backdrop-blur-xl">
				<div className="flex flex-col md:flex-row items-center justify-between gap-12">
					{/* Left Content */}
					<div className="space-y-8 max-w-xl">
						{/* Badge */}
						<div className="inline-flex items-center gap-2 bg-secondary-fixed-dim/10 text-secondary-fixed-dim px-4 py-1 rounded-full border border-secondary-fixed-dim/20">
							<span
								className="material-symbols-outlined text-sm"
								style={{ fontVariationSettings: "'FILL' 1" }}
							>
								verified_user
							</span>
							<span className="text-[10px] uppercase tracking-widest font-bold">
								Local AI Verified
							</span>
						</div>

						{/* Title */}
						<h2 className="font-headline text-4xl text-white font-medium">
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
									<p className="text-white font-medium">Built with local AI models</p>
									<p className="text-on-surface-variant text-sm">
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
									<p className="text-white font-medium">No internet required after install</p>
									<p className="text-on-surface-variant text-sm">
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
									<p className="text-white font-medium">Open-source on GitHub</p>
									<p className="text-on-surface-variant text-sm">
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
							<span className="font-headline text-2xl text-white font-medium">
								LOCAL AI
							</span>

							{/* Badge */}
							<div className="flex items-center gap-2 text-on-surface-variant text-sm uppercase tracking-widest font-bold">
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