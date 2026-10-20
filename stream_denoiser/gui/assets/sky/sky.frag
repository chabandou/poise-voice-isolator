// Poise Voice Isolator - the night sky's fragment shader
//
// Draws the dial card under a QQuickWidget (widgets/sky_gpu.py): the
// page's gradient around the card's rounded corners, the card's fill
// and border, then every layer of the night sky in NightSky.paint's
// order, clipped to the inside of the border, and over it the dial's
// ring of ticks and its needle (the dial widget paints the rest). NightSky.frame works out
// each layer (positions, sizes, colours) on the CPU every frame; this
// only draws them. Lengths are in card px (logical); colours are
// straight RGBA.
//
// No arrays: ShaderEffect maps QML properties to uniforms by name and
// does not fill arrays, hence m0..m17 and s0..s25.
//
// Baked with Qt's qsb by tools/bake_sky_shader.py, which also writes
// sky.qml (one property per uniform below).
#version 440

layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    vec2 size;          // the card
    // The card: outer radius, border width, inner radius.
    vec4 card;
    vec4 fillTop;
    vec4 fillBottom;
    vec4 borderRgba;
    // The page behind it: the card's top left in the page, page size;
    // its radial gradient's centre (fractions), radius and four stops
    // (rgb, position).
    vec4 page;
    vec4 pageGrad;
    vec4 pageStop0;
    vec4 pageStop1;
    vec4 pageStop2;
    vec4 pageStop3;
    // The sky: its clip (x, y, w, h; corners card.z) and the dial
    // (centre, k, ui).
    vec4 skyClip;
    vec4 geo;
    // The pulse's band: radius, clear stop, core stop, core alpha.
    vec4 band;
    vec4 bandRgb;
    // Motes: x, y, radius, alpha (the glow: radius + 2.6 ui, alpha x .22).
    vec4 moteRgb;
    vec4 m0; vec4 m1; vec4 m2; vec4 m3; vec4 m4; vec4 m5;
    vec4 m6; vec4 m7; vec4 m8; vec4 m9; vec4 m10; vec4 m11;
    vec4 m12; vec4 m13; vec4 m14; vec4 m15; vec4 m16; vec4 m17;
    // Sparkles: x, y, size, alpha (the glow: size x 1.5, alpha x .22).
    vec4 sparkRgb;
    vec4 s0; vec4 s1; vec4 s2; vec4 s3; vec4 s4; vec4 s5; vec4 s6;
    vec4 s7; vec4 s8; vec4 s9; vec4 s10; vec4 s11; vec4 s12; vec4 s13;
    vec4 s14; vec4 s15; vec4 s16; vec4 s17; vec4 s18; vec4 s19; vec4 s20;
    vec4 s21; vec4 s22; vec4 s23; vec4 s24; vec4 s25;
    // The shooting star: its arc's start and control points; its end,
    // and the trail's stretch of it (s0, s1: the head at s1); the
    // trail's colour and light; the trail's width at the head and its
    // glow's, the head's radius and its glow's; the head's light, how
    // white its core burns, -, on; the look (the taper at the tail,
    // white by the head, the glows' alphas).
    vec4 meteor;
    vec4 meteorEnd;
    vec4 meteorRgba;
    vec4 meteorGeo;
    vec4 meteorHead;
    vec4 meteorStyle;
    // The aura's two gradients: rgb + on, alpha at three stops, the
    // stops' positions + disc and gradient radius.
    vec4 auraRgb0; vec4 auraA0; vec4 auraP0;
    vec4 auraRgb1; vec4 auraA1; vec4 auraP1;
    // The ring: radius and its pens' widths, then the pens.
    vec4 ring;
    vec4 ringPen0; vec4 ringPen1; vec4 ringPen2;
    // The star: scale, turn (deg); its two squares' own turns (deg);
    // the pens' widths + half its side, then the pens.
    vec4 stars;
    vec4 squares;
    vec4 starW; vec4 starPen0; vec4 starPen1; vec4 starPen2;
    // Beads (alphas), their rgb, radius and the flares' radius; flares.
    vec4 beadsA; vec4 beadsB; vec4 beadRgb; vec4 beadGeo; vec4 flare;
    // Halos: radius, width unit, alpha, on; their colours.
    vec4 halo0; vec4 halo1; vec4 halo2;
    vec4 haloAcc; vec4 haloLight;
    // The dial's ring: its stretch (deg), the needle's angle (deg) and
    // glow width, on; the dial's centre and scale (k). The strokes
    // themselves are in ringData. tickBreath scales the strokes marked
    // breathing (the idle breath: all that moves while the dial rests).
    vec4 tickRing;
    vec4 tickAt;
    float tickBreath;
};

