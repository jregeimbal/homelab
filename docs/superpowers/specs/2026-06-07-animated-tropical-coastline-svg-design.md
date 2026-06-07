# Animated Tropical Coastline SVG Design

**Date:** 2026-06-07  
**Status:** Approved

## Overview

A single self-contained animated SVG file depicting a hand-drawn line art style tropical coastline at sunrise, with a car slowly cruising along the shore.

## Specifications

### Dimensions & Format
- **Ratio:** 16:9 wallpaper format (~1280×720 viewBox)
- **File:** Single `.svg` file with embedded CSS
- **No external dependencies** — fully self-contained

### Scene Elements (back to front)
1. **Sky** — sunrise gradient (deep purple → pink → orange → gold)
2. **Sun** — rises from behind mountains with pulsing glow
3. **Clouds** — 3-4 hand-drawn cloud shapes drifting across the sky
4. **Mountains/cliffs** — layered silhouettes in the background
5. **Ocean** — turquoise/blue gradient with rolling wave layers
6. **Beach/road** — light tan sand with a coastal road
7. **Palm trees** — 2-3 palm trees on the right side
8. **Car** — small sketchy car silhouette cruising on the road

### Animation Table

| Element | Animation | Duration | Loop Type |
|---------|-----------|----------|-----------|
| Sun | Rises from behind mountains, color warms to bright | 12s | Infinite |
| Clouds | Drift left to right at varying speeds | 20-30s | Seamless |
| Waves | Horizontal translate, offset per layer for depth | 3-5s | Seamless |
| Palm leaves | Gentle rotation sway from trunk base | 4-6s | Infinite |
| Car | Slow cruise along road path, stays in frame | 15s | Infinite |

### Visual Style
- **Line art** — all elements drawn with dark strokes (~2px) on a light background
- **Sketchy feel** — slight wobble/jitter on lines using SVG path manipulation
- **Color palette** — warm sunrise tones, minimal fill colors, emphasis on outlines
- **Parallax layers** — background elements move slower than foreground for depth
- **CSS animations** — all motion driven by `@keyframes` with class-based animation triggers

### Technical Approach
- CSS `@keyframes` for all animations embedded in `<style>` tag within the SVG
- `transform-origin` set appropriately for swaying palm leaves and rising sun
- Seamless loops achieved by matching keyframe start/end states (waves, clouds)
- Parallax effect via different animation speeds per layer
