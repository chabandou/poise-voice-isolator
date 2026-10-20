// Text that mists or smokes in and out in place, the Home scene's
// stand-in for a CSS blur (see animations.smoke_wisps): at `alpha`
// below 1 the sharp copy fades and faint copies spread round it.
// mist: DialButton._misted_text's eight copies, 3.5 px out at most.
// Otherwise smoke_wisps' two rings (6 and 10 copies, curling round as
// they thin), `spread` px out (worked out in Python: its easing).
import QtQuick

Item {
    id: smoke
    property alias text: core.text
    property alias font: core.font
    property alias color: core.color
    property alias horizontalAlignment: core.horizontalAlignment
    property alias verticalAlignment: core.verticalAlignment
    property alias wrapMode: core.wrapMode
    property real alpha: 1.0
    property bool mist: false
    property real spread: 0.0
    property bool shown: true
    readonly property real fog: 1.0 - alpha
    readonly property bool sharp: fog < (mist ? 0.05 : 0.03)

    width: implicitWidth
    height: implicitHeight
    implicitWidth: core.implicitWidth
    implicitHeight: core.implicitHeight
    baselineOffset: core.baselineOffset
    visible: shown && alpha > 0.01

    Text {
        id: core
        width: smoke.width
        height: smoke.height
        opacity: smoke.sharp ? smoke.alpha
                 : smoke.mist ? smoke.alpha * (1.0 - 0.6 * smoke.fog)
                 : smoke.alpha * (1.0 - smoke.fog) * (1.0 - smoke.fog)
    }
    Repeater {
        model: smoke.sharp ? 0 : (smoke.mist ? 8 : 16)
        Text {
            readonly property bool outer: !smoke.mist && index >= 6
            readonly property real turn: smoke.mist ? index * Math.PI / 4
                : outer ? 1.4 * smoke.fog + 2.0 * Math.PI * (index - 6) / 10
                : 0.6 * smoke.fog + 2.0 * Math.PI * index / 6
            readonly property real reach: smoke.mist ? 3.5 * smoke.fog
                : smoke.spread * (outer ? 1.0 : 0.45)
            x: reach * Math.cos(turn)
            y: reach * Math.sin(turn)
            width: core.width
            height: core.height
            text: core.text
            font: core.font
            color: core.color
            wrapMode: core.wrapMode
            horizontalAlignment: core.horizontalAlignment
            verticalAlignment: core.verticalAlignment
            opacity: smoke.alpha * smoke.fog
                     * (smoke.mist ? 0.1 : outer ? 0.11 : 0.2)
        }
    }
}
