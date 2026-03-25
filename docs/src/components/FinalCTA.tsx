import { useEffect, useRef, useState } from 'react';

type InstallGuide = {
	name: string;
	url: string;
	icon: string;
	disclaimer?: string;
	label: string;
	intro: string;
	note?: string;
	steps?: string[];
	commandGroups?: Array<{
		label: string;
		code: string;
	}>;
	links: Array<{
		label: string;
		url: string;
	}>;
};

const downloadOptions: InstallGuide[] = [
	{
		name: "Windows",
		url: "https://github.com/chabandou/poise-voice-isolator/tree/master?tab=readme-ov-file#windows",
		icon: "desktop_windows",
		label: "Desktop Installer",
		intro: "Install the native Windows build, then complete the loopback setup so Poise can capture system audio correctly.",
		note: "Important: install VB Cable first for loopback audio capture on Windows.",
		steps: [
			"Download and install VB Cable.",
			"Download the Poise installer: Poise_Setup.exe.",
			"Run the installer and follow the on-screen instructions.",
			"Launch Poise Voice Isolator from your Desktop or Start Menu.",
		],
		links: [
			{ label: "Download Poise_Setup.exe", url: "https://github.com/chabandou/poise-voice-isolator/releases/download/launch/Poise_Setup.exe" },
			{ label: "Install VB Cable", url: "https://vb-audio.com/Cable/index.htm" },
		],
	},
	{
		name: "Linux",
		url: "https://github.com/chabandou/poise-voice-isolator/tree/master?tab=readme-ov-file#linux-binary",
		icon: "terminal",
		label: "Prebuilt TUI Binary",
		intro: "Run the prebuilt Linux binary directly, or install the Arch package if that matches your setup.",
		commandGroups: [
			{
				label: "Direct Binary",
				code: `# Download the latest release
curl -L -o poise https://github.com/chabandou/Poise-Voice-Isolator/releases/download/v1.0.0/poise

# Make it executable
chmod +x poise

# Move to your PATH (optional)
sudo mv poise /usr/local/bin/

# Run the TUI
poise`,
			},
			{
				label: "Arch Linux",
				code: `sudo pacman -S poise-bin

# Run the TUI
poise`,
			},
		],
		links: [
			{ label: "Open Linux Instructions", url: "https://github.com/chabandou/poise-voice-isolator/tree/master?tab=readme-ov-file#linux-binary" },
		],
	},
	{
		name: "Android",
		url: "https://github.com/chabandou/poise-android#installation",
		icon: "phone_android",
		disclaimer: "SAMSUNG Only",
		label: "Companion App",
		intro: "Android support in this repo is listed as Samsung-only. The actual install flow lives in the dedicated Android project.",
		steps: [
			"Open the Poise Android installation guide.",
			"Follow the Samsung-specific install steps there.",
			"Return to Poise desktop if you want the same local-first workflow across devices.",
		],
		links: [
			{ label: "Open Android Installation", url: "https://github.com/chabandou/poise-android#installation" },
			{ label: "View Android Releases", url: "https://github.com/chabandou/poise-android/releases" },
		],
	},
];

