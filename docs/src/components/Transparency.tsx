import type { CSSProperties } from 'react';
import { CodeSimple, Cpu, WifiSlash } from '../icons';
import { Emblem, Lattice } from './Brand';
import { RELEASE } from '../release';
import { reveal } from '../reveal';

const points = [
	{
		title: 'Local AI models',
		Icon: Cpu,
		body: 'DeepFilterNet3 and RNNoise run on your CPU. No cloud service and no GPU required.',
	},
	{
		title: 'No internet required after install',
		Icon: WifiSlash,
		body: 'Works in airplane mode or on locked-down, offline machines.',
	},
	{
		title: 'Open source, MIT licensed',
		Icon: CodeSimple,
		body: 'Audit the code, report issues, or build your own fork.',
	},
];

const Transparency = () => {
	const { version } = RELEASE;

	return (
		<section className="px-6 py-24 md:px-12 md:py-32">
			<div className="card relative mx-auto max-w-6xl overflow-hidden p-8 md:p-16" {...reveal(0, 'scale')}>
				<Lattice className="text-accent opacity-40" />
				<div className="relative flex flex-col items-center justify-between gap-12 md:flex-row">
					<div className="max-w-xl space-y-8">
						<div className="kicker" {...reveal(150)}>
							<span className="kicker__dot" />
							on-device
						</div>

						<h2 className="font-heading text-[2.7rem] font-bold leading-none text-ink md:text-[3.4rem]" {...reveal(240)}>
							Technically transparent.
						</h2>

						<ul className="space-y-6">
							{points.map(({ title, Icon, body }, index) => (
								<li key={title} className="flex items-start gap-4" {...reveal(340 + index * 110)}>
									<span className="icon-chip h-10 w-10 rounded-[10px]">
										<Icon size={20} />
									</span>
									<div>
										<p className="text-[1.05rem] font-semibold text-ink">{title}</p>
										<p className="text-[0.98rem] leading-[1.65] text-muted">{body}</p>
									</div>
								</li>
							))}
						</ul>
					</div>

					{/* The app's About page */}
					<div className="flex w-full max-w-[22rem] flex-col items-center text-center">
						<div className="aspect-square w-[78%]" {...reveal(0, 'draw')}>
							<Emblem className="h-full w-full" />
						</div>
						{/* The caption follows once the emblem has drawn (index.css .emblem-caption). */}
						<p className="emblem-caption mt-6 font-heading text-[1.9rem] font-bold leading-none text-ink">
							Poise Voice Isolator
						</p>
						<p className="emblem-caption mt-3 h-5 font-mono text-[0.85rem] text-secondary" style={{ '--caption-delay': '90ms' } as CSSProperties}>
							{version ?? ''}
						</p>
						<p className="emblem-caption mt-2 text-[0.95rem] text-ink/90" style={{ '--caption-delay': '180ms' } as CSSProperties}>
							Real-time voice isolation. Runs 100% on-device.
						</p>
					</div>
				</div>
			</div>
		</section>
	);
};

export default Transparency;
