const Footer = () => {
	return (
		<footer className="w-full py-20 bg-surface-container-lowest">
			<div className="flex flex-col md:flex-row justify-between items-center px-6 md:px-12 max-w-360 mx-auto gap-8">
				{/* Logo */}
				<div className="font-headline text-[1.05rem] font-semibold tracking-[-0.05em] text-white">
					Poise
				</div>

				{/* Links */}
				<div className="flex gap-8 items-center font-body text-[0.68rem] font-medium uppercase tracking-[0.16em] text-on-surface-variant">
					<a className="hover:text-secondary-fixed-dim transition-colors hidden" href="#">
						Documentation
					</a>
				</div>

				{/* Copyright */}
				<div className="font-body text-[0.68rem] font-medium uppercase tracking-[0.16em] text-center text-on-surface-variant md:text-right">
					©{new Date().getFullYear()} Poise Voice. Pure clarity from chaos.
				</div>
			</div>
		</footer>
	);
};

export default Footer;
