import { useEffect, useState, type MouseEvent } from 'react';
import CtaButton from './CtaButton';

type NavLink = {
  label: string;
  href: string;
  sectionIds?: string[];
};

const navLinks: NavLink[] = [
  { label: 'Home', href: '#home', sectionIds: ['home'] },
  { label: 'Features', href: '#how-it-works', sectionIds: ['how-it-works', 'features'] },
  { label: 'Download', href: '#downloads', sectionIds: ['downloads'] },
];

const Navbar = () => {
  const [isOpen, setIsOpen] = useState(false);
  const [activeSection, setActiveSection] = useState('home');

  const scrollToSection = (href: string) => {
    const targetId = href.startsWith('#') ? href.slice(1) : href;
    const target = document.getElementById(targetId);

    if (!target) {
      return;
    }

    const targetTop = Math.max(0, target.getBoundingClientRect().top + window.scrollY - 120);

    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      window.scrollTo(0, targetTop);
      return;
    }

    const startTop = window.scrollY;
    const distance = targetTop - startTop;
    const duration = 950;
    const startTime = performance.now();

    const easeInOutCubic = (progress: number) =>
      progress < 0.5
        ? 4 * progress * progress * progress
        : 1 - Math.pow(-2 * progress + 2, 3) / 2;

    const step = (currentTime: number) => {
      const elapsed = currentTime - startTime;
      const progress = Math.min(elapsed / duration, 1);
      const easedProgress = easeInOutCubic(progress);

      window.scrollTo(0, startTop + distance * easedProgress);

      if (progress < 1) {
        window.requestAnimationFrame(step);
      }
    };

    window.requestAnimationFrame(step);
  };

  const handleNavClick = (event: MouseEvent<HTMLAnchorElement>, href: string, sectionId?: string) => {
    if (!href.startsWith('#')) {
      return;
    }

    event.preventDefault();

    if (sectionId) {
      setActiveSection(sectionId);
    }

    scrollToSection(href);
  };

  useEffect(() => {
    const trackedSectionIds = [...new Set(navLinks.flatMap((link) => link.sectionIds ?? []))];
    const sections = trackedSectionIds
      .map((sectionId) => document.getElementById(sectionId))
      .filter((section): section is HTMLElement => section !== null);

    const updateActiveSection = () => {
      if (sections.length === 0) {
        return;
      }

      const scrollMarker = window.scrollY + window.innerHeight * 0.35;
      let currentSection = sections[0].id;

      for (const section of sections) {
        if (section.offsetTop <= scrollMarker) {
          currentSection = section.id;
        }
      }

      setActiveSection(currentSection);
    };

    updateActiveSection();
    window.addEventListener('scroll', updateActiveSection, { passive: true });
    window.addEventListener('resize', updateActiveSection);

    return () => {
      window.removeEventListener('scroll', updateActiveSection);
      window.removeEventListener('resize', updateActiveSection);
    };
  }, []);

  const getLinkClasses = (isActive: boolean) =>
    `relative inline-block transition-[color,opacity,transform] duration-300 after:absolute after:-bottom-1 after:left-0 after:h-px after:w-full after:bg-primary-fixed/50 after:transition-opacity after:duration-300 ${
      isActive
        ? '-translate-y-0.5 text-white opacity-100 after:opacity-100'
        : 'translate-y-0 text-on-surface-variant opacity-70 after:opacity-0 hover:-translate-y-0.5 hover:text-white hover:opacity-100'
    }`;

  return (
    <header className="fixed top-0 z-50 w-full bg-background/45 backdrop-blur-2xl glassmorphism-edge">
      <nav className="mx-auto flex w-full max-w-360 items-center justify-between px-6 py-5 md:px-12 md:py-8">
        <div className='flex gap-2 items-center justify-center'>
          <div>
            <img src={`${import.meta.env.BASE_URL}icon.png`} className='h-8 w-8 object-contain' alt="Poise logo" />
          </div>
          <div className="font-headline text-[1.55rem] font-semibold tracking-[-0.06em] text-white">
            Poise
          </div>
        </div>

        <div className="hidden items-center gap-12 font-headline text-[0.95rem] font-medium tracking-[-0.03em] md:flex">
          {navLinks.map((link) => (
            <a
              key={link.label}
              className={getLinkClasses(link.sectionIds?.includes(activeSection) ?? false)}
              href={link.href}
              onClick={(event) => handleNavClick(event, link.href, link.sectionIds?.[0])}
            >
              {link.label}
            </a>
          ))}
        </div>

        <div className="hidden md:block">
          <CtaButton
            className="navbar-cta px-8 py-3 text-[0.96rem] font-semibold"
            href="#downloads"
            icon={<span className="material-symbols-outlined text-[1.25em] leading-none">download</span>}
          >
            Download Now
          </CtaButton>
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
          className="mx-6 mb-4 rounded-2xl border border-white/5 bg-background/80 p-5 backdrop-blur-2xl md:hidden"
          id="mobile-nav"
        >
          <div className="flex flex-col gap-4 font-headline text-[1rem] tracking-[-0.03em]">
            {navLinks.map((link) => (
              <a
                key={link.label}
                className={getLinkClasses(link.sectionIds?.includes(activeSection) ?? false)}
                href={link.href}
                onClick={(event) => {
                  handleNavClick(event, link.href, link.sectionIds?.[0]);
                  setIsOpen(false);
                }}
              >
                {link.label}
              </a>
            ))}
            <CtaButton
              className="navbar-cta mt-2 px-8 py-3 text-[0.96rem] font-semibold"
              href="#downloads"
              icon={<span className="material-symbols-outlined text-[1.25em] leading-none">download</span>}
            >
              Download Now
            </CtaButton>
          </div>
        </div>
      )}
    </header>
  );
};

export default Navbar;
