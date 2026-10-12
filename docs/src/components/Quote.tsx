import { reveal } from '../reveal';

const Quote = () => {
	return (
		<section className="border-y border-white/6 bg-deep px-6 py-28 text-center md:py-36">
			<div className="mx-auto max-w-4xl space-y-10">
				<h2 className="font-heading text-[2.6rem] font-bold leading-[1.02] text-ink md:text-[3.8rem]" {...reveal(0)}>
					“Music is everywhere, even when you don’t choose it.”
				</h2>
				<div className="mx-auto h-px w-24 bg-secondary/60" {...reveal(260, 'line')}></div>
				<p className="text-[1.15rem] leading-relaxed text-muted md:text-[1.3rem]" {...reveal(400)}>
					Take back control of your environment.
				</p>
			</div>
		</section>
	);
};

export default Quote;
