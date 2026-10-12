import { useEffect, useRef, useState, type ReactNode } from 'react';
import { AndroidLogo, ArrowRight, ArrowUpRight, LinuxLogo, WindowsLogo, X, type Icon } from '@phosphor-icons/react';
import { RELEASE, RELEASES_URL, REPO_URL } from '../release';
import { reveal } from '../reveal';

type InstallGuide = {
	name: string;
	Icon: Icon;
	disclaimer?: string;
	label: string;
	intro: string;
	note?: ReactNode;
	steps?: string[];
	commandGroups?: Array<{
		label: string;
		code: string;
	}>;
	links: Array<{
		label: string;
		url: string;
		primary?: boolean;
	}>;
};

const buildGuides = (windowsUrl: string): InstallGuide[] => [
	{
		name: "Windows",
		Icon: WindowsLogo,
		label: "desktop app",
		intro: "The native Windows app: one dial to start and stop, live stats, and six colour themes.",
		steps: [
			"Download Poise_Setup.exe and run it.",
			"The installer sets up VB-Cable, the virtual audio cable Poise listens to, if it is missing. Restart if Windows asks.",
			"Launch Poise Voice Isolator from the Start menu and press the dial.",
		],
		note: (
			<>
				If Poise reports that VB-Cable is missing, its error dialog offers a one-click install, or you can get it from{" "}
				<a className="text-accent underline-offset-4 hover:underline" href="https://vb-audio.com/Cable/" rel="noopener noreferrer" target="_blank">
					vb-audio.com
				</a>
				. VB-CABLE is donationware by VB-Audio Software.
			</>
		),
		links: [
			{ label: "Download Poise_Setup.exe", url: windowsUrl, primary: true },
			{ label: "All releases", url: RELEASES_URL },
		],
	},
	{
		name: "Linux",
		Icon: LinuxLogo,
		label: "terminal app",
		intro: "A prebuilt terminal UI. Poise routes audio through a PulseAudio/PipeWire null sink and restores your setup on exit.",
		commandGroups: [
			{
				label: "Prebuilt binary",
				code: `# Download the latest release
curl -L -o poise ${RELEASES_URL}/latest/download/poise

# Make it executable
chmod +x poise

# Move it to your PATH (optional)
sudo mv poise /usr/local/bin/

# Run the TUI
poise`,
			},
			{
				label: "Arch Linux (AUR)",
				code: `yay -S poise-bin

# Run the TUI
poise`,
			},
		],
		note: "Using the RNNoise model? Install your distro's rnnoise package too (rnnoise on Arch, librnnoise0 on Debian/Ubuntu).",
		links: [
			{ label: "Linux instructions", url: `${REPO_URL}#linux-binary`, primary: true },
			{ label: "Troubleshooting", url: `${REPO_URL}#linux-troubleshooting` },
		],
	},
	{
		name: "Android",
		Icon: AndroidLogo,
		disclaimer: "Samsung only",
		label: "companion app",
		intro: "Android support is Samsung-only for now. The install flow lives in the dedicated Android project.",
		steps: [
			"Open the Poise Android installation guide.",
			"Follow the Samsung-specific install steps there.",
		],
		links: [
			{ label: "Android installation", url: "https://github.com/chabandou/poise-android#installation", primary: true },
			{ label: "Android releases", url: "https://github.com/chabandou/poise-android/releases" },
		],
	},
];