// DialButton._ring_strokes, one column per tick (55) and the needle's
// (column 55); rows: the stroke's rgb, its glow's rgb, (the stroke's
// alpha, the glow's, which breathe: 128 the stroke, 64 its glow), then
// the stroke's inner and outer radius and the glow's, each as two bytes
// (x 256). RGBX, so nothing premultiplies it.
layout(binding = 1) uniform sampler2D ringData;

const vec2 SPARKLE[16] = vec2[16](
    vec2(0.000000, -5.000000), vec2(0.344415, -0.831492),
    vec2(1.838478, -1.838478), vec2(0.831492, -0.344415),
    vec2(5.000000, 0.000000), vec2(0.831492, 0.344415),
    vec2(1.838478, 1.838478), vec2(0.344415, 0.831492),
    vec2(0.000000, 5.000000), vec2(-0.344415, 0.831492),
    vec2(-1.838478, 1.838478), vec2(-0.831492, 0.344415),
    vec2(-5.000000, 0.000000), vec2(-0.831492, -0.344415),
    vec2(-1.838478, -1.838478), vec2(-0.344415, -0.831492));

// The beads sit on the ring every 45 degrees, clockwise from the top.
const vec2 BEAD[8] = vec2[8](
    vec2(0.0, -1.0), vec2(0.70710678, -0.70710678), vec2(1.0, 0.0),
    vec2(0.70710678, 0.70710678), vec2(0.0, 1.0),
    vec2(-0.70710678, 0.70710678), vec2(-1.0, 0.0),
    vec2(-0.70710678, -0.70710678));

float px;   // one device pixel, in card px

// Coverage of a shape at signed distance sd (negative inside).
float cover(float sd) { return clamp(0.5 - sd / px, 0.0, 1.0); }

vec3 over(vec3 col, vec4 c, float cov) {
    return mix(col, c.rgb, clamp(c.a, 0.0, 1.0) * cov);
}

float sdRoundRect(vec2 p, vec2 lo, vec2 hi, float r) {
    vec2 h = (hi - lo) * 0.5;
    vec2 q = abs(p - (lo + hi) * 0.5) - h + r;
    return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - r;
}

// Undoes QPainter::rotate(deg).
vec2 unrotate(vec2 v, float deg) {
    float a = radians(deg);
    float c = cos(a), s = sin(a);
    return vec2(v.x * c + v.y * s, -v.x * s + v.y * c);
}

// A gradient through three (position, alpha) stops, padded.
float ramp(float t, float p0, float a0, float p1, float a1, float p2,
           float a2) {
    if (t <= p0) return a0;
    if (t <= p1) return mix(a0, a1, (t - p0) / max(p1 - p0, 1e-5));
    if (t <= p2) return mix(a1, a2, (t - p1) / max(p2 - p1, 1e-5));
    return a2;
}

vec3 pageColour(float t) {
    vec3 c = pageStop0.rgb;
    c = mix(c, pageStop1.rgb, clamp((t - pageStop0.w)
            / max(pageStop1.w - pageStop0.w, 1e-5), 0.0, 1.0));
    c = mix(c, pageStop2.rgb, clamp((t - pageStop1.w)
            / max(pageStop2.w - pageStop1.w, 1e-5), 0.0, 1.0));
    c = mix(c, pageStop3.rgb, clamp((t - pageStop2.w)
            / max(pageStop3.w - pageStop2.w, 1e-5), 0.0, 1.0));
    return c;
}

