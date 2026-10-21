import { useEffect, type CSSProperties } from 'react';

// Scroll-triggered entrance animations. Mark an element with
// {...reveal(delayMs, variant)}; useReveal() (mounted once in App) sets
// data-revealed when it scrolls into view, which plays the CSS animation in
// index.css. Variants: up (default), fade, scale, line, spin, tilt (rises
// from a slight backward lean; its parent needs a perspective), draw (no
// motion of its own: its children draw themselves on, e.g. Brand's Emblem).
//
// The marker is an attribute React never renders, not a class: React
// rewrites className whenever it changes (e.g. a theme tile becoming
// selected), which would silently wipe an imperatively added class and
// hide the element again.

export type RevealVariant = 'up' | 'fade' | 'scale' | 'line' | 'spin' | 'tilt' | 'draw';

export const reveal = (delay = 0, variant: RevealVariant = 'up', style?: CSSProperties) => ({
	'data-reveal': variant,
	style: { ...style, '--reveal-delay': `${delay}ms` } as CSSProperties,
});

/** For what is on screen at load (the hero): prerendered already revealed,
 * so the entrance plays from the first paint instead of waiting for the
 * script to download and hydrate. */
export const revealOnLoad = (delay = 0, variant: RevealVariant = 'up', style?: CSSProperties) => ({
	...reveal(delay, variant, style),
	'data-revealed': '',
});

export const useReveal = () => {
	useEffect(() => {
		const elements = [...document.querySelectorAll<HTMLElement>('[data-reveal]:not([data-revealed])')];
		if (!('IntersectionObserver' in window)) {
			elements.forEach((element) => element.setAttribute('data-revealed', ''));
			return;
		}

		const observer = new IntersectionObserver(
			(entries) => {
				for (const entry of entries) {
					if (entry.isIntersecting) {
						entry.target.setAttribute('data-revealed', '');
						observer.unobserve(entry.target);
					}
				}
			},
			// Fire once the element's top passes ~92% of the viewport height.
			{ rootMargin: '0px 0px -8% 0px', threshold: 0 },
		);

		elements.forEach((element) => observer.observe(element));
		return () => observer.disconnect();
	}, []);
};
