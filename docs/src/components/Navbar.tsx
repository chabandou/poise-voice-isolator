import { useCallback, useEffect, useLayoutEffect, useRef, useState, type MouseEvent } from 'react';
import { DownloadSimpleBold, List, X } from '../icons';
import CtaButton from './CtaButton';
import { PoiseMark } from './Brand';
import { getLenis } from '../smoothScroll';

type NavLink = {
  label: string;
  href: string;
  sectionIds?: string[];
};

const navLinks: NavLink[] = [
  { label: 'Home', href: '#home', sectionIds: ['home'] },
  { label: 'How it works', href: '#how-it-works', sectionIds: ['how-it-works'] },
  { label: 'The app', href: '#app', sectionIds: ['app'] },
  { label: 'Features', href: '#features', sectionIds: ['features'] },
  { label: 'Download', href: '#downloads', sectionIds: ['downloads'] },
];

const Navbar = () => {
  const [isOpen, setIsOpen] = useState(false);
  const [activeSection, setActiveSection] = useState('home');

  // While a nav click is scrolling the page, the highlight stays on the
  // clicked link instead of flickering through every section on the way.
  const scrollLockRef = useRef<string | null>(null);
  const scrollFrameRef = useRef(0);

  const scrollToSection = (href: string, sectionId?: string) => {
    const targetId = href.startsWith('#') ? href.slice(1) : href;
    const target = document.getElementById(targetId);

    if (!target) {
      return;
    }

    window.cancelAnimationFrame(scrollFrameRef.current);
    const targetTop = targetId === 'home'
      ? 0
      : Math.max(0, target.getBoundingClientRect().top + window.scrollY - 120);

    // 'instant' bypasses the stylesheet's scroll-behavior: smooth, which
    // would otherwise turn every animation step into its own smooth scroll.
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      window.scrollTo({ top: targetTop, behavior: 'instant' });
      return;
    }

    scrollLockRef.current = sectionId ?? targetId;
    const startTop = window.scrollY;
    const distance = targetTop - startTop;
    const duration = 950;
    const startTime = performance.now();

    const easeInOutCubic = (progress: number) =>
      progress < 0.5
        ? 4 * progress * progress * progress
        : 1 - Math.pow(-2 * progress + 2, 3) / 2;

    // With wheel smoothing on, Lenis runs the same glide so the two never
    // pull the page in different directions.
    const lenis = getLenis();
    if (lenis) {
      lenis.scrollTo(targetTop, {
        duration: duration / 1000,
        easing: easeInOutCubic,
        force: true,
        onComplete: () => {
          scrollLockRef.current = null;
        },
      });
      return;
    }

    const step = (currentTime: number) => {
      const elapsed = currentTime - startTime;
      const progress = Math.min(elapsed / duration, 1);
      const easedProgress = easeInOutCubic(progress);

      window.scrollTo({ top: startTop + distance * easedProgress, behavior: 'instant' });

      if (progress < 1) {
        scrollFrameRef.current = window.requestAnimationFrame(step);
      } else {
        scrollLockRef.current = null;
      }
    };

    scrollFrameRef.current = window.requestAnimationFrame(step);
  };

  const handleNavClick = (event: MouseEvent<HTMLAnchorElement>, href: string, sectionId?: string) => {
    if (!href.startsWith('#')) {
      return;
    }

    event.preventDefault();

    if (sectionId) {
      setActiveSection(sectionId);
    }

    scrollToSection(href, sectionId);
  };

  useEffect(() => {
    const trackedSectionIds = [...new Set(navLinks.flatMap((link) => link.sectionIds ?? []))];
    const sections = trackedSectionIds
      .map((sectionId) => document.getElementById(sectionId))
      .filter((section): section is HTMLElement => section !== null);

    const updateActiveSection = () => {
      if (sections.length === 0 || scrollLockRef.current) {
        return;
      }

      // The last section can be too short to ever reach the marker, so
      // the bottom of the page always selects it.
      const atBottom = window.scrollY + window.innerHeight >= document.documentElement.scrollHeight - 4;
      const scrollMarker = window.scrollY + window.innerHeight * 0.35;
      let currentSection = sections[0].id;

      for (const section of sections) {
        if (section.offsetTop <= scrollMarker) {
          currentSection = section.id;
        }
      }

      setActiveSection(atBottom ? sections[sections.length - 1].id : currentSection);
    };

    // A wheel/touch/key scroll by the user cancels a nav-click animation.
    const cancelNavScroll = () => {
      if (scrollLockRef.current) {
        window.cancelAnimationFrame(scrollFrameRef.current);
        // (A Lenis glide needs no cancelling: the wheel takes over from it.)
        scrollLockRef.current = null;
        updateActiveSection();
      }
    };

    // Scroll events can outnumber frames; check once per frame at most.
    let pending = 0;
    const onScroll = () => {
      if (!pending) {
        pending = window.requestAnimationFrame(() => {
          pending = 0;
          updateActiveSection();
        });
      }
    };

    updateActiveSection();
    window.addEventListener('scroll', onScroll, { passive: true });
    window.addEventListener('resize', updateActiveSection);
    window.addEventListener('wheel', cancelNavScroll, { passive: true });
    window.addEventListener('touchstart', cancelNavScroll, { passive: true });
    window.addEventListener('keydown', cancelNavScroll);

    return () => {
      window.cancelAnimationFrame(scrollFrameRef.current);
      window.cancelAnimationFrame(pending);
      window.removeEventListener('scroll', onScroll);
      window.removeEventListener('resize', updateActiveSection);
      window.removeEventListener('wheel', cancelNavScroll);
      window.removeEventListener('touchstart', cancelNavScroll);
      window.removeEventListener('keydown', cancelNavScroll);
    };
  }, []);

  // Desktop: one highlight (washing down from the top edge) slides between
  // links. The stacked mobile menu washes from the left like the app's
  // sidebar and swaps in place.
  const linkBarRef = useRef<HTMLDivElement>(null);
  const indicatorRef = useRef<HTMLSpanElement>(null);
  const linkRefs = useRef<Record<string, HTMLAnchorElement | null>>({});
  const activeSectionRef = useRef(activeSection);

  // Moves the highlight straight in the DOM (no re-render). With
  // data-instant set the move jumps; without it the CSS transition slides.
  const placeIndicator = useCallback((sectionId: string, instant: boolean) => {
    const indicator = indicatorRef.current;
    const active = navLinks.find((link) => link.sectionIds?.includes(sectionId));
    const element = active ? linkRefs.current[active.label] : null;
    if (!indicator || !element || element.offsetWidth === 0) {
      return;
    }
    const firstPlacement = indicator.style.opacity !== '1';
    indicator.toggleAttribute('data-instant', instant || firstPlacement);
    indicator.style.width = `${element.offsetWidth}px`;
    indicator.style.height = `${element.offsetHeight}px`;
    indicator.style.transform = `translate(${element.offsetLeft}px, ${element.offsetTop}px)`;
    indicator.style.opacity = '1';
  }, []);

  useLayoutEffect(() => {
    activeSectionRef.current = activeSection;
    placeIndicator(activeSection, false);
  }, [activeSection, placeIndicator]);

  // Layout changes (fonts loading, resizing, the bar appearing at lg) snap
  // the highlight to the active link without animating.
  useEffect(() => {
    const bar = linkBarRef.current;
    if (!bar) {
      return;
    }
    const observer = new ResizeObserver(() => placeIndicator(activeSectionRef.current, true));
    observer.observe(bar);
    return () => observer.disconnect();
  }, [placeIndicator]);

  const getLinkClasses = (isActive: boolean, wash = '') =>
    `rounded-[10px] px-3.5 py-2 transition-colors duration-300 ${
      isActive ? `${wash} text-ink` : 'text-muted hover:text-ink'
    }`;

  return (
    <header className="header-enter fixed top-0 z-50 w-full border-b border-white/6 bg-bg/80 backdrop-blur-md">
      <nav className="mx-auto flex w-full max-w-360 items-center justify-between px-6 py-4 md:px-12 md:py-5">
        <a
          className="flex items-center gap-2.5"
          href="#home"
          onClick={(event) => handleNavClick(event, '#home', 'home')}
        >
          <PoiseMark className="h-9 w-9" />
          <span className="font-heading text-[1.7rem] font-bold leading-none text-ink">Poise</span>
        </a>

        <div ref={linkBarRef} className="relative hidden items-center gap-1 whitespace-nowrap text-[0.92rem] font-medium lg:flex">
          <span
            ref={indicatorRef}
            aria-hidden="true"
            className="nav-indicator nav-wash-top pointer-events-none absolute left-0 top-0 rounded-[10px]"
            style={{ opacity: 0 }}
          />
          {navLinks.map((link) => (
            <a
              key={link.label}
              ref={(element) => {
                linkRefs.current[link.label] = element;
              }}
              aria-current={link.sectionIds?.includes(activeSection) ? 'true' : undefined}
              className={`relative ${getLinkClasses(link.sectionIds?.includes(activeSection) ?? false)}`}
              href={link.href}
              onClick={(event) => handleNavClick(event, link.href, link.sectionIds?.[0])}
            >
              {link.label}
            </a>
          ))}
        </div>

        <div className="hidden lg:block">
          <CtaButton
            className="px-5 py-2.5 text-[0.9rem]"
            href="#downloads"
            icon={<DownloadSimpleBold size={18} />}
            onClick={(event) => handleNavClick(event, '#downloads', 'downloads')}
          >
            Download
          </CtaButton>
        </div>

        <button
          aria-controls="mobile-nav"
          aria-expanded={isOpen}
          aria-label="Toggle navigation"
          className="btn btn-ghost h-10 w-10 p-0 lg:hidden"
          onClick={() => setIsOpen((prev) => !prev)}
          type="button"
        >
          {isOpen ? <X size={20} /> : <List size={20} />}
        </button>
      </nav>

      {isOpen && (
        <div
          className="card mx-6 mb-4 p-4 md:mx-12 lg:hidden"
          id="mobile-nav"
        >
          <div className="flex flex-col gap-1 text-[1rem] font-medium">
            {navLinks.map((link) => (
              <a
                key={link.label}
                className={getLinkClasses(link.sectionIds?.includes(activeSection) ?? false, 'nav-wash')}
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
              className="mt-3 px-5 py-3 text-[0.95rem]"
              href="#downloads"
              icon={<DownloadSimpleBold size={18} />}
              onClick={(event) => {
                handleNavClick(event, '#downloads', 'downloads');
                setIsOpen(false);
              }}
            >
              Download
            </CtaButton>
          </div>
        </div>
      )}
    </header>
  );
};

export default Navbar;
