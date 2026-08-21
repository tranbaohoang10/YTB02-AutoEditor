from __future__ import annotations

from dataclasses import dataclass

from .models import AutoEditorError


@dataclass(frozen=True)
class StylePreset:
    name: str
    palette: str
    paper_texture: str
    halftone: str
    cutout_style: str
    typography: str
    composition: str
    lighting_mood: str
    background: str
    finish: str

    def prompt(self) -> str:
        return (
            f"Palette: {self.palette}. Paper texture: {self.paper_texture}. "
            f"Halftone: {self.halftone}. Cutout style: {self.cutout_style}. "
            f"Typography guidance: {self.typography}. Composition: {self.composition}. "
            f"Lighting and mood: {self.lighting_mood}. Background: {self.background}. "
            f"Finish: {self.finish}."
        )


PRESETS = {
    "newsprint-editorial": StylePreset(
        "newsprint-editorial", "charcoal, warm ivory, muted red accents",
        "tactile recycled newsprint grain", "restrained monochrome dot screening",
        "clean editorial photo cutouts with subtle torn edges", "no text or labels",
        "strong documentary focal point, generous negative space", "tense, sober, directional",
        "layered archival paper", "premium magazine editorial, coherent across scenes",
    ),
    "photo-collage": StylePreset(
        "photo-collage", "natural muted photography with two accent colors",
        "layered matte paper", "light print texture", "hand-cut photographic collage",
        "no text", "balanced overlapping layers", "cinematic documentary",
        "soft paper field", "refined analog collage",
    ),
    "modern-flat": StylePreset(
        "modern-flat", "controlled modern flat palette", "subtle uncoated stock",
        "none", "precise vector-like shapes", "no text", "clear geometric hierarchy",
        "even and calm", "minimal solid field", "crisp editorial illustration",
    ),
    "american-retro": StylePreset(
        "american-retro", "faded navy, cream, brick red, mustard", "aged poster stock",
        "visible vintage screen print", "mid-century illustrated cutouts", "no text",
        "bold diagonal period composition", "optimistic but historically grounded",
        "weathered color blocks", "authentic 1950s print finish",
    ),
    "documentary-paper-collage": StylePreset(
        "documentary-paper-collage", "desaturated archival tones", "creased archival paper",
        "subtle photocopy grain", "archival photographs and document fragments",
        "no generated text; blank document areas only", "evidence-board depth without clutter",
        "serious investigative mood", "layered files and paper", "museum-quality documentary collage",
    ),
}


def get_style_preset(name: str) -> StylePreset:
    try:
        return PRESETS[name]
    except KeyError as exc:
        raise AutoEditorError(
            f"Style preset không tồn tại: {name}. Có: {', '.join(sorted(PRESETS))}."
        ) from exc
