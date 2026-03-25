const Quote = () => {
	return (
		<section className="bg-surface-container-lowest px-6 py-28 text-center md:py-40">
			<div className="max-w-4xl mx-auto space-y-12">
				<h2 className="font-headline text-[2.35rem] font-semibold leading-[1.04] tracking-[-0.05em] text-white md:text-[3.4rem]">
					"Music is everywhere even when you don't choose it."
				</h2>
				<div className="w-24 h-px bg-primary-fixed/30 mx-auto"></div>
				<p className="font-body text-[1.18rem] italic leading-relaxed text-on-surface-variant md:text-[1.35rem]">
					Take back control of your environment.
				</p>
			</div>
		</section>
	);
};

export default Quote;