// card.w is always 0: loop bounds the compiler cannot see through, so
// Direct3D keeps these loops instead of unrolling them (unrolled, they
// took seconds to compile when the sky first shows).
int dynamic(int n) { return n + int(card.w); }

float segment2(vec2 p, vec2 a, vec2 b) {
    vec2 e = b - a, w = p - a;
    vec2 q = w - e * clamp(dot(w, e) / dot(e, e), 0.0, 1.0);
    return dot(q, q);
}

// The sparkle mirrors onto itself across both axes and both diagonals:
// folded into the eighth between the +x axis and the diagonal, a point
// is as far from its outline as it was, and only the long arm's edge
// (SPARKLE[4] to [5]) and the short arm's ([5] to [6]) are there. The
// corner between them points in, so inside is inside either edge.
float sdSparkle(vec2 p) {
    p = abs(p);
    if (p.y > p.x) p = p.yx;
    vec2 tip = SPARKLE[4], notch = SPARKLE[5], arm = SPARKLE[6];
    float d = min(segment2(p, tip, notch), segment2(p, notch, arm));
    vec2 e0 = notch - tip, w0 = p - tip, e1 = arm - notch, w1 = p - notch;
    bool inside = e0.x * w0.y - e0.y * w0.x > 0.0
               || e1.x * w1.y - e1.y * w1.x > 0.0;
    return (inside ? -1.0 : 1.0) * sqrt(d);
}

vec3 mote(vec3 col, vec2 p, vec4 m) {
    if (m.w <= 0.0) return col;
    float d = length(p - m.xy);
    float glow = m.z + 2.6 * geo.w;
    if (d > glow + px) return col;
    col = over(col, vec4(moteRgb.rgb, m.w * 0.22), cover(d - glow));
    return over(col, vec4(moteRgb.rgb, m.w), cover(d - m.z));
}

// How much of this pixel a sparkle `scale` across covers. Its arms are
// thinner than a pixel, so the edge ramp of cover() would overstate
// them: sample the pixel's area instead (4 x 4), as QPainter fills it.
// The samples lie within 0.53 px of the centre, and sdSparkle is the
// exact distance to the edge: a pixel further from it than that has
// all 16 on one side, so only the pixels on the edge are sampled.
float sparkleCover(vec2 v, float scale) {
    float edge = sdSparkle(v / scale) * scale;
    if (edge > 0.75 * px) return 0.0;
    if (edge < -0.75 * px) return 1.0;
    float c = 0.0;
    for (int i = 0; i < dynamic(4); ++i) {
        for (int j = 0; j < dynamic(4); ++j) {
            vec2 o = (vec2(float(i), float(j)) - 1.5) * 0.25 * px;
            c += step(sdSparkle((v + o) / scale), 0.0);
        }
    }
    return c / 16.0;
}

vec3 sparkle(vec3 col, vec2 p, vec4 s) {
    if (s.w <= 0.0) return col;
    float big = s.z * 1.5;
    vec2 v = p - s.xy;
    if (length(v) > 5.0 * big + px) return col;
    col = over(col, vec4(sparkRgb.rgb, s.w * 0.22), sparkleCover(v, big));
    return over(col, vec4(sparkRgb.rgb, s.w), sparkleCover(v, s.z));
}

// The point s (0..1) along the shooting star's arc (sky.arc_point).
vec2 arcAt(float s) {
    float v = 1.0 - s;
    return v * v * meteor.xy + 2.0 * v * s * meteor.zw + s * s * meteorEnd.xy;
}

float arcDistance(vec2 p, float s) { return length(p - arcAt(s)); }

