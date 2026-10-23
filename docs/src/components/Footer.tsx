import { PoiseMark } from './Brand';
import { ISSUES_URL, RELEASES_URL, REPO_URL } from '../release';

const links = [
	{ label: 'GitHub', href: REPO_URL },
	{ label: 'Releases', href: RELEASES_URL },
	{ label: 'Report an issue', href: ISSUES_URL },
	// For contributors more than users, so it lives here, not in the header.
	{ label: 'Repo map', href: `${import.meta.env.BASE_URL}repo/`, internal: true },
];

const creditLink = 'text-ink/80 underline-offset-4 transition-colors hover:text-accent hover:underline';

const Footer = ({ homeHref = '#home' }: { homeHref?: string }) => {
	return (
		<footer className="w-full border-t border-white/6 bg-deep py-14">
			<div className="mx-auto flex max-w-360 flex-col gap-10 px-6 md:px-12">
				<div className="flex flex-col items-center justify-between gap-6 md:flex-row">
					<a className="flex items-center gap-2.5" href={homeHref}>
						<PoiseMark className="h-8 w-8" />
						<span className="font-heading text-[1.5rem] font-bold leading-none text-ink">Poise</span>
					</a>

					<nav className="flex flex-wrap justify-center gap-x-7 gap-y-2 text-[0.92rem] text-muted">
						{links.map((link) => (
							<a
								key={link.label}
								className="transition-colors hover:text-ink"
								href={link.href}
								{...(link.internal ? {} : { rel: 'noopener noreferrer', target: '_blank' })}
							>
								{link.label}
							</a>
						))}
					</nav>
				</div>

				{/* Same credits as the app's About page */}
				<div className="flex flex-col items-center justify-between gap-4 border-t border-white/6 pt-8 text-center text-[0.82rem] leading-relaxed text-muted md:flex-row md:text-left">
					<p>
						Denoising:{' '}
						<a className={creditLink} href="https://github.com/Rikorose/DeepFilterNet" rel="noopener noreferrer" target="_blank">DeepFilterNet3</a>
						{' · '}
						<a className={creditLink} href="https://github.com/xiph/rnnoise" rel="noopener noreferrer" target="_blank">RNNoise</a>
						{' · '}Audio routing on Windows: VB-CABLE by{' '}
						<a className={creditLink} href="https://vb-audio.com/" rel="noopener noreferrer" target="_blank">VB-Audio Software</a>
					</p>
					{/* Year can differ between the prerender and the visit (New Year). */}
					<p className="font-mono text-[0.75rem]" suppressHydrationWarning>
						© {new Date().getFullYear()} Poise Voice Isolator · MIT licensed
					</p>
				</div>
			</div>
		</footer>
	);
};

export default Footer;
