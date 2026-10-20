import { useRef, useState, type KeyboardEvent, type PointerEvent } from 'react';

// Port of stream_denoiser/gui/widgets/dial.py: a 270-degree ring of ticks
// around a power disc. Press the disc to start/stop; drag the ring (or use
// the arrow keys) to set the reduction strength. Idle the lit ticks use the
// secondary colour, while isolating they switch to the accent. Themes whose
// Home breathes (Vigil, Eclipse) breathe the lit ticks on the sky's cycle.

const ATTEN_STRONG = -50;
const ATTEN_GENTLE = -10;

const REF = 300;
const TICKS = 55;
const ARC_START = 135;
const ARC_SPAN = 270;
const MAJOR_EVERY = 9;
const R_OUT = 136;
const R_IN = 118;
const R_IN_MAJOR = 110;
const DISC_R = 88;
const RING_HIT_MIN = 102;
const RING_HIT_MAX = 150;

const clampDb = (db: number) => Math.round(Math.max(ATTEN_STRONG, Math.min(ATTEN_GENTLE, db)));

const strengthFraction = (db: number) => (ATTEN_GENTLE - clampDb(db)) / (ATTEN_GENTLE - ATTEN_STRONG);

const dbFromFraction = (fraction: number) =>
	clampDb(ATTEN_GENTLE - Math.max(0, Math.min(1, fraction)) * (ATTEN_GENTLE - ATTEN_STRONG));

const angleToFraction = (angleDeg: number, previous?: number) => {
	let rel = (((angleDeg - ARC_START) % 360) + 360) % 360;
	if (rel > ARC_SPAN) {
		rel = rel < ARC_SPAN + (360 - ARC_SPAN) / 2 ? ARC_SPAN : 0;
	}
	let fraction = rel / ARC_SPAN;
	if (previous !== undefined && Math.abs(fraction - previous) > 0.5) {
		fraction = previous > 0.5 ? 1 : 0;
	}
	return fraction;
};

const ticks = Array.from({ length: TICKS }, (_, index) => {
	const angle = ((ARC_START + (ARC_SPAN * index) / (TICKS - 1)) * Math.PI) / 180;
	const inner = index % MAJOR_EVERY === 0 ? R_IN_MAJOR : R_IN;
	const c = REF / 2;
	return {
		index,
		x1: c + inner * Math.cos(angle),
		y1: c + inner * Math.sin(angle),
		x2: c + R_OUT * Math.cos(angle),
		y2: c + R_OUT * Math.sin(angle),
	};
});

type DialProps = {
	live: boolean;
	strengthDb: number;
	onToggle: () => void;
	onStrengthChange: (db: number) => void;
	/** The theme's motion is "breath" (themes.py). */
	breath?: boolean;
	className?: string;
};

