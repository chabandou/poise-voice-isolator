// Mirrors stream_denoiser/gui/themes.py so the site and the app share one
// set of colorways. index.css holds the matching CSS variables per theme;
// this file is the list the theme picker renders.

export type ThemeId = 'halcyon' | 'verdant' | 'eclipse' | 'vigil' | 'ember' | 'orchid';

export type Theme = {
	id: ThemeId;
	label: string;
	blurb: string;
	bg: string;
	card: string;
	accent: string;
	/** The app icon's colour (the logo variant the app shows). */
	icon: string;
	/** What the app's Home card shows behind the dial (themes.py "backdrop"). */
	backdrop: 'lattice' | 'sky';
};

export const THEMES: Theme[] = [
	{ id: 'halcyon', label: 'Halcyon', blurb: 'Signature cyan on deep navy.', bg: '#0a111e', card: '#0f1828', accent: '#5fd5eb', icon: '#5fd5eb', backdrop: 'lattice' },
	{ id: 'verdant', label: 'Verdant', blurb: 'Emerald on forest black, with gold highlights.', bg: '#0a1110', card: '#0f1918', accent: '#35e0a8', icon: '#35e0a8', backdrop: 'lattice' },
	{ id: 'eclipse', label: 'Eclipse', blurb: 'Silver and deep blue on graphite under a slow night sky.', bg: '#0a0a0a', card: '#111111', accent: '#c8c8c8', icon: '#4a83c9', backdrop: 'sky' },
	{ id: 'vigil', label: 'Vigil', blurb: 'Lavender and candle gold under a slow night sky.', bg: '#0a0920', card: '#141131', accent: '#b9a6ff', icon: '#b9a6ff', backdrop: 'sky' },
	{ id: 'ember', label: 'Ember', blurb: 'Warm amber on dark roast.', bg: '#140f0a', card: '#1a130c', accent: '#f5a524', icon: '#f5a524', backdrop: 'lattice' },
	{ id: 'orchid', label: 'Orchid', blurb: 'Hot pink on dark plum, with a sky-blue accent.', bg: '#150d14', card: '#1b1119', accent: '#f472b6', icon: '#f472b6', backdrop: 'lattice' },
];

export const DEFAULT_THEME: ThemeId = 'halcyon';
const STORAGE_KEY = 'poise-theme';

export const isThemeId = (value: unknown): value is ThemeId =>
	THEMES.some((theme) => theme.id === value);

export const applyTheme = (id: ThemeId) => {
	document.documentElement.dataset.theme = id;
	const meta = document.querySelector('meta[name="theme-color"]');
	const theme = THEMES.find((entry) => entry.id === id);
	if (meta && theme) {
		meta.setAttribute('content', theme.bg);
	}
	try {
		window.localStorage.setItem(STORAGE_KEY, id);
	} catch {
		// Storage can be unavailable (private mode); the theme still applies.
	}
};

// Tiny shared store so the picker and the app preview stay in sync.
type Listener = () => void;
const listeners = new Set<Listener>();

export const getTheme = (): ThemeId => {
	const current = document.documentElement.dataset.theme;
	return isThemeId(current) ? current : DEFAULT_THEME;
};

export const setTheme = (id: ThemeId) => {
	applyTheme(id);
	listeners.forEach((listener) => listener());
};

export const subscribeTheme = (listener: Listener) => {
	listeners.add(listener);
	return () => {
		listeners.delete(listener);
	};
};
