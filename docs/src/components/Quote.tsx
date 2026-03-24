const Quote = () => {
	return (
		<section className="bg-surface-container-lowest px-6 py-28 text-center md:py-40">
			<div className="max-w-4xl mx-auto space-y-12">
				<h2 className="font-headline text-[2.5rem] md:text-5xl text-white leading-tight font-medium">
					"Music is everywhere even when you don't choose it."
				</h2>
				<div className="w-24 h-px bg-primary-fixed/30 mx-auto"></div>
				<p className="font-body text-2xl text-on-surface-variant italic">
					Take back control of your environment.
				</p>
			</div>
		</section>
	);
};

export default Quote;