// The point of the arc's stretch s0..s1 nearest p, as its s: the
// nearest points of the whole curve solve a cubic (in closed form, after
// Inigo Quilez's sdBezier); clamped into the stretch, with its ends.
float arcNearest(vec2 p, float s0, float s1) {
    vec2 a = meteor.zw - meteor.xy;
    vec2 b = meteor.xy - 2.0 * meteor.zw + meteorEnd.xy;
    vec2 d = meteor.xy - p;
    float kk = 1.0 / max(dot(b, b), 1e-6);
    float kx = kk * dot(a, b);
    float ky = kk * (2.0 * dot(a, a) + dot(d, b)) / 3.0;
    float kz = kk * dot(d, a);
    float q3 = ky - kx * kx;
    float q = kx * (2.0 * kx * kx - 3.0 * ky) + kz;
    float h = q * q + 4.0 * q3 * q3 * q3;
    vec3 roots;
    if (h >= 0.0) {
        h = sqrt(h);
        vec2 x = (vec2(h, -h) - q) * 0.5;
        vec2 uv = sign(x) * pow(abs(x), vec2(1.0 / 3.0));
        roots = vec3(uv.x + uv.y - kx);
    } else {
        float z = sqrt(-q3);
        float v = acos(clamp(q / (q3 * z * 2.0), -1.0, 1.0)) / 3.0;
        float m = cos(v), n = sin(v) * 1.732050808;
        roots = vec3(m + m, -n - m, n - m) * z - kx;
    }
    roots = clamp(roots, s0, s1);
    float best = s0, bestD = arcDistance(p, s0);
    float dist = arcDistance(p, s1);
    if (dist < bestD) { best = s1; bestD = dist; }
    dist = arcDistance(p, roots.x);
    if (dist < bestD) { best = roots.x; bestD = dist; }
    dist = arcDistance(p, roots.y);
    if (dist < bestD) { best = roots.y; bestD = dist; }
    dist = arcDistance(p, roots.z);
    if (dist < bestD) { best = roots.z; }
    return best;
}

// The shooting star as NightSky._paint_meteor draws it: the trail a
// strip along its arc tapering back from the head, lit (t^2) and
// whitened (t^3) toward it (sky.meteor_trail_at, t: 0 at the back, 1
// at the front), its glow first; then the head's soft glow and its core.
vec3 shootingStar(vec3 col, vec2 p) {
    if (meteorHead.w <= 0.0) return col;
    float s0 = meteorEnd.z, s1 = meteorEnd.w;
    vec2 front = arcAt(s1);
    // Nothing to draw beyond the stretch's reach (a sub-arc strays from
    // its chord by at most |b| ds^2 / 4).
    vec2 b = meteor.xy - 2.0 * meteor.zw + meteorEnd.xy;
    float ds = s1 - s0;
    vec2 mid = arcAt(s0 + ds * 0.5);
    float reach = 0.5 * length(front - arcAt(s0)) + 0.25 * length(b) * ds * ds
                  + max(meteorGeo.y * 0.5, meteorGeo.w);
    if (length(p - mid) > reach + px) return col;
    float s = arcNearest(p, s0, s1);
    float d = arcDistance(p, s);
    float t = (s - s0) / max(ds, 1e-5);
    float taper = meteorStyle.x + (1.0 - meteorStyle.x) * t;
    vec3 rgb = mix(meteorRgba.rgb, vec3(1.0), meteorStyle.y * t * t * t);
    float lit = meteorRgba.a * t * t;
    col = over(col, vec4(rgb, lit * meteorStyle.z),
               cover(d - meteorGeo.y * 0.5 * taper));
    col = over(col, vec4(rgb, lit), cover(d - meteorGeo.x * 0.5 * taper));
    if (meteorHead.x <= 0.0) return col;
    float hd = length(p - front);
    float fall = 1.0 - min(hd / meteorGeo.w, 1.0);
    col = over(col, vec4(meteorRgba.rgb, meteorHead.x * meteorStyle.w
                         * fall * fall), cover(hd - meteorGeo.w));
    return over(col, vec4(mix(meteorRgba.rgb, vec3(1.0), meteorHead.y),
                          meteorHead.x), cover(hd - meteorGeo.z));
}

