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
			autoRaf: true,
		});
		lenis = instance;

		return () => {
			instance.destroy();
			lenis = null;
		};
	}, []);
};