const FinalCTA = () => {
	const [activeGuide, setActiveGuide] = useState<InstallGuide | null>(null);
	const [isClosing, setIsClosing] = useState(false);
	const closeTimeoutRef = useRef<number | null>(null);

	const openGuide = (guide: InstallGuide) => {
		if (closeTimeoutRef.current) {
			window.clearTimeout(closeTimeoutRef.current);
			closeTimeoutRef.current = null;
		}

		setIsClosing(false);
		setActiveGuide(guide);
	};

	const closeGuide = () => {
		if (!activeGuide || isClosing) {
			return;
		}

		setIsClosing(true);
		closeTimeoutRef.current = window.setTimeout(() => {
			setActiveGuide(null);
			setIsClosing(false);
			closeTimeoutRef.current = null;
		}, 280);
	};

	useEffect(() => {
		if (!activeGuide) {
			return;
		}

		const previousOverflow = document.body.style.overflow;
		document.body.style.overflow = 'hidden';

		const handleEscape = (event: KeyboardEvent) => {
			if (event.key === 'Escape') {
				closeGuide();
			}
		};

		window.addEventListener('keydown', handleEscape);

		return () => {
			document.body.style.overflow = previousOverflow;
			window.removeEventListener('keydown', handleEscape);
		};
	}, [activeGuide]);

	useEffect(() => {
		return () => {
			if (closeTimeoutRef.current) {
				window.clearTimeout(closeTimeoutRef.current);
			}
		};
	}, []);

	return (
		<>
			<section className="px-6 pb-20 pt-0 mt-10 md:px-12 md:pb-28 md:pt-15 md:mt-5" id="downloads">
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
							<button
								key={option.name}
								className="group relative flex flex-col items-center rounded-3xl bg-surface-container-low p-8 text-center transition-colors duration-300 hover:bg-surface-container-high"
								onClick={() => openGuide(option)}
								type="button"
							>
								<span className="material-symbols-outlined mb-4 text-5xl text-primary-container transition-all group-hover:brightness-125">
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
								<p className="text-sm text-on-surface-variant">View Install Steps</p>
								<div className="pointer-events-none absolute inset-0 rounded-3xl border border-primary-container/0 transition-all duration-300 group-hover:border-primary-container/40" />
							</button>
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

			{activeGuide && (
				<div
					aria-modal="true"
					aria-labelledby="install-guide-title"
					className={`install-modal-backdrop fixed inset-0 z-[80] flex items-center justify-center bg-background/72 px-4 py-8 backdrop-blur-md ${isClosing ? "install-modal-backdrop--closing" : ""}`}
					onClick={closeGuide}
					role="dialog"
				>
					<div
						className={`install-modal-panel relative max-h-[90vh] w-full max-w-3xl overflow-y-auto rounded-[2rem] border border-white/8 bg-surface-container p-6 shadow-2xl md:p-8 ${isClosing ? "install-modal-panel--closing" : ""}`}
						onClick={(event) => event.stopPropagation()}
					>
						<button
							aria-label="Close install instructions"
							className="absolute right-4 top-4 flex h-10 w-10 items-center justify-center rounded-full border border-white/8 bg-background/70 text-on-surface-variant transition-colors hover:border-primary-fixed/30 hover:text-white"
							onClick={closeGuide}
							type="button"
						>
							<span className="material-symbols-outlined text-[1.15rem]">close</span>
						</button>

						<div className="mb-8 pr-12">
							<div className="mb-4 inline-flex items-center gap-3 rounded-full border border-white/8 bg-background/70 px-4 py-2 text-[11px] font-medium uppercase tracking-[0.22em] text-on-surface-variant">
								<span className="material-symbols-outlined text-[1rem] text-primary-fixed">{activeGuide.icon}</span>
								{activeGuide.label}
							</div>
							<h3 className="font-headline text-4xl font-bold text-white md:text-5xl" id="install-guide-title">{activeGuide.name} Install</h3>
							<p className="mt-4 max-w-2xl text-base leading-relaxed text-on-surface-variant md:text-lg">
								{activeGuide.intro}
							</p>
						</div>

						{activeGuide.note && (
							<div className="mb-6 rounded-2xl border border-primary-fixed/20 bg-primary-fixed/8 p-4 text-sm leading-relaxed text-on-surface">
								{activeGuide.note}
							</div>
						)}

						{activeGuide.steps && (
							<div className="mb-8">
								<h4 className="mb-4 text-xs font-semibold uppercase tracking-[0.24em] text-on-surface-variant">Install Steps</h4>
								<ol className="space-y-4">
									{activeGuide.steps.map((step, index) => (
										<li key={step} className="flex gap-4 rounded-2xl border border-white/6 bg-background/45 p-4">
											<span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary-fixed/12 text-sm font-semibold text-primary-fixed">
												{index + 1}
											</span>
											<p className="pt-1 text-sm leading-relaxed text-on-surface md:text-base">{step}</p>
										</li>
									))}
								</ol>
							</div>
						)}

						{activeGuide.commandGroups && (
							<div className="mb-8 space-y-5">
								{activeGuide.commandGroups.map((group) => (
									<div key={group.label}>
										<h4 className="mb-3 text-xs font-semibold uppercase tracking-[0.24em] text-on-surface-variant">{group.label}</h4>
										<pre className="overflow-x-auto rounded-2xl border border-white/6 bg-background/70 p-4 text-sm leading-relaxed text-on-surface">
											<code>{group.code}</code>
										</pre>
									</div>
								))}
							</div>
						)}

						<div className="flex flex-col gap-3 border-t border-white/6 pt-6 sm:flex-row sm:flex-wrap">
							{activeGuide.links.map((link) => (
								<a
									key={link.url}
									className="inline-flex items-center justify-center gap-2 rounded-full border border-primary-fixed/18 bg-primary-fixed/10 px-5 py-3 text-sm font-medium text-primary-fixed transition-colors hover:bg-primary-fixed/16"
									href={link.url}
									rel="noopener noreferrer"
									target="_blank"
								>
									{link.label}
									<span className="material-symbols-outlined text-[1rem]">arrow_outward</span>
								</a>
							))}
						</div>
					</div>
				</div>
			)}
		</>
	);
};

export default FinalCTA;
