import { useEffect, useRef } from 'react';

// The app preview's response to the pointer: the window leans a little
// toward it (a few degrees at most, eased rather than snapping), a soft
// sheen follows it across the glass and the shadow shifts the other way.
// It holds still while a button is down (dragging the dial's ring must not
// move the ring under the pointer) and for a beat after, and it is off for
// touch and under reduced motion. The values go to CSS variables on the
// tilting element (index.css .app-tilt): --rx / --ry in degrees, --mx /
// --my the pointer in % of the window, --sheen 0..1.

const MAX_RY = 2.6; // degrees, left-right
const MAX_RX = 2; // degrees, up-down
const EASE = 0.085; // of the remaining distance per 60 Hz frame
const RESUME_MS = 450; // still after the button comes up

export const useWindowMotion = <T extends HTMLElement>() => {
	const ref = useRef<T>(null);

	useEffect(() => {
		const element = ref.current;
		if (!element || !window.matchMedia) {
			return;
		}
		const fine = window.matchMedia('(hover: hover) and (pointer: fine)');
		const still = window.matchMedia('(prefers-reduced-motion: reduce)');

		const now = { rx: 0, ry: 0, mx: 50, my: 50, sheen: 0 };
		const goal = { ...now };
		let pressed = false;
		let heldUntil = 0;
		let frame = 0;
		let last = 0;

		const write = () => {
			const style = element.style;
			style.setProperty('--rx', now.rx.toFixed(3));
			style.setProperty('--ry', now.ry.toFixed(3));
			style.setProperty('--mx', `${now.mx.toFixed(1)}%`);
			style.setProperty('--my', `${now.my.toFixed(1)}%`);
			style.setProperty('--sheen', now.sheen.toFixed(3));
		};

		const tick = (time: number) => {
			const dt = last ? Math.min(64, time - last) : 16.7;
			last = time;
			const f = 1 - Math.pow(1 - EASE, dt / 16.7);
			let moving = false;
			for (const key of ['rx', 'ry', 'mx', 'my', 'sheen'] as const) {
				const delta = goal[key] - now[key];
				if (Math.abs(delta) > (key === 'mx' || key === 'my' ? 0.05 : 0.001)) {
					now[key] += delta * f;
					moving = true;
				} else {
					now[key] = goal[key];
				}
			}
			write();
			frame = moving ? requestAnimationFrame(tick) : 0;
			if (!moving) {
				last = 0;
			}
		};

		const run = () => {
			if (!frame) {
				frame = requestAnimationFrame(tick);
			}
		};

		const enabled = (event: PointerEvent) => event.pointerType !== 'touch' && fine.matches && !still.matches;

		const onMove = (event: PointerEvent) => {
			if (!enabled(event) || pressed || performance.now() < heldUntil) {
				return;
			}
			const rect = element.getBoundingClientRect();
			const nx = Math.max(-1, Math.min(1, ((event.clientX - rect.left) / rect.width) * 2 - 1));
			const ny = Math.max(-1, Math.min(1, ((event.clientY - rect.top) / rect.height) * 2 - 1));
			goal.ry = nx * MAX_RY;
			goal.rx = -ny * MAX_RX;
			goal.mx = 50 + nx * 50;
			goal.my = 50 + ny * 50;
			goal.sheen = 1;
			run();
		};

		const onLeave = () => {
			pressed = false;
			goal.rx = goal.ry = 0;
			goal.sheen = 0;
			run();
		};

		const onDown = () => {
			pressed = true;
		};

		const onUp = () => {
			if (pressed) {
				pressed = false;
				heldUntil = performance.now() + RESUME_MS;
			}
		};

		element.addEventListener('pointermove', onMove);
		element.addEventListener('pointerleave', onLeave);
		element.addEventListener('pointerdown', onDown);
		window.addEventListener('pointerup', onUp);
		window.addEventListener('pointercancel', onUp);
		return () => {
			cancelAnimationFrame(frame);
			element.removeEventListener('pointermove', onMove);
			element.removeEventListener('pointerleave', onLeave);
			element.removeEventListener('pointerdown', onDown);
			window.removeEventListener('pointerup', onUp);
			window.removeEventListener('pointercancel', onUp);
		};
	}, []);

	return ref;
};
