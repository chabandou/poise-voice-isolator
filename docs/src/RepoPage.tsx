import { PoiseMark } from './components/Brand';
import Footer from './components/Footer';
import RepoMap from './components/RepoMap';
import { ArrowRight } from './icons';
import { useReveal } from './reveal';
import { useSmoothScroll } from './smoothScroll';

const HOME = import.meta.env.BASE_URL;

// /repo/: the repository map on a page of its own, for people reading the
// code rather than installing the app (the landing page links it from the
// footer, the README from its file tree).
export default function RepoPage() {
	useReveal();
	useSmoothScroll();

	return (
		<div className="min-h-screen overflow-x-hidden bg-bg text-ink">
			<header className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-6 pt-8 md:px-12">
				<a className="flex items-center gap-2.5" href={HOME}>
					<PoiseMark className="h-8 w-8" />
					<span className="font-heading text-[1.5rem] font-bold leading-none text-ink">Poise</span>
				</a>
				<a className="btn btn-ghost px-4 py-2.5 text-[0.9rem]" href={HOME}>
					<ArrowRight className="rotate-180" size={16} />
					Back to the site
				</a>
			</header>
			<main>
				<RepoMap />
			</main>
			<Footer homeHref={HOME} />
		</div>
	);
}
