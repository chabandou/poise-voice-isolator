# DESIGN SYSTEM: The Ethereal Signal

## 1. Overview & Creative North Star
The Creative North Star for this design system is **"The Silent Architect."**

In a world of digital noise, this system embodies the calm, precise, and ethical extraction of clarity from chaos. We move beyond the "gamer-neon" trope into a high-end editorial space. The design rejects the rigid, boxed-in layouts of standard SaaS templates in favor of **Intentional Negative Space** and **Atmospheric Depth**.

By using wide horizontal margins, asymmetrical content staggering, and overlapping "glass" containers, we create a sense of high-tech sophistication. The UI doesn't just display information; it breathes, mimicking the organic flow of sound waves being purified.

---

## 2. Colors & Surface Philosophy
The palette is rooted in deep obsidian tones, punctuated by bio-luminescent accents.

### Color Tokens (Material Design Convention)
* **Background:** `#131313` (The void)
* **Primary:** `#FFFFFF` (For high-clarity text)
* **Primary Container (Glow):** `#00FBFB` (Cyan signature)
* **Secondary Fixed Dim:** `#00E479` (Green signature)
* **Surface Tiers:**
* `surface_container_lowest`: `#0E0E0E` (Inset depth)
* `surface_container_low`: `#1C1B1B` (Default sectioning)
* `surface_container_highest`: `#353534` (Elevated glass)

### The "No-Line" Rule
**Explicit Instruction:** Do not use 1px solid borders to define sections. Content blocks must be separated through background shifts. For example, a feature section using `surface_container_low` should sit directly against the `surface` background. If visual separation is needed, use a 40px vertical gap from the spacing scale rather than a line.

### Surface Hierarchy & Nesting
Treat the UI as a series of nested frosted glass sheets.
* **Layer 1 (The Base):** `surface` (#131313).
* **Layer 2 (The Section):** `surface_container_low` (#1C1B1B).
* **Layer 3 (The Component):** `surface_container_highest` (#353534) with a 60% opacity and 20px Backdrop Blur.

### Signature Textures
Main CTAs and Hero accents must utilize a **"Pulse Gradient"**: A linear transition from `primary_container` (#00FBFB) to `secondary_fixed_dim` (#00E479) at a 135-degree angle. This represents the transition from "noise" to "clarity."

---

## 3. Typography
We pair the geometric precision of **Space Grotesk** for headlines with the hyper-readability of **Inter** for functional data.

* **Display (Space Grotesk):** `display-lg` (3.5rem). Use for core value propositions. Letter-spacing should be set to -0.02em to create a "locked-in" premium feel.
* **Headline (Space Grotesk):** `headline-lg` (2rem). Use for section titles. Always in sentence case to maintain the "Calm" vibe.
* **Body (Inter):** `body-lg` (1rem). Set with a line-height of 1.6 for breathability. Use `on_surface_variant` (#B9CAC9) for secondary descriptions to reduce visual fatigue.
* **Labels (Inter):** `label-md` (0.75rem). Use All-Caps with 0.1em tracking for small technical metadata or "Private & Encrypted" badges.

---

## 4. Elevation & Depth
In this system, elevation is a product of light and transparency, not shadow.

* **The Layering Principle:** Depth is achieved by stacking. Place a `surface_container_lowest` card inside a `surface_container_high` section to create an "etched" look.
* **Ambient Glows:** Instead of drop shadows, use "Neon Underglows." Use the `primary_container` color at 10% opacity with a 48px blur, positioned behind primary cards to simulate a soft emission of light.
* **The Ghost Border Fallback:** If a container requires a boundary (e.g., in a complex dashboard), use a `outline_variant` (#3A4A49) at **15% opacity**. It should be felt, not seen.
* **Glassmorphism:** All "floating" elements (Modals, Hovering Nav) must use:
* `background`: `surface_container_highest` at 40% alpha.
* `backdrop-filter`: blur(24px).
* `border`: 1px solid rgba(255, 255, 255, 0.05).

---

## 5. Components

### Buttons (The Kinetic Trigger)
* **Primary:** No border. Background is the "Pulse Gradient." Text is `on_primary_fixed` (#002020).
* *Hover:* Increase brightness by 10% and add a 20px outer glow of `primary_container`.
* **Secondary (Glass):** `surface_container_highest` at 20% opacity. 1px Ghost Border.
* *Hover:* Opacity increases to 40%.
* **Rounding:** All buttons use `full` (9999px) for a "capsule" look, contrasting the `xl` (1.5rem/24px) rounding of the cards.

### Cards & Containers
* **Radius:** Always use `xl` (1.5rem/24px).
* **Separation:** Absolute prohibition of divider lines. Use `spacing-8` (2.75rem) to separate internal card content (e.g., Header from Body).
* **Interactive State:** On hover, a card should shift from `surface_container_low` to `surface_container_high` via a 300ms ease-out transition.

### Input Fields
* **Style:** Minimalist underline or "Soft Inset."
* **Inactive:** `surface_container_highest` background, no border.
* **Focus:** A 1px bottom border using the `primary_container` (Cyan) and a subtle glow.

### Signature Component: The "Signal Monitor"
A specialized graph or visualization component using the `secondary` (Green) color to show voice isolation levels. Use a thin 1.5px stroke width and avoid any grid lines behind the data.

---

## 6. Do's and Don'ts

### Do
* **DO** use extreme vertical whitespace (`spacing-20` and `spacing-24`) to separate major narrative beats.
* **DO** use "Inter" for all functional UI and "Space Grotesk" only for editorial statements.
* **DO** lean into asymmetry. A text block on the left with a floating glass element overlapping the right margin creates a bespoke, high-end feel.

### Don't
* **DON'T** use pure #000000 or pure #FFFFFF for anything other than absolute highlights. It breaks the "Ethical & Calm" vibe.
* **DON'T** use 100% opaque borders. They create "visual traps" that stop the eye from flowing through the page.
* **DON'T** use standard Material or FontAwesome icons. Use ultra-thin (1pt) custom stroke icons to match the futuristic aesthetic.
* **DON'T** use "Heavy" or "Black" font weights. Keep headlines at "Medium" weight to preserve the sophisticated tone.