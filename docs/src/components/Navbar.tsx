import { useState } from 'react';

const Navbar = () => {
  const [isOpen, setIsOpen] = useState(false);

  const navLinks = [
    { label: 'Home', href: '#home' },
    { label: 'Features', href: '#features' },
    { label: 'Github', href: 'https://github.com/chabandou/poise-voice-isolator' },
  ];

  return (
    <header className="fixed top-0 z-50 w-full bg-[#131313]/40 backdrop-blur-2xl glassmorphism-edge">
      <nav className="mx-auto flex w-full max-w-360 items-center justify-between px-6 py-5 md:px-12 md:py-8">
        <div className='flex gap-2 items-center justify-center'>
          <div>
            <img src="/icon.png" className='w-8 rounded-lg' alt="" />
          </div>
          <div className="font-['Space_Grotesk'] text-2xl font-medium tracking-tighter text-white">
            Poise
          </div>
        </div>

        <div className="hidden items-center gap-12 font-['Space_Grotesk'] font-medium tracking-[-0.02em] md:flex">
          {navLinks.map((link, index) => (
            <a
              key={link.label}
              className={`transition-all duration-300 ${
                index === 0
                  ? 'border-b border-[#00FBFB]/50 pb-1 font-medium text-white'
                  : 'text-[#B9CAC9] hover:text-white hover:opacity-80'
              }`}
              href={link.href}
            >
              {link.label}
            </a>
          ))}
        </div>

        <div className="hidden md:block">
          <a className="pulse-gradient rounded-full px-8 py-3 font-medium text-on-primary-fixed transition-all hover:opacity-90 active:scale-95" href='#downloads'>
            Download Now
          </a>
        </div>

        <button
          aria-controls="mobile-nav"
          aria-expanded={isOpen}
          aria-label="Toggle navigation"
          className="rounded-full bg-surface-container-highest/20 p-2 text-white transition-all hover:bg-surface-container-highest/40 md:hidden"
          onClick={() => setIsOpen((prev) => !prev)}
          type="button"
        >
          <span className="material-symbols-outlined text-[22px]">{isOpen ? 'close' : 'menu'}</span>
        </button>
      </nav>

      {isOpen && (
        <div
          className="mx-6 mb-4 rounded-2xl border border-white/5 bg-[#131313]/80 p-5 backdrop-blur-2xl md:hidden"
          id="mobile-nav"
        >
          <div className="flex flex-col gap-4 font-['Space_Grotesk']">
            {navLinks.map((link, index) => (
              <a
                key={link.label}
                className={`transition-all duration-300 ${
                  index === 0
                    ? 'border-b border-[#00FBFB]/50 pb-1 font-medium text-white'
                    : 'text-[#B9CAC9] hover:text-white hover:opacity-80'
                }`}
                href={link.href}
                onClick={() => setIsOpen(false)}
              >
                {link.label}
              </a>
            ))}
            <a className="pulse-gradient mt-2 rounded-full px-8 py-3 font-medium text-on-primary-fixed transition-all hover:opacity-90 active:scale-95" href='#downloads'>
              Download Now
            </a>
          </div>
        </div>
      )}
    </header>
  );
};

export default Navbar;