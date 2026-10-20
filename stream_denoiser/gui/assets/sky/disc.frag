// Poise Voice Isolator - the dial's disc, for the Home scene
//
// The breathing dial's disc as DialButton._paint_disc_breath paints it,
// bottom up: the charge's glow around it, its face (a radial gradient
// lit from just above the centre, a 1.5 wide edge), the charge's glow
// inside it and its rim's band, then the keyboard focus ring and the
// power glyph (a stem and a 280-degree arc, round caps). The item
// covers the dial's 300-unit design square (HomeDial.qml); lengths are
// in design units, colours straight RGBA. The charge's parts are drawn
// at full strength and scaled by `charge`, as the widget's cached
// layers were.
//
// Baked with Qt's qsb by tools/bake_sky_shader.py --shader disc (no
// QML is written for it: HomeDial.qml declares its uniforms).
#version 440

layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    // The face: its gradient's centre and 0.7 stops, and its edge.
    vec4 faceTop;
    vec4 faceMid;
    vec4 faceEdge;
    // The charge's tones (accent, the rim's light: rgb) and strength.
    vec4 accentRgb;
    vec4 rimRgb;
    float charge;
    // The focus ring (alpha 0: none) and the glyph's pen.
    vec4 focusRgba;
    vec4 glyphRgba;
    // The stem's lift (design units, + is down) and design units per
    // device pixel.
    float stem;
    float unit;
};

const float C = 150.0;
const float R = 88.0;              // DISC_R
const float GLYPH_Y = 137.75;
const float GLYPH_R = 20.0;

float cover(float sd) { return clamp(0.5 - sd / unit, 0.0, 1.0); }

// Premultiplied `col` under a straight `c` at coverage `cov`.
vec4 over(vec4 col, vec4 c, float cov) {
    float a = c.a * cov;
    return vec4(c.rgb * a, a) + col * (1.0 - a);
}

// Stroke of a round-capped segment a..b.
float segment(vec2 p, vec2 a, vec2 b) {
    vec2 ab = b - a;
    float h = clamp(dot(p - a, ab) / dot(ab, ab), 0.0, 1.0);
    return length(p - a - ab * h);
}

void main() {
    vec2 p = qt_TexCoord0 * 300.0;
    vec2 v = p - vec2(C);
    float d = length(v);
    vec4 col = vec4(0.0);
    if (d > R + 34.0) {
        fragColor = col;
        return;
    }
    float t = d / R;
    if (charge > 0.0) {     // light around the disc
        float g = clamp((d - R) / 34.0, 0.0, 1.0);
        col = over(col, vec4(accentRgb.rgb, 0.26 * (1.0 - g)), charge);
    }
    // The face, then its edge (a QPainter pen, on the circle).
    float face = cover(d - R);
    float f = clamp(length(p - vec2(C, C - 0.1 * R)) / R / 0.7, 0.0, 1.0);
    col = over(col, mix(faceTop, faceMid, f), face);
    col = over(col, faceEdge, cover(abs(d - R) - 0.75));
    if (charge > 0.0) {
        // Glow inside the disc...
        float inner = clamp((t - 0.5) / 0.5, 0.0, 1.0);
        col = over(col, vec4(accentRgb.rgb, 0.34 * inner),
                   charge * cover(d - (R - 0.75)));
        // ...and the rim's band.
        float band = clamp((d - (R - 7.0)) / 6.0, 0.0, 1.0);
        col = over(col, vec4(rimRgb.rgb, 0.8 * band), charge * face);
    }
    if (focusRgba.a > 0.0)
        col = over(col, focusRgba, cover(abs(d - (R + 6.0)) - 1.0));
    if (glyphRgba.a > 0.0 && d < R) {
        // The stem, and the arc open at the top (between 50 and 130
        // degrees, y up), both 5.5 wide with round caps.
        float s = segment(p, vec2(C, GLYPH_Y - 26.0 + stem),
                          vec2(C, GLYPH_Y - 6.0 + stem));
        vec2 q = p - vec2(C, GLYPH_Y);
        float a = degrees(atan(-q.y, q.x));
        float arc = abs(length(q) - GLYPH_R);
        if (a > 50.0 && a < 130.0) {
            vec2 e = GLYPH_R * vec2(cos(radians(50.0)), -sin(radians(50.0)));
            arc = min(length(q - e), length(q - vec2(-e.x, e.y)));
        }
        col = over(col, glyphRgba, cover(min(s, arc) - 2.75));
    }
    fragColor = col * qt_Opacity;
}