vec3 aura(vec3 col, float d, vec4 rgb, vec4 a, vec4 at) {
    if (rgb.w <= 0.0) return col;
    float alpha = ramp(d / at.w, 0.0, a.x, at.x, a.y, at.y, a.z);
    return over(col, vec4(rgb.rgb, alpha), cover(d - at.z));
}

vec3 circle(vec3 col, float d, float r, float w, vec4 pen) {
    if (pen.a <= 0.0) return col;
    return over(col, pen, cover(abs(d - r) - w * 0.5));
}

// A square's outline as a pen with bevel joins would stroke it.
vec3 square(vec3 col, vec2 q, float half_, float scale, vec4 w, vec4 pen0,
            vec4 pen1, vec4 pen2) {
    vec2 b = abs(q) - vec2(half_);
    float box = abs(length(max(b, 0.0)) + min(max(b.x, b.y), 0.0));
    float diag = abs(q.x) + abs(q.y) - 2.0 * half_;
    vec4 pens[3] = vec4[3](pen0, pen1, pen2);
    for (int i = 0; i < dynamic(3); ++i) {
        if (pens[i].a <= 0.0) continue;
        float e = w[i] * 0.5;
        float sd = max(box - e, (diag - e) * 0.70710678);
        col = over(col, pens[i], cover(sd * scale));
    }
    return col;
}

vec3 halo(vec3 col, float d, vec4 h) {
    if (h.w <= 0.0) return col;
    col = circle(col, d, h.x, 10.0 * h.y, vec4(haloAcc.rgb, h.z * 0.07));
    col = circle(col, d, h.x, 5.0 * h.y, vec4(haloAcc.rgb, h.z * 0.14));
    return circle(col, d, h.x, h.y, vec4(haloLight.rgb, h.z));
}

// Keeps the two items (x, y, size, alpha) nearest p, by the edge of
// their reach.
#define NEAREST(s, reach) {                                         \
        float r = length(p - s.xy) - (reach);                         \
        if (s.w > 0.0 && r < d1) {                                    \
            if (r < d0) { d1 = d0; near1 = near0; d0 = r; near0 = s; }   \
            else { d1 = r; near1 = s; }                                 \
        }                                                               \
    }

// -- the dial's ring --------------------------------------------------------------
const float RING_COLUMNS = 56.0;
const float RING_ROWS = 7.0;

vec3 ringTexel(int column, int row) {
    return texture(ringData, (vec2(float(column), float(row)) + 0.5)
                   / vec2(RING_COLUMNS, RING_ROWS)).rgb;
}

float ringRadius(int column, int row) {
    vec3 v = floor(ringTexel(column, row) * 255.0 + 0.5);
    return (v.r * 256.0 + v.g) / 256.0;
}

// A round-capped stroke along the ray at `angle` (radians) from r0 to
// r1, `width` wide, in dial units (k card px each).
vec3 ringStroke(vec3 col, vec2 q, float angle, float r0, float r1,
                float width, vec4 rgba) {
    if (rgba.a <= 0.0) return col;
    vec2 dir = vec2(cos(angle), sin(angle));
    float sd = length(q - dir * clamp(dot(q, dir), r0, r1)) - width * 0.5;
    return over(col, rgba, cover(sd * tickAt.z));
}

// Stroke `column` and its glow (rows as above): the glow first.
vec3 ringColumn(vec3 col, vec2 q, int column, float angle, float width,
                float glowWidth) {
    vec3 alphaBytes = floor(ringTexel(column, 2) * 255.0 + 0.5);
    vec2 alphas = alphaBytes.rg / 255.0;
    vec2 breathes = vec2(step(128.0, alphaBytes.b),
                         step(64.0, mod(alphaBytes.b, 128.0)));
    alphas *= mix(vec2(1.0), vec2(tickBreath), breathes);
    col = ringStroke(col, q, angle, ringRadius(column, 5),
                     ringRadius(column, 6), glowWidth,
                     vec4(ringTexel(column, 1), alphas.g));
    return ringStroke(col, q, angle, ringRadius(column, 3),
                      ringRadius(column, 4), width,
                      vec4(ringTexel(column, 0), alphas.r));
}