const Dial = ({ live, strengthDb, onToggle, onStrengthChange, breath = false, className = '' }: DialProps) => {
	const svgRef = useRef<SVGSVGElement>(null);
	const dragRef = useRef<{ fraction: number; moved: boolean } | null>(null);
	const pressRef = useRef(false);
	const [dragging, setDragging] = useState(false);

	const lit = Math.round(TICKS * strengthFraction(strengthDb));

	const localPoint = (event: PointerEvent<SVGSVGElement>) => {
		const rect = svgRef.current!.getBoundingClientRect();
		const scale = REF / rect.width;
		return {
			x: (event.clientX - rect.left) * scale - REF / 2,
			y: (event.clientY - rect.top) * scale - REF / 2,
		};
	};

	const handlePointerDown = (event: PointerEvent<SVGSVGElement>) => {
		const { x, y } = localPoint(event);
		const distance = Math.hypot(x, y);
		if (distance >= RING_HIT_MIN && distance <= RING_HIT_MAX) {
			const fraction = angleToFraction((Math.atan2(y, x) * 180) / Math.PI);
			dragRef.current = { fraction, moved: false };
			setDragging(true);
			onStrengthChange(dbFromFraction(fraction));
			event.currentTarget.setPointerCapture(event.pointerId);
		} else if (distance < DISC_R + 12) {
			pressRef.current = true;
		}
	};

	const handlePointerMove = (event: PointerEvent<SVGSVGElement>) => {
		const drag = dragRef.current;
		if (!drag) {
			return;
		}
		const { x, y } = localPoint(event);
		const fraction = angleToFraction((Math.atan2(y, x) * 180) / Math.PI, drag.fraction);
		drag.fraction = fraction;
		drag.moved = true;
		onStrengthChange(dbFromFraction(fraction));
	};

	const handlePointerUp = (event: PointerEvent<SVGSVGElement>) => {
		if (dragRef.current) {
			dragRef.current = null;
			setDragging(false);
			event.currentTarget.releasePointerCapture(event.pointerId);
			return;
		}
		if (pressRef.current) {
			pressRef.current = false;
			const { x, y } = localPoint(event);
			if (Math.hypot(x, y) < DISC_R + 12) {
				onToggle();
			}
		}
	};

	const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
		if (event.key === 'Enter' || event.key === ' ') {
			event.preventDefault();
			onToggle();
		} else if (event.key === 'ArrowLeft' || event.key === 'ArrowDown') {
			event.preventDefault();
			onStrengthChange(clampDb(strengthDb + 1));
		} else if (event.key === 'ArrowRight' || event.key === 'ArrowUp') {
			event.preventDefault();
			onStrengthChange(clampDb(strengthDb - 1));
		}
	};

	const litClass = live ? 'stroke-accent' : 'stroke-secondary';
	const showHead = live || dragging;

	return (
		<div
			aria-label={`${live ? 'Stop' : 'Start'} isolating. Reduction strength ${strengthDb} dB; use the arrow keys to change it.`}
			aria-pressed={live}
			className={`rounded-full ${className}`}
			onKeyDown={handleKeyDown}
			role="button"
			tabIndex={0}
		>
			<svg
				ref={svgRef}
				className={`dial block h-full w-full select-none ${live ? 'dial--live' : ''} ${breath ? 'dial--breath' : ''}`}
				onPointerCancel={handlePointerUp}
				onPointerDown={handlePointerDown}
				onPointerMove={handlePointerMove}
				onPointerUp={handlePointerUp}
				viewBox={`0 0 ${REF} ${REF}`}
			>
				{ticks.map((tick) => {
					const isLit = tick.index < lit;
					const isHead = showHead && tick.index === lit - 1;
					return (
						<line
							key={tick.index}
							className={`dial__tick ${isLit ? `dial__tick--lit ${isHead ? 'stroke-ink' : litClass}` : 'stroke-muted/30'}`}
							strokeLinecap="round"
							strokeWidth={isHead ? 5 : 4}
							x1={tick.x1}
							x2={tick.x2}
							y1={tick.y1}
							y2={tick.y2}
						/>
					);
				})}

				<circle className="fill-pill stroke-groove" cx="150" cy="150" r={DISC_R} strokeWidth="2" />

				<g className={live ? 'stroke-accent' : 'stroke-secondary'} fill="none" strokeLinecap="round" strokeWidth="5.5" style={{ transition: 'stroke 260ms ease' }}>
					<line x1="150" x2="150" y1="111.75" y2="131.75" />
					<path d="M137.144 122.429 A20 20 0 1 0 162.856 122.429" />
				</g>

				<text className="fill-ink font-heading" fontSize="21" fontWeight="700" textAnchor="middle" x="150" y="191">
					{live ? 'Stop' : 'Start'}
				</text>

				<text className="fill-ink font-heading" fontSize="30" fontWeight="700" textAnchor="middle" x="150" y="276">
					{strengthDb} dB
				</text>
				<text className="fill-muted font-body" fontSize="12" textAnchor="middle" x="150" y="294">
					reduction strength
				</text>
				<text className="fill-muted font-body" fontSize="12" textAnchor="middle" x="52" y="278">
					gentle
				</text>
				<text className="fill-muted font-body" fontSize="12" textAnchor="middle" x="248" y="278">
					strong
				</text>
			</svg>
		</div>
	);
};

export default Dial;
