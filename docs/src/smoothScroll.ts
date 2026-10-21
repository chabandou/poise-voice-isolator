import Lenis from 'lenis';
import { useEffect } from 'react';

// A light ease on wheel and trackpad scrolling (Lenis): the page glides to
// a stop instead of jumping notch by notch. The page still scrolls
// natively underneath, so the reveal observer, the sticky header and the
// nav's section tracking see ordinary scroll events. Touch keeps the
// device's own scrolling, and reduced motion keeps the browser's.

let lenis: Lenis | null = null;

/** The running instance, or null (reduced motion, before mount). */
export const getLenis = () => lenis;

export const useSmoothScroll = () => {
	useEffect(() => {
		if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
			return;
		}

		const instance = new Lenis({
			// "A bit": a little quicker to settle than Lenis' default 0.1.
			lerp: 0.12,
		});
		lenis = instance;

		// Driven only while it glides: autoRaf would run a frame loop for as
		// long as the page is open, scrolling or not. Every glide starts in
		// scrollTo (the wheel's included, and it flags itself smooth at once),
		// so that wakes the loop, and the loop sleeps once the glide settles.
		let frame = 0;
		let waking = false;
		const tick = (time: number) => {
			if (waking) {
				// One frame's step, not the whole time asleep.
				instance.time = time - 1000 / 60;
				waking = false;
			}
			instance.raf(time);
			frame = instance.isScrolling === 'smooth' ? requestAnimationFrame(tick) : 0;
		};
		const scrollTo = instance.scrollTo.bind(instance);
		instance.scrollTo = (...args: Parameters<Lenis['scrollTo']>) => {
			scrollTo(...args);
			if (!frame && instance.isScrolling === 'smooth') {
				waking = true;
				frame = requestAnimationFrame(tick);
			}
		};

		return () => {
			cancelAnimationFrame(frame);
			instance.destroy();
			lenis = null;
		};
	}, []);
};