vec3 tickColumn(vec3 col, vec2 q, int i) {
    if (i < 0 || i > 54) return col;
    return ringColumn(col, q, i, radians(135.0 + 5.0 * float(i)), 4.0, 10.0);
}

vec3 dialRing(vec3 col, vec2 p) {
    if (tickRing.w <= 0.0) return col;
    // Into the dial's design square (300 across, centred), unstretched.
    vec2 q = unrotate((p - tickAt.xy) / tickAt.z, tickRing.x);
    float r = length(q);
    if (r < 95.0 || r > 170.0) return col;
    // The ticks run every 5 degrees clockwise from 135 (the gentle
    // end); a pixel is in reach of its nearest tick and the two beside
    // it (a glow is 10 wide, ticks ~10 apart). In drawing order.
    float f = mod(degrees(atan(q.y, q.x)) - 135.0 + 720.0, 360.0) / 5.0;
    if (f > 63.0) f -= 72.0;
    // (Written out, not looped: texture() needs derivatives, which
    // Direct3D cannot take in a loop it cannot unroll.)
    int nearest = int(floor(f + 0.5));
    col = tickColumn(col, q, nearest - 1);
    col = tickColumn(col, q, nearest);
    col = tickColumn(col, q, nearest + 1);
    return ringColumn(col, q, 55, radians(tickRing.y), 5.0, tickRing.z);
}

