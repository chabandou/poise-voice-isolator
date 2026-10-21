import { Cpu, Lightning, LockSimple, MoonStars, SpeakerHigh, Tray } from '../icons';
import { reveal } from '../reveal';

const features = [
	{
		title: 'Real-time',
		Icon: Lightning,
		body: 'Audio is cleaned in ~10 ms frames as it plays, so speech stays in sync with the video.',
	},
	{
		title: 'System-wide',
		Icon: SpeakerHigh,
		body: 'Browsers, apps, and video calls are all covered. No per-app plugins to configure.',
	},
	{
		title: '100% on-device',
		Icon: LockSimple,
		body: 'Your audio never leaves your computer. No account, no telemetry, and it works offline.',
	},
	{
		title: 'Two models',
		Icon: Cpu,
		body: 'DeepFilterNet3 removes music and keeps voices. RNNoise is a lighter model for weaker CPUs.',
	},
	{
		title: 'Skips silence',
		Icon: MoonStars,
		body: 'Audio activity detection pauses the model while nothing is playing, so idle time costs almost no CPU.',
	},
	{
		title: 'Stays out of the way',
		Icon: Tray,
		body: 'Lives in the system tray and can keep running after you close the window.',
	},
];

const Grid = () => {
	return (
		<section className="px-6 py-24 md:px-12 md:py-32" id="features">
			<div className="mx-auto max-w-6xl">
				<div className="mb-14 text-center md:mb-16">
					<div className="kicker mb-5" {...reveal(0)}>
						<span className="kicker__dot" />
						features
					</div>
					<h2 className="font-heading text-[2.8rem] font-bold leading-none text-ink md:text-[3.5rem]" {...reveal(90)}>
						Designed for total control.
					</h2>
				</div>

				<div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3 lg:gap-6">
					{features.map(({ title, Icon, body }, index) => (
						<div key={title} className="card group p-8 hover:border-secondary/60" {...reveal((index % 3) * 100 + Math.floor(index / 3) * 80)}>
							<span className="icon-chip mb-7">
								<Icon size={24} />
							</span>
							<h3 className="mb-3 font-heading text-[1.75rem] font-bold leading-none text-ink">{title}</h3>
							<p className="text-[0.98rem] leading-[1.68] text-muted">{body}</p>
						</div>
					))}
				</div>
			</div>
		</section>
	);
};

export default Grid;
