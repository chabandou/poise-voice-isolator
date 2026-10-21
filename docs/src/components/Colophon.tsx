import { useEffect, useRef } from 'react';
import { mountColophon, type Colophon as Pen } from '../colophon';
import { subscribeTheme } from '../themes';

// How long the line waits, once mostly in view, before the pen sets down.
const DELAY_MS = 700;

// The page's sign-off: تَمَّ بِحَمْدِ اللَّهِ written in gold Ruqʿa, the
// line scribes closed a manuscript with. See src/colophon.ts.
const Colophon = () => {
	const canvasRef = useRef<HTMLCanvasElement>(null);

	useEffect(() => {
		const canvas = canvasRef.current;
		if (!canvas || !('IntersectionObserver' in window)) {
			return;
		}

		const still = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
		let pen: Pen | null = null;
		let preparing: Promise<void> | null = null;
		let disposed = false;
		let wantPlay = false;
		let timer = 0;

		const begin = () => {
			if (!pen) {
				wantPlay = true;
				return;
			}
			observer.disconnect();
			if (still) pen.still();
			else pen.play();
		};

		// Tracing the letters takes a moment, so it runs as the section nears
		// the viewport, before the pen is due.
		const prepare = () => {
			preparing ??= mountColophon(canvas).then((mounted) => {
				if (disposed) {
					mounted?.destroy();
					return;
				}
				pen = mounted;
				if (wantPlay) begin();
			});
		};

		const nearby = new IntersectionObserver(
			([entry]) => {
				if (entry.isIntersecting) {
					nearby.disconnect();
					prepare();
				}
			},
			{ rootMargin: '400px 0px' },
		);
		// Plays once most of the line is on screen; scrolling past before the
		// delay is up cancels it until it comes back.
		const observer = new IntersectionObserver(
			([entry]) => {
				window.clearTimeout(timer);
				if (entry.intersectionRatio >= 0.6) {
					prepare();
					timer = window.setTimeout(begin, still ? 0 : DELAY_MS);
				}
			},
			{ threshold: [0, 0.6] },
		);
		nearby.observe(canvas);
		observer.observe(canvas);

		const unsubscribe = subscribeTheme(() => pen?.recolor());

		return () => {
			disposed = true;
			window.clearTimeout(timer);
			nearby.disconnect();
			observer.disconnect();
			unsubscribe();
			pen?.destroy();
		};
	}, []);

	return (
		<canvas
			ref={canvasRef}
			aria-label="تم بحمد الله, written in gold Ruqʿa calligraphy"
			className="mx-auto mb-12 block aspect-[1000/330] w-96 max-w-full"
			role="img"
		/>
	);
};

export default Colophon;