vec3 sky(vec3 col, vec2 p) {
    vec2 c = geo.xy;
    float d = length(p - c);

    if (band.x > 0.0) {
        float a = ramp(d / band.x, band.y, 0.0, band.z, band.w, 1.0, 0.0);
        col = over(col, vec4(bandRgb.rgb, a), cover(d - band.x));
    }

    // Motes are a few px across: draw the nearest two (as below).
    vec4 near0 = vec4(0.0), near1 = vec4(0.0);
    float d0 = 1e9, d1 = 1e9;
    NEAREST(m0, m0.z + 2.6 * geo.w) NEAREST(m1, m1.z + 2.6 * geo.w)
    NEAREST(m2, m2.z + 2.6 * geo.w) NEAREST(m3, m3.z + 2.6 * geo.w)
    NEAREST(m4, m4.z + 2.6 * geo.w) NEAREST(m5, m5.z + 2.6 * geo.w)
    NEAREST(m6, m6.z + 2.6 * geo.w) NEAREST(m7, m7.z + 2.6 * geo.w)
    NEAREST(m8, m8.z + 2.6 * geo.w) NEAREST(m9, m9.z + 2.6 * geo.w)
    NEAREST(m10, m10.z + 2.6 * geo.w) NEAREST(m11, m11.z + 2.6 * geo.w)
    NEAREST(m12, m12.z + 2.6 * geo.w) NEAREST(m13, m13.z + 2.6 * geo.w)
    NEAREST(m14, m14.z + 2.6 * geo.w) NEAREST(m15, m15.z + 2.6 * geo.w)
    NEAREST(m16, m16.z + 2.6 * geo.w) NEAREST(m17, m17.z + 2.6 * geo.w)
    col = mote(col, p, near1);
    col = mote(col, p, near0);

    // Sparkles are 64 px apart (on the design's card) and at most ~14
    // across: a pixel is in reach of one, two on a small card mid-push.
    // Draw the nearest two (26 inlined copies of the sparkle took
    // Direct3D 19 s to compile when the sky first showed).
    near0 = near1 = vec4(0.0);
    d0 = d1 = 1e9;
    NEAREST(s0, 7.5 * s0.z) NEAREST(s1, 7.5 * s1.z)
    NEAREST(s2, 7.5 * s2.z) NEAREST(s3, 7.5 * s3.z)
    NEAREST(s4, 7.5 * s4.z) NEAREST(s5, 7.5 * s5.z)
    NEAREST(s6, 7.5 * s6.z) NEAREST(s7, 7.5 * s7.z)
    NEAREST(s8, 7.5 * s8.z) NEAREST(s9, 7.5 * s9.z)
    NEAREST(s10, 7.5 * s10.z) NEAREST(s11, 7.5 * s11.z)
    NEAREST(s12, 7.5 * s12.z) NEAREST(s13, 7.5 * s13.z)
    NEAREST(s14, 7.5 * s14.z) NEAREST(s15, 7.5 * s15.z)
    NEAREST(s16, 7.5 * s16.z) NEAREST(s17, 7.5 * s17.z)
    NEAREST(s18, 7.5 * s18.z) NEAREST(s19, 7.5 * s19.z)
    NEAREST(s20, 7.5 * s20.z) NEAREST(s21, 7.5 * s21.z)
    NEAREST(s22, 7.5 * s22.z) NEAREST(s23, 7.5 * s23.z)
    NEAREST(s24, 7.5 * s24.z) NEAREST(s25, 7.5 * s25.z)
    col = sparkle(col, p, near1);
    col = sparkle(col, p, near0);

    col = shootingStar(col, p);

    col = aura(col, d, auraRgb0, auraA0, auraP0);
    col = aura(col, d, auraRgb1, auraA1, auraP1);

    // The ring, the star, the beads.
    col = circle(col, d, ring.x, ring.y, ringPen0);
    col = circle(col, d, ring.x, ring.z, ringPen1);
    col = circle(col, d, ring.x, ring.w, ringPen2);

    // The star, where its squares can reach: from inside their sides to
    // their corners, plus the widest pen.
    float wide = max(starW.x, max(starW.y, starW.z)) * 0.5 + px / stars.x;
    float dl = d / stars.x;
    if (dl > starW.w - wide && dl < starW.w * 1.41421356 + wide) {
        vec2 q = unrotate((p - c) / stars.x, stars.y);
        col = square(col, unrotate(q, squares.x), starW.w, stars.x, starW,
                     starPen0, starPen1, starPen2);
        col = square(col, unrotate(q, squares.y), starW.w, stars.x, starW,
                     starPen0, starPen1, starPen2);
    }

    float reach = max(beadGeo.x, beadGeo.y) + px;
    if (abs(d - ring.x) < reach) {
        float bead[8] = float[8](beadsA.x, beadsA.y, beadsA.z, beadsA.w,
                                 beadsB.x, beadsB.y, beadsB.z, beadsB.w);
        for (int i = 0; i < dynamic(8); ++i) {
            float db = length(p - c - ring.x * BEAD[i]);
            col = over(col, vec4(beadRgb.rgb, bead[i]),
                       cover(db - beadGeo.x));
        }
        if (flare.a > 0.0) {
            for (int i = 0; i < dynamic(8); ++i) {
                float db = length(p - c - ring.x * BEAD[i]);
                col = over(col, flare, cover(db - beadGeo.y));
            }
        }
    }

    col = halo(col, d, halo0);
    col = halo(col, d, halo1);
    col = halo(col, d, halo2);
    return col;
}

void main() {
    vec2 p = qt_TexCoord0 * size;
    px = max(length(fwidth(p)) * 0.70710678, 1e-4);

    // The page behind the card's corners, the card's fill and border.
    vec2 uv = (p + page.xy) / page.zw - pageGrad.xy;
    vec3 col = pageColour(length(uv) / pageGrad.z);
    float outer = sdRoundRect(p, vec2(0.0), size, card.x);
    col = mix(col, mix(fillTop.rgb, fillBottom.rgb, p.y / size.y),
              cover(outer));
    float inner = sdRoundRect(p, vec2(card.y), size - vec2(card.y), card.z);
    col = over(col, borderRgba, cover(outer) * (1.0 - cover(inner)));

    // The sky, inside the border.
    float clipped = sdRoundRect(p, skyClip.xy, skyClip.xy + skyClip.zw,
                                card.z);
    if (clipped < px)
        col = mix(col, sky(col, p), cover(clipped));
    col = dialRing(col, p);

    fragColor = vec4(col, 1.0) * qt_Opacity;
}
