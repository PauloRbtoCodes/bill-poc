---
name: Synthetic Intelligence Narrative
colors:
  surface: '#0f1414'
  surface-dim: '#0f1414'
  surface-bright: '#353a39'
  surface-container-lowest: '#0a0f0e'
  surface-container-low: '#171d1c'
  surface-container: '#1b2120'
  surface-container-high: '#262b2a'
  surface-container-highest: '#303635'
  on-surface: '#dee4e2'
  on-surface-variant: '#c7c4d9'
  inverse-surface: '#dee4e2'
  inverse-on-surface: '#2c3131'
  outline: '#918fa2'
  outline-variant: '#464556'
  surface-tint: '#c4c0ff'
  primary: '#c4c0ff'
  on-primary: '#2100a4'
  primary-container: '#4b39ef'
  on-primary-container: '#d4d0ff'
  inverse-primary: '#4e3cf1'
  secondary: '#bdc2ff'
  on-secondary: '#152089'
  secondary-container: '#323da2'
  on-secondary-container: '#abb3ff'
  tertiary: '#ffb59b'
  on-tertiary: '#5b1a00'
  tertiary-container: '#a53600'
  on-tertiary-container: '#ffc8b6'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#e3dfff'
  primary-fixed-dim: '#c4c0ff'
  on-primary-fixed: '#110068'
  on-primary-fixed-variant: '#3311db'
  secondary-fixed: '#dfe0ff'
  secondary-fixed-dim: '#bdc2ff'
  on-secondary-fixed: '#000866'
  on-secondary-fixed-variant: '#303b9f'
  tertiary-fixed: '#ffdbcf'
  tertiary-fixed-dim: '#ffb59b'
  on-tertiary-fixed: '#380d00'
  on-tertiary-fixed-variant: '#812800'
  background: '#0f1414'
  on-background: '#dee4e2'
  surface-variant: '#303635'
  deep-space: '#1B135C'
  electric-indigo: '#4B39EF'
  mist-white: '#FAFFFD'
  soft-lilac: '#727DE4'
typography:
  headline-xl:
    fontFamily: Outfit
    fontSize: 64px
    fontWeight: '700'
    lineHeight: 72px
    letterSpacing: -0.02em
  headline-lg:
    fontFamily: Outfit
    fontSize: 40px
    fontWeight: '600'
    lineHeight: 48px
    letterSpacing: -0.01em
  headline-lg-mobile:
    fontFamily: Outfit
    fontSize: 32px
    fontWeight: '600'
    lineHeight: 40px
  headline-md:
    fontFamily: Outfit
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
  body-lg:
    fontFamily: Inter
    fontSize: 18px
    fontWeight: '400'
    lineHeight: 28px
  body-md:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 24px
  label-md:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '500'
    lineHeight: 20px
    letterSpacing: 0.01em
  label-sm:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '600'
    lineHeight: 16px
    letterSpacing: 0.05em
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  unit: 8px
  container-max: 1280px
  gutter: 24px
  margin-mobile: 16px
  margin-desktop: 48px
---

## Brand & Style

This design system is built for an AI agent platform that emphasizes technical precision, deep intelligence, and fluid automation. The aesthetic is rooted in **Modern Glassmorphism** with a **High-Contrast Dark** foundation. 

The brand personality is visionary yet grounded—it feels like a command center for the future. The interface utilizes deep violets and electric blues to create a sense of vast digital space, while sharp typography and translucent overlays provide the clarity needed for complex AI orchestration. The goal is to evoke a sense of "power under control," where sophisticated technology is made accessible through a refined, cinematic interface.

## Colors

The palette is anchored by **Deep Space (#1B135C)** as the primary canvas color, creating a more sophisticated alternative to pure black. **Electric Indigo (#4B39EF)** serves as the primary action color, providing high-energy focal points for AI interactions and primary buttons.

**Soft Lilac (#727DE4)** is used for secondary interactive elements and decorative gradients, ensuring the UI has depth and a modern "glow" effect. **Mist White (#FAFFFD)** is the exclusive color for text and essential icons, providing maximum legibility against the dark backgrounds. Gradients should primarily flow from Electric Indigo to Soft Lilac to simulate data flow and activity.

## Typography

The typography system pairs the geometric, tech-forward personality of **Outfit** for headlines with the utilitarian clarity of **Inter** for functional text. 

Headlines utilize tight letter-spacing and heavy weights to command attention, mirroring the bold nature of AI innovation. Body text is kept clean and highly legible with generous line heights to ensure long-form technical logs or agent descriptions remain readable. Use `label-sm` in uppercase for section headers or status indicators to provide a structural, "dashboard" feel.

## Layout & Spacing

The design system employs a **12-column fluid grid** for desktop and a **4-column grid** for mobile. A strict 8px spacing power-of-two scale ensures mathematical harmony across all components.

Layouts should favor high-density information center-aligned within a max-width container, surrounded by expansive margins of "Deep Space" to focus the user's attention. Large sections should be separated by vertical padding of 80px-120px on desktop to allow the "Glassmorphic" layers room to breathe. On mobile, margins reduce to 16px to maximize the functional area for AI chat and control interfaces.

## Elevation & Depth

Depth is achieved through **Glassmorphism and Tonal Layering** rather than traditional drop shadows. 

1.  **Base Layer:** Solid `#1B135C`.
2.  **Surface Layer:** Semi-transparent overlays (White at 5-10% opacity) with a `24px` backdrop blur. This creates the "frosted glass" effect for cards and navigation bars.
3.  **Accent Elevation:** Subtle inner glows (1px borders with 20% opacity white) on the top and left edges of components to simulate a light source from the top-left.
4.  **Interactive Depth:** When an element is hovered, increase the backdrop blur and add a faint outer glow using the primary color (`#4B39EF`) at low opacity (15%) to signify "energy" or "activation."

## Shapes

The shape language is **Rounded**, balancing technical precision with organic accessibility. 

Standard components (Cards, Inputs) use a **0.5rem (8px)** corner radius. Larger containers or hero sections use **1rem (16px)** to feel more integrated and modern. Buttons that act as primary triggers for AI agents may use a fully rounded **Pill-shape** to distinguish them from structural layout elements. Borders should be kept thin (1px) and translucent to maintain the glass aesthetic.

## Components

-   **Buttons:** Primary buttons use a solid gradient of Electric Indigo to Soft Lilac with Mist White text. Secondary buttons are "ghost" style with a 1px white border at 20% opacity and a backdrop blur.
-   **Cards:** Use the Glassmorphism style—background: `rgba(255, 255, 255, 0.05)`, backdrop-filter: `blur(20px)`, and a subtle 1px border.
-   **Input Fields:** Deep, recessed backgrounds (`rgba(0, 0, 0, 0.2)`) with a 1px border that glows Electric Indigo when focused.
-   **Chips/Status Badges:** Small, pill-shaped elements with low-opacity fills of the primary color. Use for agent statuses (e.g., "Processing," "Active").
-   **AI Chat Bubble:** User messages should be subtle glass cards; Agent messages should have a subtle Electric Indigo left-border accent to denote "System Output."
-   **Progress Bars:** Thin, 4px height bars using the primary gradient, often accompanied by a faint outer glow to simulate "loading data."