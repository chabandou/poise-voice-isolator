import { Fragment, useEffect, useRef, useState, type CSSProperties } from 'react';
import { ArrowUpRight, X } from '../icons';
import { REPO_URL } from '../release';
import { reveal } from '../reveal';
import { getLenis } from '../smoothScroll';
import repoMap from '../repo-map.json';

// The repository as a tree: each file's name and a dot for the stop on the
// signal path it serves. Hovering (or focusing) a file brings a card that
// glides from row to row with what it does; clicking opens its outline,
// read from the source at build time (vite.config.ts, scripts/repo-map.mjs).
// src/repo-map.json is the list; the build warns when it falls behind.

type RepoNode = {
	name: string;
	path: string;
	stage?: number;
	desc?: string;
	folded?: boolean;
	children?: RepoNode[];
};

type Snippets = (typeof import('virtual:repo-map-snippets'))['default'];

const SECTIONS = repoMap.sections as Array<{ title: string; nodes: RepoNode[] }>;

const STAGES = ['Drive', 'Host', 'Capture', 'Prepare', 'Isolate'];
const stageName = (stage?: number) => (stage ? STAGES[stage - 1] : 'Supports the rest');
const stageStyle = (stage?: number) => ({ '--stage': stage ? `var(--stage-${stage})` : 'var(--color-muted)' }) as CSSProperties;

const isFolder = (node: RepoNode) => Boolean(node.children) || node.name.endsWith('/');
const githubUrl = (node: RepoNode) =>
	node.path ? `${REPO_URL}/${isFolder(node) ? 'tree' : 'blob'}/master/${node.path.replace(/\/$/, '')}` : REPO_URL;

type Tip = { node: RepoNode; x: number; y: number; above: boolean; snap: boolean };

type RowEvents = {
	onHover: (node: RepoNode, row: HTMLElement) => void;
	onLeave: () => void;
	onOpen: (node: RepoNode, row: HTMLElement) => void;
};

// Snippets load once, on the first hover or click, as their own chunk.
let snippetsPromise: Promise<Snippets> | null = null;
const loadSnippets = () => (snippetsPromise ??= import('virtual:repo-map-snippets').then((module) => module.default));

const Branch = ({ nodes, depth, trail, events }: { nodes: RepoNode[]; depth: number; trail: boolean[]; events: RowEvents }) => (
	<>
		{nodes.map((node, index) => (
			<Entry key={node.path || node.name} depth={depth} events={events} last={index === nodes.length - 1} node={node} trail={trail} />
		))}
	</>
);

const Entry = ({ node, depth, last, trail, events }: { node: RepoNode; depth: number; last: boolean; trail: boolean[]; events: RowEvents }) => {
	const [open, setOpen] = useState(!node.folded);
	const folder = isFolder(node);
	const guide = trail.map((ancestorLast) => (ancestorLast ? '   ' : '│  ')).join('') + (depth ? (last ? '└─ ' : '├─ ') : '');

	return (
		<>
			<button
				aria-expanded={node.children ? open : undefined}
				className={`repo-row ${folder ? 'repo-row--folder' : node.stage ? '' : 'repo-row--support'}`}
				onBlur={events.onLeave}
				onClick={(event) => (node.children ? setOpen(!open) : events.onOpen(node, event.currentTarget))}
				onFocus={(event) => events.onHover(node, event.currentTarget)}
				onMouseEnter={(event) => events.onHover(node, event.currentTarget)}
				onMouseLeave={events.onLeave}
				style={stageStyle(node.stage)}
				type="button"
			>
				<span aria-hidden="true" className="repo-row__guide">{guide}</span>
				<span className="repo-row__name">{node.name}</span>
				{node.children && <span aria-hidden="true" className="repo-row__chevron" data-open={open || undefined} />}
				{node.stage && <span aria-hidden="true" className="repo-row__dot" />}
			</button>
			{node.children && (
				<div className="repo-fold" data-open={open || undefined} inert={!open}>
					<div className="repo-fold__inner">
						<Branch depth={depth + 1} events={events} nodes={node.children} trail={depth ? [...trail, last] : trail} />
					</div>
				</div>
			)}
		</>
	);
};

