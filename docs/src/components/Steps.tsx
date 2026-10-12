import { DownloadSimple, Power, SlidersHorizontal } from '@phosphor-icons/react';
import { reveal } from '../reveal';

const steps = [
	{
		title: 'Install',
		Icon: DownloadSimple,
		body: 'Grab the Windows installer or the Linux binary. On Windows, the VB-Cable audio route is set up for you.',
	},
	{
		title: 'Start',
		Icon: Power,
		body: 'Press start. Poise captures system audio, cleans it on-device, and plays it on your speakers or headphones.',
	},
	{
		title: 'Tune',
		Icon: SlidersHorizontal,
		body: 'Drag the dial to set the reduction strength, and pick the model that fits what you are listening to.',
	},
];

const Steps = () => {
	return (
		<section className="border-y border-white/6 bg-deep px-6 py-20 md:px-12 md:py-24" id="how-it-works">
			<div className="mx-auto max-w-6xl">
				<div className="grid grid-cols-1 gap-12 md:grid-cols-3 md:gap-14">
					{steps.map(({ title, Icon, body }, index) => (
						<div key={title} className="flex flex-col items-center text-center md:items-start md:text-left" {...reveal(index * 130)}>
							<div className="mb-6 flex items-center gap-4">
								<span className="icon-chip">
									<Icon size={24} />
								</span>
								{/* QLabel#step-num */}
								<span className="flex h-7 w-7 items-center justify-center rounded-full border border-secondary/55 font-heading text-[0.95rem] font-bold text-secondary">
									{index + 1}
								</span>
							</div>
							<h3 className="mb-3 font-heading text-[1.9rem] font-bold leading-none text-ink">{title}</h3>
							<p className="max-w-[20rem] text-[1rem] leading-[1.65] text-muted">{body}</p>
						</div>
					))}
				</div>
			</div>
		</section>
	);
};

export default Steps;