const FinalCTA = () => {
	const { version, windowsUrl } = RELEASE;
	const downloadOptions = buildGuides(windowsUrl);
	const [activeName, setActiveName] = useState<string | null>(null);
	const activeGuide = downloadOptions.find((option) => option.name === activeName) ?? null;
	const [isClosing, setIsClosing] = useState(false);
	const closeTimeoutRef = useRef<number | null>(null);

	const openGuide = (guide: InstallGuide) => {
		if (closeTimeoutRef.current) {
			window.clearTimeout(closeTimeoutRef.current);
			closeTimeoutRef.current = null;
		}

		setIsClosing(false);
		setActiveName(guide.name);
	};

	const closeGuide = () => {
		if (!activeGuide || isClosing) {
			return;
		}

		setIsClosing(true);
		closeTimeoutRef.current = window.setTimeout(() => {
			setActiveName(null);
			setIsClosing(false);
			closeTimeoutRef.current = null;
		}, 280);
	};

	useEffect(() => {
		if (!activeName) {
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
	}, [activeName]);

	useEffect(() => {
		return () => {
			if (closeTimeoutRef.current) {
				window.clearTimeout(closeTimeoutRef.current);
			}
		};
	}, []);

	return (
		<>
			<section className="px-6 pb-24 pt-8 md:px-12 md:pb-32" id="downloads">
				<div className="mx-auto max-w-5xl">
					<div className="mb-14 text-center md:mb-16">
						<div className="kicker mb-5" {...reveal(0)}>
							<span className="kicker__dot" />
							{version ? <>latest <span className="text-secondary">{version}</span></> : 'choose your build'}
						</div>
						<h2 className="font-heading text-[3.3rem] font-bold leading-none text-ink md:text-[4.4rem]" {...reveal(90)}>
							Download Poise
						</h2>
						<p className="mx-auto mt-5 max-w-2xl text-[1.05rem] leading-[1.65] text-muted md:text-[1.15rem]" {...reveal(180)}>
							Pick the build for your system. Every version runs on-device and is open source.
						</p>
					</div>

					<div className="grid grid-cols-1 gap-5 md:grid-cols-3 md:gap-6">
						{downloadOptions.map((option, index) => (
							<button
								key={option.name}
								{...reveal(index * 110)}
								className="card group flex flex-col items-center p-8 text-center hover:border-secondary"
								onClick={() => openGuide(option)}
								type="button"
							>
								<span className="icon-chip mb-5 h-14 w-14 rounded-[14px]">
									<option.Icon size={30} />
								</span>
								<h3 className="font-heading text-[2rem] font-bold leading-none text-ink">{option.name}</h3>
								<p className="mt-2 font-mono text-[0.75rem] text-muted">{option.label}</p>
								{option.disclaimer && (
									<span className="mt-3 rounded-full border border-secondary/40 bg-secondary/12 px-3 py-0.5 font-mono text-[0.72rem] text-secondary">
										{option.disclaimer}
									</span>
								)}
								<span className="mt-6 inline-flex items-center gap-1.5 text-[0.95rem] font-semibold text-accent">
									Install steps
									<ArrowRight className="transition-transform duration-200 group-hover:translate-x-1" size={16} weight="bold" />
								</span>
							</button>
						))}
					</div>

					<p className="mt-12 text-center text-[0.94rem] text-muted" {...reveal(200, 'fade')}>
						All versions are open source and available on{" "}
						<a className="text-ink underline-offset-4 hover:text-accent hover:underline" href={RELEASES_URL} rel="noopener noreferrer" target="_blank">
							GitHub
						</a>
						.
					</p>
				</div>
			</section>

			{activeGuide && (
				<div
					aria-labelledby="install-guide-title"
					aria-modal="true"
					className={`install-modal-backdrop fixed inset-0 z-[80] flex items-center justify-center bg-bg/75 px-4 py-8 backdrop-blur-md ${isClosing ? "install-modal-backdrop--closing" : ""}`}
					onClick={closeGuide}
					role="dialog"
				>
					<div
						className={`install-modal-panel card relative max-h-[90vh] w-full max-w-3xl overflow-y-auto p-6 shadow-2xl md:p-8 ${isClosing ? "install-modal-panel--closing" : ""}`}
						onClick={(event) => event.stopPropagation()}
					>
						<button
							aria-label="Close install instructions"
							className="btn btn-ghost absolute right-4 top-4 h-10 w-10 p-0"
							onClick={closeGuide}
							type="button"
						>
							<X size={18} />
						</button>

						<div className="mb-7 flex items-start gap-4 pr-12">
							<span className="icon-chip">
								<activeGuide.Icon size={24} />
							</span>
							<div>
								<h3 className="font-heading text-[2.4rem] font-bold leading-none text-ink md:text-[2.9rem]" id="install-guide-title">
									{activeGuide.name}
								</h3>
								<p className="mt-1 font-mono text-[0.78rem] text-muted">{activeGuide.label}</p>
							</div>
						</div>
						<p className="mb-7 max-w-2xl text-[1.02rem] leading-[1.68] text-muted">{activeGuide.intro}</p>

						{activeGuide.steps && (
							<ol className="mb-7 space-y-3">
								{activeGuide.steps.map((step, index) => (
									<li key={step} className="flex gap-4 rounded-xl border border-white/6 bg-pill p-4">
										<span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-secondary/55 font-heading text-[0.9rem] font-bold text-secondary">
											{index + 1}
										</span>
										<p className="text-[0.98rem] leading-[1.6] text-ink">{step}</p>
									</li>
								))}
							</ol>
						)}

						{activeGuide.commandGroups && (
							<div className="mb-7 space-y-5">
								{activeGuide.commandGroups.map((group) => (
									<div key={group.label}>
										<h4 className="mb-2.5 font-mono text-[0.78rem] text-muted">{group.label}</h4>
										<pre className="overflow-x-auto rounded-lg border border-white/10 bg-pill px-4 py-3.5 font-mono text-[0.82rem] leading-relaxed text-ink">
											<code>{group.code}</code>
										</pre>
									</div>
								))}
							</div>
						)}

						{activeGuide.note && (
							<div className="mb-7 rounded-xl border border-secondary/25 bg-secondary/8 p-4 text-[0.95rem] leading-[1.65] text-ink/90">
								{activeGuide.note}
							</div>
						)}

						<div className="flex flex-col gap-3 border-t border-white/8 pt-6 sm:flex-row sm:flex-wrap">
							{activeGuide.links.map((link) => (
								<a
									key={link.url}
									className={`btn ${link.primary ? "btn-primary" : "btn-ghost"} px-5 py-3 text-[0.92rem]`}
									href={link.url}
									rel="noopener noreferrer"
									target="_blank"
								>
									{link.label}
									<ArrowUpRight size={16} weight="bold" />
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