const RepoMap = () => {
	const [tip, setTip] = useState<Tip | null>(null);
	const [tipVisible, setTipVisible] = useState(false);
	const [openNode, setOpenNode] = useState<RepoNode | null>(null);
	const [isClosing, setIsClosing] = useState(false);
	const [snippets, setSnippets] = useState<Snippets | null>(null);
	const lastRowRef = useRef<HTMLElement | null>(null);
	const closeButtonRef = useRef<HTMLButtonElement>(null);
	const closeTimeoutRef = useRef<number | null>(null);

	const fetchSnippets = () => {
		if (!snippets) loadSnippets().then(setSnippets, () => setSnippets({}));
	};

	const events: RowEvents = {
		onHover: (node, row) => {
			// Touch screens open the outline on tap instead; focus still shows the card.
			if (!row.matches(':focus-visible') && !window.matchMedia('(hover: hover)').matches) return;
			fetchSnippets();
			const rect = row.getBoundingClientRect();
			const above = rect.bottom + 150 > window.innerHeight;
			setTip({
				node,
				x: Math.max(12, Math.min(rect.left + 28, window.innerWidth - 332)),
				y: above ? rect.top - 8 : rect.bottom + 8,
				above,
				snap: !tipVisible,
			});
			setTipVisible(true);
		},
		onLeave: () => setTipVisible(false),
		onOpen: (node, row) => {
			lastRowRef.current = row;
			fetchSnippets();
			if (closeTimeoutRef.current) {
				window.clearTimeout(closeTimeoutRef.current);
				closeTimeoutRef.current = null;
			}
			setTipVisible(false);
			setIsClosing(false);
			setOpenNode(node);
		},
	};

	const closeModal = () => {
		if (!openNode || isClosing) return;
		setIsClosing(true);
		closeTimeoutRef.current = window.setTimeout(() => {
			setOpenNode(null);
			setIsClosing(false);
			closeTimeoutRef.current = null;
			lastRowRef.current?.focus({ preventScroll: true });
		}, 280);
	};

	// The card belongs to a row on screen; scrolling leaves it behind.
	useEffect(() => {
		if (!tipVisible) return;
		const hide = () => setTipVisible(false);
		window.addEventListener('scroll', hide, { passive: true });
		return () => window.removeEventListener('scroll', hide);
	}, [tipVisible]);

	useEffect(() => {
		if (!openNode) return;
		const previousOverflow = document.body.style.overflow;
		document.body.style.overflow = 'hidden';
		// Wheel smoothing scrolls the page itself, past the overflow lock.
		getLenis()?.stop();
		closeButtonRef.current?.focus({ preventScroll: true });
		const handleEscape = (event: KeyboardEvent) => {
			if (event.key === 'Escape') closeModal();
		};
		window.addEventListener('keydown', handleEscape);
		return () => {
			document.body.style.overflow = previousOverflow;
			getLenis()?.start();
			window.removeEventListener('keydown', handleEscape);
		};
		// closeModal only reads state that re-runs this effect when it changes.
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, [openNode, isClosing]);

	useEffect(() => () => {
		if (closeTimeoutRef.current) window.clearTimeout(closeTimeoutRef.current);
	}, []);

	const snippet = openNode && snippets ? snippets[openNode.path] : undefined;

	return (
		<section className="px-6 pb-24 pt-14 md:px-12 md:pb-32 md:pt-20" id="repo-map">
			<div className="mx-auto max-w-6xl">
				<div className="mb-12 max-w-2xl md:mb-14">
					<div className="kicker mb-5" {...reveal(0)}>
						<span className="kicker__dot" />
						open source
					</div>
					<h1 className="font-heading text-[2.7rem] font-bold leading-none text-ink md:text-[3.4rem]" {...reveal(90)}>
						Find your way around the code.
					</h1>
					<p className="mt-5 text-[1.05rem] leading-[1.65] text-muted" {...reveal(180)}>
						Every file in the repository, marked with the stop on the signal path it serves. Hover a file for what it does, click it to look inside.
					</p>
				</div>

				<ol aria-label="The signal path" className="repo-stages mb-12" {...reveal(240, 'fade')}>
					{STAGES.map((name, index) => (
						<li key={name} className="repo-stages__stop" style={stageStyle(index + 1)}>
							<span aria-hidden="true" className="repo-row__dot" />
							{name}
						</li>
					))}
				</ol>

				<div className="grid grid-cols-1 gap-x-10 gap-y-14 md:grid-cols-2 lg:grid-cols-3">
					{SECTIONS.map((section, index) => (
						<div key={section.title} className="min-w-0" {...reveal((index % 3) * 110)}>
							<h3 className="mb-3 border-b border-edge pb-3 font-heading text-[0.95rem] font-semibold uppercase tracking-[0.18em] text-muted">
								{section.title}
							</h3>
							<Branch depth={0} events={events} nodes={section.nodes} trail={[]} />
						</div>
					))}
				</div>
			</div>

			<div
				aria-hidden="true"
				className={`repo-tip card ${tip?.above ? 'repo-tip--above' : ''} ${tip?.snap ? 'repo-tip--snap' : ''}`}
				data-visible={tipVisible || undefined}
				style={{ left: tip?.x ?? 0, top: tip?.y ?? 0, ...stageStyle(tip?.node.stage) }}
			>
				{tip && (
					<>
						<p className="repo-stage-chip">
							<span className="repo-row__dot" />
							{stageName(tip.node.stage)}
						</p>
						<p className="mt-2 font-mono text-[0.85rem] text-ink">{tip.node.name}</p>
						{tip.node.desc && <p className="mt-1 text-[0.9rem] leading-[1.5] text-ink/85">{tip.node.desc}</p>}
						<p className="mt-2 text-[0.75rem] text-muted">{tip.node.children ? 'Click to fold or unfold' : 'Click to look inside'}</p>
					</>
				)}
			</div>

			{openNode && (
				<div
					aria-labelledby="repo-file-title"
					aria-modal="true"
					className={`install-modal-backdrop fixed inset-0 z-[80] flex items-center justify-center bg-bg/75 px-4 py-8 backdrop-blur-md ${isClosing ? 'install-modal-backdrop--closing' : ''}`}
					onClick={closeModal}
					role="dialog"
				>
					<div
						data-lenis-prevent
						className={`install-modal-panel card relative max-h-[90vh] w-full max-w-3xl overflow-y-auto p-6 shadow-2xl md:p-8 ${isClosing ? 'install-modal-panel--closing' : ''}`}
						onClick={(event) => event.stopPropagation()}
						style={stageStyle(openNode.stage)}
					>
						<button
							ref={closeButtonRef}
							aria-label="Close"
							className="btn btn-ghost absolute right-4 top-4 h-10 w-10 p-0"
							onClick={closeModal}
							type="button"
						>
							<X size={18} />
						</button>

						<p className="repo-stage-chip">
							<span className="repo-row__dot" />
							{stageName(openNode.stage)}
						</p>
						<h3 className="mt-3 break-all pr-12 font-mono text-[1.1rem] text-ink md:text-[1.25rem]" id="repo-file-title">
							{openNode.path}
						</h3>
						{openNode.desc && <p className="mt-4 text-[1.1rem] leading-[1.55] text-ink">{openNode.desc}</p>}

						{!snippets ? (
							<div aria-label="Reading the file" className="repo-code repo-code--loading mt-6" role="status">
								<span />
								<span />
								<span />
							</div>
						) : (
							snippet && (
								<>
									{snippet.about && <p className="mt-4 text-[0.98rem] leading-[1.65] text-muted">{snippet.about}</p>}
									{snippet.lines.length > 0 && (
										<pre className="repo-code mt-6">
											<code>
												{snippet.lines.map((line, index) => (
													<Fragment key={index}>
														<span className="repo-code__line" style={{ '--line': index } as CSSProperties}>
															{line.map(([text, kind], part) => (
																<span key={part} className={kind ? `tok-${kind}` : undefined}>
																	{text}
																</span>
															))}
														</span>
														{'\n'}
													</Fragment>
												))}
											</code>
										</pre>
									)}
								</>
							)
						)}

						<div className="mt-7 flex flex-col gap-3 border-t border-white/8 pt-6 sm:flex-row">
							<a className="btn btn-primary px-5 py-3 text-[0.92rem]" href={githubUrl(openNode)} rel="noopener noreferrer" target="_blank">
								View on GitHub
								<ArrowUpRight size={16} />
							</a>
						</div>
					</div>
				</div>
			)}
		</section>
	);
};

export default RepoMap;
