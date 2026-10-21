import { DownloadSimpleBold, GithubLogo } from '../icons';
import CtaButton from './CtaButton';
import HeroSignal from './HeroSignal';
import { REPO_URL } from '../release';
import { revealOnLoad } from '../reveal';

// Headline, then the live signal straight under it, then copy and CTAs.
// Type and band height scale with viewport height so the demo is on
// screen at first paint, even on short laptop displays.
const Hero = () => {
	return (
		<section className="page-scrim relative flex min-h-svh flex-col justify-center overflow-hidden pb-12 pt-24 md:pt-28" id="home">
			<div className="relative z-10 mx-auto flex w-full max-w-5xl flex-col items-center px-6 text-center">
				<div className="kicker mb-5 md:mb-6" {...revealOnLoad(0)}>
					<span className="kicker__dot" />
					free &amp; open source · windows · linux
				</div>
				<h1 className="hero-title font-heading max-w-4xl font-bold leading-[0.9] text-ink">
					<span className="block" {...revealOnLoad(90)}>Filter Music.</span>
					<span className="block text-accent" {...revealOnLoad(200)}>In Real Time.</span>
				</h1>
			</div>

			<div {...revealOnLoad(340, 'fade')}>
				<HeroSignal className="my-6 md:my-7" />
			</div>

			<div className="relative z-10 mx-auto flex w-full max-w-5xl flex-col items-center px-6 text-center">
				<p {...revealOnLoad(460)} className="mb-7 max-w-2xl text-balance text-[1.02rem] leading-[1.6] text-muted md:mb-8 md:text-[1.15rem]">
					System-wide AI that helps you avoid haram audio effortlessly. Pure clarity from chaos.
				</p>

				<div className="flex w-full flex-col items-center justify-center gap-4 sm:w-auto sm:flex-row" {...revealOnLoad(560)}>
					<CtaButton
						className="w-full max-w-[20rem] px-8 py-4 text-[1.02rem] sm:w-auto"
						href="#downloads"
						icon={<DownloadSimpleBold size={20} />}
					>
						Download Poise
					</CtaButton>
					<CtaButton
						className="w-full max-w-[20rem] px-8 py-4 text-[1.02rem] sm:w-auto"
						href={REPO_URL}
						icon={<GithubLogo size={20} />}
						rel="noopener noreferrer"
						target="_blank"
						variant="ghost"
					>
						View source
					</CtaButton>
				</div>
			</div>
		</section>
	);
};

export default Hero;
